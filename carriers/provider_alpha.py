import traceback

from .base_carrier_integration import BaseCarrierIntegration

try:
    from config import PROVIDER_ALPHA_API_KEY
except ImportError:
    PROVIDER_ALPHA_API_KEY = ""


class ProviderAlphaIntegration(BaseCarrierIntegration):
    def __init__(self):
        super().__init__("PROVIDER_ALPHA")
        self.api_key = str(PROVIDER_ALPHA_API_KEY)
        # Obfuscated API endpoint mirroring standard enterprise REST structures
        self.api_url_base = "https://api.alpha-logistics-network.com/v2/telemetry/events?assetRef="

    def track_equipment(self, equipment_number: str) -> dict:
        if not self.api_key:
            return {"error": "Provider Alpha API Key Missing"}

        url = f"{self.api_url_base}{equipment_number}"
        headers = {
            "Accept": "application/json",
            "X-Api-Auth-Token": self.api_key
        }

        # Delegating the HTTP request and retry logic to the Base class
        return self._execute_request(method="GET", url=url, headers=headers)

    def normalize_response(self, raw_data) -> dict:
        if isinstance(raw_data, dict) and "error" in raw_data:
            return {"error": f"API Error: {raw_data['error']}"}

        # Handle both direct list responses and wrapped root keys
        events = raw_data if isinstance(raw_data, list) else raw_data.get("milestones")

        if not events or not isinstance(events, list):
            return {"status": "No Events Found"}

        try:
            valid_events = []
            for event in events:
                if not isinstance(event, dict):
                    continue

                # Filter out empty repositioning events if not needed for physical tracking
                if str(event.get("load_indicator", "")).upper() == "EMPTY":
                    continue

                if str(event.get("category", "")).upper() in [
                    "EQUIPMENT",
                    "TRANSPORT",
                ]:
                    valid_events.append(event)

            if not valid_events:
                return {"status": "Ignored (Empty or No Physical Milestones)"}

            parsed_events = []
            for event_dict in valid_events:
                # Map nested, provider-specific JSON to our unified schema
                ev_type = str(event_dict.get("timing_type", "Unknown")).upper()
                if ev_type == "PLN":
                    ev_type = "EST"

                status_raw = event_dict.get("asset_status_code") or event_dict.get(
                    "transit_status_code"
                )
                status = str(status_raw).upper() if status_raw else "DISC"

                tc = event_dict.get("transit_call") or {}
                loc_code, facility, mode, vessel = "Unknown", "", "Unknown", "TBN"

                if isinstance(tc, dict) and tc:
                    loc_code = tc.get("un_loc_code", "Unknown")
                    facility_code = tc.get("facility_id")
                    other_facility = tc.get("alt_facility_name", "")

                    # Cascade fallback for facility naming
                    if facility_code:
                        facility = facility_code
                    elif other_facility:
                        # Extract primary name parts from unstructured text
                        facility = " ".join(other_facility.split()[:3])
                    else:
                        facility = tc.get("geo_node", {}).get("node_name", "")

                    mode = str(tc.get("transport_mode", "Unknown")).upper()
                    if mode == "VESSEL":
                        vessel = tc.get("vessel_details", {}).get("ship_name", "TBN")

                # Fallback location extraction if transit call is missing geolocation
                if loc_code == "Unknown":
                    el = event_dict.get("event_geo_node") or {}
                    if isinstance(el, dict):
                        loc_code = el.get("un_loc_code", "Unknown")
                        if not facility:
                            facility = el.get("node_name", "")

                date_raw = event_dict.get("timestamp")
                if date_raw and isinstance(date_raw, str):
                    # Normalize ISO 8601 Zulu time to explicit UTC offset
                    date_raw = date_raw.replace("Z", "+00:00")
                    display_date = date_raw[:10]
                    sort_date = date_raw
                else:
                    display_date, sort_date = "Unknown", "1970-01-01T00:00:00"

                # Append to standard format for the Base class pipeline
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

            # Hand over standardized events to the base class for ETA calculation and history building
            return self._process_standard_events(parsed_events)

        except Exception as e:
            return {
                "error": f"Parsing Error: {str(e)} | Trace: {traceback.format_exc()}"
            }
