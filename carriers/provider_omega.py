import base64
import time
import traceback
import uuid

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12

from .base_carrier_integration import BaseCarrierIntegration

try:
    from config import (
        PROVIDER_OMEGA_CERT_PASSWORD,
        PROVIDER_OMEGA_CERT_PATH,
        PROVIDER_OMEGA_CLIENT_ID,
        PROVIDER_OMEGA_SCOPE,
        PROVIDER_OMEGA_TENANT_ID,
    )
except ImportError:
    PROVIDER_OMEGA_CERT_PASSWORD = ""
    PROVIDER_OMEGA_CERT_PATH = ""
    PROVIDER_OMEGA_CLIENT_ID = ""
    PROVIDER_OMEGA_SCOPE = ""
    PROVIDER_OMEGA_TENANT_ID = ""


class ProviderOmegaIntegration(BaseCarrierIntegration):
    """
    Integration class for 'Provider Omega'.
    Demonstrates enterprise-grade mTLS / JWT-based authentication (RFC 7523).
    Extracts RSA private keys from PKCS#12 certificates to sign dynamic JWT
    assertions for OAuth 2.0 token exchange via an Identity and Access Management (IAM) provider.
    """

    def __init__(self):
        super().__init__("PROVIDER_OMEGA")
        self.client_id = PROVIDER_OMEGA_CLIENT_ID
        self.tenant_id = PROVIDER_OMEGA_TENANT_ID
        self.cert_path = PROVIDER_OMEGA_CERT_PATH
        self.cert_password = PROVIDER_OMEGA_CERT_PASSWORD
        self.scope = PROVIDER_OMEGA_SCOPE

        # Obfuscated telemetry endpoint
        self.base_url = (
            "https://api.omega-shipping.com/v3/telemetry/events?assetRef="
        )

        self._access_token = None
        self._token_expires_at = 0

    def _generate_jwt_assertion(self) -> str:
        """
        Generates a signed JWT payload using a local PKCS#12 certificate.
        Used to assert client identity to the IAM provider without sending secrets over the wire.
        """
        cert_path_str = str(self.cert_path or "")
        if not cert_path_str:
            raise ValueError("PROVIDER_OMEGA_CERT_PATH is missing!")

        with open(cert_path_str, "rb") as key_file:
            pfx_data = key_file.read()

        password_bytes = self.cert_password.encode() if self.cert_password else b""
        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            pfx_data, password_bytes
        )

        if certificate is None or private_key is None:
            raise ValueError("Certificate or Private key could not be loaded from PFX.")

        # Static type-checking validation (e.g., for Pylance/Mypy)
        # Ensures the extracted key strictly conforms to RSA signing requirements
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise TypeError(
                "The loaded private key must be an RSA private key for JWT RS256 signing."
            )

        fingerprint = certificate.fingerprint(hashes.SHA1())
        x5t = base64.urlsafe_b64encode(fingerprint).decode("utf-8")

        now = int(time.time())
        payload = {
            # Target audience is the Enterprise IAM token endpoint
            "aud": f"https://iam.enterprise-cloud.net/{self.tenant_id}/oauth2/v2.0/token",
            "iss": self.client_id,
            "sub": self.client_id,
            "jti": str(uuid.uuid4()),
            "nbf": now,
            "exp": now + 600,  # Assertion valid for 10 minutes
        }

        return jwt.encode(payload, private_key, algorithm="RS256", headers={"x5t": x5t})

    def _refresh_token_if_needed(self):
        if self._access_token and time.time() < self._token_expires_at - 60:
            return

        self.logger.info(f"[{self.carrier_code}] Negotiating new IAM token via JWT assertion...")
        jwt_assertion = self._generate_jwt_assertion()
        token_url = (
            f"https://iam.enterprise-cloud.net/{self.tenant_id}/oauth2/v2.0/token"
        )

        payload = {
            "client_id": self.client_id,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": jwt_assertion,
            "grant_type": "client_credentials",
            "scope": self.scope,
        }

        token_data = self._execute_request("POST", token_url, data_payload=payload)
        if "error" in token_data:
            raise Exception(f"IAM Token Exchange Error: {token_data['error']}")

        self._access_token = token_data["access_token"]
        self._token_expires_at = time.time() + token_data.get("expires_in", 3600)

        # Update the persistent session headers for subsequent API calls
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
            }
        )

    def track_equipment(self, equipment_number: str) -> dict:
        try:
            self._refresh_token_if_needed()
        except Exception as e:
            return {"error": f"Enterprise Auth Pipeline Failed: {str(e)}"}

        url = f"{self.base_url}{equipment_number}"
        return self._execute_request("GET", url)

    def normalize_response(self, raw_data: list | dict) -> dict:
        if isinstance(raw_data, dict) and "error" in raw_data:
            return {"error": f"API Error: {raw_data['error']}"}

        if not raw_data or not isinstance(raw_data, list):
            return {"error": "Invalid API Data Structure"}

        try:
            is_laden = False
            parsed_events = []

            for event in raw_data:
                if not isinstance(event, dict):
                    continue

                # State Tracking: Ensure asset is laden to filter out empty repo noise
                if event.get("load_indicator") == "LADEN":
                    is_laden = True

                if str(event.get("category_type", "")).upper() not in [
                    "EQUIPMENT",
                    "TRANSPORT",
                ]:
                    continue

                ev_type = str(event.get("timing_type", "Unknown")).upper()
                status = str(
                    event.get("asset_status_code")
                    or event.get("transit_status_code")
                    or "Unknown"
                ).upper()

                tc = event.get("transit_call") or {}
                el = event.get("event_geo_node") or {}

                loc_code = (
                    tc.get("un_loc_code") or el.get("un_loc_code") or "Unknown"
                )
                f_code = tc.get("facility_id") or el.get("facility_id")
                f_name = el.get("node_name") or tc.get("node_name")

                if f_code:
                    facility = f_code
                elif f_name:
                    facility = f_name
                else:
                    facility = ""

                mode, vessel = "Unknown", "TBN"
                if isinstance(tc, dict) and tc:
                    mode = str(tc.get("transport_mode", "Unknown")).upper()
                    if mode == "VESSEL":
                        vessel = (tc.get("vessel_details") or {}).get("ship_name", "TBN")

                date_raw = event.get("timestamp")
                if date_raw and isinstance(date_raw, str):
                    date_raw = date_raw.replace("Z", "+00:00").replace("T", " ")
                    display_date, sort_date = date_raw[:10], date_raw
                else:
                    display_date, sort_date = "Unknown", "1970-01-01 00:00:00"

                parsed_events.append(
                    {
                        "ev_type": ev_type,
                        "status": status,
                        "loc": loc_code,
                        "term": facility,
                        "date": display_date,
                        "sort_date": sort_date,
                        "mode": mode,
                        "vessel": vessel,
                    }
                )

            # Core Business Rule Enforcement
            if not is_laden:
                return {"status": "Ignored (Empty Asset Routing)"}

            return self._process_standard_events(parsed_events)

        except Exception as e:
            return {
                "error": f"Parsing Error: {str(e)} | Trace: {traceback.format_exc()}"
            }
