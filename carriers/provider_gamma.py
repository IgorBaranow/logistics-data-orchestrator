import base64
import threading
import time
import traceback

from .base_carrier_integration import BaseCarrierIntegration

try:
    from config import (
        PROVIDER_GAMMA_API_URL_BASE,
        PROVIDER_GAMMA_CLIENT_ID,
        PROVIDER_GAMMA_CLIENT_SECRET,
        PROVIDER_GAMMA_TOKEN_URL,
    )
except ImportError:
    PROVIDER_GAMMA_CLIENT_ID = ""
    PROVIDER_GAMMA_CLIENT_SECRET = ""
    PROVIDER_GAMMA_TOKEN_URL = ""
    PROVIDER_GAMMA_API_URL_BASE = ""


class ProviderGammaIntegration(BaseCarrierIntegration):
    """
    Integration class for 'Provider Gamma'.
    Demonstrates thread-safe OAuth 2.0 Client Credentials flow,
    token caching with pre-expiration refresh, and graceful fallback
    mechanisms for malformed API query parameters.
    """

    def __init__(self):
        super().__init__("PROVIDER_GAMMA")
        self.client_id = str(PROVIDER_GAMMA_CLIENT_ID)
        self.client_secret = str(PROVIDER_GAMMA_CLIENT_SECRET)
        self.token_url = str(PROVIDER_GAMMA_TOKEN_URL)
        self.api_url_base = str(PROVIDER_GAMMA_API_URL_BASE)

        self.access_token = None
        self.token_expires_at = 0
        self.token_lock = threading.Lock()

    def _refresh_token_if_needed(self):
        """
        Thread-safe token refresh mechanism. Prevents multiple worker threads
        from simultaneously requesting a new token when the current one expires.
        Includes a 5-second buffer to prevent edge-case race conditions.
        """
        if self.access_token and time.time() < self.token_expires_at - 5:
            return

        with self.token_lock:
            # Double-check inside the lock to ensure another thread hasn't already refreshed it
            if self.access_token and time.time() < self.token_expires_at - 5:
                return

            self.logger.info(f"[{self.carrier_code}] Requesting new OAuth 2.0 token...")
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

            headers = {
                "Authorization": f"Basic {encoded_credentials}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            token_data = self._execute_request(
                "POST", self.token_url, headers=headers, timeout=(5, 15), max_retries=3
            )

            if "error" in token_data:
                raise Exception(f"OAuth Token Error: {token_data['error']}")

            self.access_token = token_data.get("access_token")
            expires_in = int(token_data.get("expires_in", 60))
            self.token_expires_at = time.time() + expires_in

    def track_equipment(self, equipment_number: str) -> dict:
        try:
            self._refresh_token_if_needed()
        except Exception as e:
            return {"error": f"Auth Pipeline Failed: {str(e)}"}

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "API-Version": "2.2",
        }

        # Attempt tracking with full parametric scope
        complex_query = f"&milestone_classifier=ACT,EST,PLN&max_results=100"
        url = f"{self.api_url_base}{equipment_number}{complex_query}"
        response = self._execute_request("GET", url, headers=headers)

        # Graceful fallback: If the provider's API rejects the complex query parameters,
        # fallback to a simplified REST path.
        if isinstance(response, dict) and response.get("error", "").startswith("Client Error 400"):
            self.logger.warning(
                f"[{self.carrier_code}] 400 Bad Request on complex query. Falling back to simple endpoint."
            )
            url_simple = f"{self.api_url_base}{equipment_number}"
            response = self._execute_request("GET", url_simple, headers=headers)

        return response

    def normalize_response(self, raw_data) -> dict:
        if isinstance(raw_data, dict) and "error" in raw_data:
            return {"error": f"API Error: {raw_data['error']}"}

        events = raw_data if isinstance(raw_data, list) else raw_data.get("milestones")
        if not events or not isinstance(events, list):
            return {"status": "No Milestones Found"}

        try:
            parsed_events = []
            for event in events:
                if not isinstance(event, dict):
                    continue

                if str(event.get("category_type", "")).upper() not in [
                    "EQUIPMENT",
                    "TRANSPORT",
                ]:
                    continue

                ev_type = str(event.get("milestone_classifier", "Unknown")).upper()
                status = str(
                    event.get("asset_event_type_code")
                    or event.get("transit_event_type_code")
                    or "Unknown"
                ).upper()

                tc = event.get("transit_call") or {}
                loc_code, facility, mode, vessel = "Unknown", "", "Unknown", "TBN"

                if isinstance(tc, dict) and tc:
                    raw_loc_code = str(tc.get("un_loc_code", "")).strip()
                    if raw_loc_code.upper() not in ["", "NONE", "NULL"]:
                        loc_code = raw_loc_code

                    facility_code = str(tc.get("facility_id", "")).strip()
                    other_facility = str(tc.get("alt_facility", "")).strip()
                    loc_name = str(
                        tc.get("geo_location", {}).get("location_name", "")
                    ).strip()

                    # Cascade logic for resolving facility identity
                    if facility_code:
                        facility = facility_code
                    elif other_facility:
                        facility = " ".join(other_facility.split()[:3])
                    else:
                        facility = loc_name

                    # Deduce location code from facility prefix if un_loc_code is missing
                    if loc_code == "Unknown" and facility_code and len(facility_code) >= 5:
                        loc_code = facility_code[:5]

                    if loc_code == "Unknown" and loc_name:
                        loc_code = loc_name

                    mode = str(tc.get("transport_mode", "Unknown")).upper()
                    if mode == "VESSEL":
                        vessel = (tc.get("vessel_details") or {}).get("ship_name", "TBN")

                # Fallback to secondary geo node if transit call lacks coordinates
                if loc_code == "Unknown":
                    el = event.get("event_geo_node") or {}
                    if isinstance(el, dict):
                        raw_el_code = str(el.get("un_loc_code", "")).strip()
                        loc_code = (
                            raw_el_code
                            if raw_el_code.upper() not in ["", "NONE", "NULL"]
                            else str(el.get("location_name", "")).strip()
                        )
                        if not facility:
                            facility = str(el.get("location_name", "")).strip()

                if not loc_code or loc_code.upper() in ["NONE", "NULL"]:
                    loc_code = "Unknown"

                date_raw = event.get("timestamp")
                if date_raw and isinstance(date_raw, str):
                    date_raw = date_raw.replace("Z", "+00:00")
                    display_date, sort_date = date_raw[:10], date_raw
                else:
                    display_date, sort_date = "Unknown", "1970-01-01T00:00:00"

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

            return self._process_standard_events(parsed_events)

        except Exception as e:
            return {
                "error": f"Parsing Error: {str(e)} | Trace: {traceback.format_exc()}"
            }
