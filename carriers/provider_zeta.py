import time
import traceback

from .base_carrier_integration import BaseCarrierIntegration

try:
    from config import PROVIDER_ZETA_CLIENT_ID, PROVIDER_ZETA_CLIENT_SECRET
except ImportError:
    PROVIDER_ZETA_CLIENT_ID = ""
    PROVIDER_ZETA_CLIENT_SECRET = ""


class ProviderZetaIntegration(BaseCarrierIntegration):
    """
    Integration class for 'Provider Zeta'.
    Demonstrates pure Server-to-Server OAuth2 Client Credentials flow,
    handling form-urlencoded token requests, and hybrid authentication
    (combining Bearer tokens with custom API Gateway consumer keys).
    """

    def __init__(self):
        super().__init__("PROVIDER_ZETA")
        self.client_id = PROVIDER_ZETA_CLIENT_ID
        self.client_secret = PROVIDER_ZETA_CLIENT_SECRET
        self.access_token = None
        self.token_expires_at = 0

    def _refresh_token_if_needed(self):
        # Includes a 60-second buffer to prevent token expiration mid-flight
        if self.access_token and time.time() < self.token_expires_at - 60:
            return

        self.logger.info(f"[{self.carrier_code}] Requesting new OAuth 2.0 token via Client Credentials...")
        url = "https://api.zeta-logistics.com/oauth2/access_token"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        # Submitting credentials via data_payload for form-urlencoded processing
        token_data = self._execute_request("POST", url, headers=headers, data_payload=data)
        if "error" in token_data:
            raise Exception(f"OAuth Token Error: {token_data['error']}")

        self.access_token = token_data.get("access_token")
        # Hardcoding a safe expiration window based on provider specifications (e.g., 50 minutes)
        self.token_expires_at = time.time() + 3000

    def track_equipment(self, equipment_number: str) -> dict:
        try:
            self._refresh_token_if_needed()
        except Exception as e:
            return {"error": f"Auth Pipeline Failed: {str(e)}"}

        url = f"https://api.zeta-logistics.com/v2/track-and-trace/events?assetReference={equipment_number}"

        # Hybrid authentication: Standard Bearer + Proprietary Consumer Key
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Consumer-Key": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
        }

        return self._execute_request("GET", url, headers=headers)

    def normalize_response(self, raw_data: dict) -> dict:
        if isinstance(raw_data, dict) and "error" in raw_data:
            return {"error": f"API Error: {raw_data['error']}"}

        events = raw_data.get("milestones")
        if not events or not isinstance(events, list):
            return {"error": "Invalid API Data Structure"}

        try:
            is_laden = False
            parsed_events = []

            for event in events:
                if not isinstance(event, dict):
                    continue

                # State Tracking: Ensure the asset was actually carrying cargo at some point
                if (
                    event.get("category_type") == "EQUIPMENT"
                    and event.get("load_indicator") == "LADEN"
                ):
                    is_laden = True

                # Keep only physical movements, ignoring commercial/administrative noise
                if event.get("category_type") not in ["EQUIPMENT", "TRANSPORT"]:
                    continue

                ev_type = event.get("timing_type", "Unknown")
                status = str(
                    event.get("asset_status_code")
                    or event.get("transit_status_code")
                    or event.get("shipment_status_code")
                    or "Unknown"
                ).upper()

                tc = event.get("transit_call") or {}
                loc_code, facility, mode, vessel = "Unknown", "", "Unknown", "TBN"

                if isinstance(tc, dict):
                    loc_code = tc.get("un_loc_code", "Unknown")
                    facility_code = tc.get("facility_id")
                    other_facility = tc.get("alt_facility_name", "")

                    if facility_code:
                        facility = facility_code
                    elif other_facility:
                        facility = " ".join(other_facility.split()[:3])
                    else:
                        facility = tc.get("geo_node", {}).get("node_name", "")

                    mode = tc.get("transport_mode", "Unknown")
                    if mode == "VESSEL":
                        vessel = (tc.get("vessel_details") or {}).get("ship_name", "TBN")

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

            # Core Business Rule Enforcement
            if not is_laden:
                return {"status": "Ignored (Empty Asset Routing)"}

            return self._process_standard_events(parsed_events)

        except Exception as e:
            return {
                "error": f"Parsing Error: {str(e)} | Trace: {traceback.format_exc()}"
            }
