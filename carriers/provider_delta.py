import traceback

from .base_carrier_integration import BaseCarrierIntegration

try:
    from config import PROVIDER_DELTA_CLIENT_ID, PROVIDER_DELTA_CLIENT_SECRET
except ImportError:
    PROVIDER_DELTA_CLIENT_ID = ""
    PROVIDER_DELTA_CLIENT_SECRET = ""


class ProviderDeltaIntegration(BaseCarrierIntegration):
    """
    Integration class for 'Provider Delta'.
    Demonstrates API Gateway header authentication, payload state tracking,
    and business-rule filtering (e.g., rejecting empty asset repositioning telemetry).
    """

    def __init__(self):
        super().__init__("PROVIDER_DELTA")
        self.client_id = PROVIDER_DELTA_CLIENT_ID
        self.client_secret = PROVIDER_DELTA_CLIENT_SECRET

    def track_equipment(self, equipment_number: str) -> dict:
        if not self.client_id or not self.client_secret:
            return {"error": "Provider Delta API Keys Missing"}

        url = f"https://api.delta-logistics.net/external/v2/events/?assetReference={equipment_number}"

        # Using generic Enterprise API Gateway headers (obfuscated from specific vendors like IBM/Apigee)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Gateway-Client-Id": self.client_id,
            "X-Gateway-Client-Secret": self.client_secret,
        }

        return self._execute_request("GET", url, headers=headers)

    def normalize_response(self, raw_data) -> dict:
        if isinstance(raw_data, dict) and "error" in raw_data:
            return {"error": f"API Error: {raw_data['error']}"}

        events = raw_data if isinstance(raw_data, list) else raw_data.get("milestones")
        if not events or not isinstance(events, list):
            return {"error": "Invalid API Data Structure"}

        try:
            is_laden = False
            parsed_events = []

            for event in events:
                if not isinstance(event, dict):
                    continue

                # State Tracking: Determine if the asset is actually carrying cargo (Laden)
                # to filter out empty equipment repositioning noise.
                if str(event.get("category_type", "")).upper() == "EQUIPMENT":
                    if str(event.get("load_indicator", "")).upper() == "LADEN":
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
                loc_code, facility, mode, vessel = "Unknown", "", "Unknown", "TBN"

                if isinstance(tc, dict) and tc:
                    loc_code = tc.get("un_loc_code", "Unknown")
                    facility_code = tc.get("facility_id")
                    other_facility = tc.get("alt_facility_name", "")

                    if facility_code:
                        facility = facility_code
                    elif other_facility:
                        facility = " ".join(other_facility.split()[:3])
                    else:
                        facility = tc.get("geo_node", {}).get("node_name", "")

                    mode = str(tc.get("transport_mode", "Unknown")).upper()
                    if mode == "VESSEL":
                        vessel = (tc.get("vessel_details") or {}).get("ship_name", "TBN")

                if loc_code == "Unknown":
                    el = event.get("event_geo_node") or {}
                    if isinstance(el, dict):
                        loc_code = el.get("un_loc_code", "Unknown")
                        if not facility:
                            facility = el.get("node_name", "")

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
