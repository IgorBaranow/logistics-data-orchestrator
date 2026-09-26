import traceback

# Soft import to prevent crashes if the key is missing from the environment
try:
    from config import PROVIDER_EPSILON_API_KEY
except ImportError:
    PROVIDER_EPSILON_API_KEY = ""

from .base_carrier_integration import BaseCarrierIntegration


class ProviderEpsilonIntegration(BaseCarrierIntegration):
    """
    Integration class for 'Provider Epsilon'.
    Demonstrates data sanitization (SCAC prefix stripping from booking references)
    and aggregation of highly fragmented JSON responses where telemetry is split
    across multiple dynamic root keys.
    """

    def __init__(self):
        super().__init__("PROVIDER_EPSILON")
        self.api_key = str(PROVIDER_EPSILON_API_KEY)
        self.api_url_base = (
            "https://api.epsilon-network.com/gateway/telemetry/v1/asset-tracking"
        )

    def track_equipment(self, equipment_number: str, booking_ref: str = "") -> dict:
        if not self.api_key:
            return {"error": "Provider Epsilon API Key Missing"}

        # Provider Epsilon strictly requires a Booking Reference
        if not booking_ref or str(booking_ref).strip().lower() in ["", "nan", "none"]:
            return {"error": "Missing Booking Reference (Required for Provider Epsilon)"}

        # --- THE FIX: Strip Provider SCAC prefix from Booking Reference ---
        # Remove the first 4 characters if they match the standard provider SCAC code
        booking_ref = str(booking_ref).strip()
        if booking_ref.upper().startswith("EPSL"):
            booking_ref = booking_ref[4:]
        # -------------------------------------------

        url = f"{self.api_url_base}?bookingReference={booking_ref}&assetReference={equipment_number}"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Gateway-APIKey": self.api_key,
        }

        # Delegating the HTTP request and retry logic to the Base class
        return self._execute_request("GET", url, headers=headers)

    def normalize_response(self, raw_data) -> dict:
        if isinstance(raw_data, dict) and "error" in raw_data:
            return {"error": f"API Error: {raw_data['error']}"}

        # ---------------------------------------------------------
        # THE FIX: Aggregate ALL event lists from fragmented JSON
        # ---------------------------------------------------------
        events = []
        if isinstance(raw_data, list):
            events = raw_data
        elif isinstance(raw_data, dict):
            if "milestones" in raw_data and isinstance(raw_data["milestones"], list):
                events = raw_data["milestones"]
            else:
                # Provider splits events into isolated arrays (e.g., "shipment_event", "transit_event").
                # We dynamically scan root keys and aggregate all valid milestone arrays into a master list.
                for key, val in raw_data.items():
                    if (
                        isinstance(val, list)
                        and len(val) > 0
                        and isinstance(val[0], dict)
                        and "category_type" in val[0]
                    ):
                        events.extend(val)

        if not events:
            return {"status": "No Milestones Found"}

        try:
            valid_events = []

            for event in events:
                if not isinstance(event, dict):
                    continue

                # Ignore empty asset movements (e.g. empty return to depot)
                if str(event.get("load_indicator", "")).upper() == "EMPTY":
                    continue

                # Keep only physical movements
                if str(event.get("category_type", "")).upper() in [
                    "EQUIPMENT",
                    "TRANSPORT",
                ]:
                    valid_events.append(event)

            if not valid_events:
                return {"status": "Ignored (Empty or No Physical Milestones)"}

            parsed_events = []

            for event_dict in valid_events:
                ev_type = str(event_dict.get("timing_type", "Unknown")).upper()

                # Standardize PLN to EST so base_integration handles it smoothly
                if ev_type == "PLN":
                    ev_type = "EST"

                status_raw = event_dict.get("asset_status_code") or event_dict.get(
                    "transit_status_code"
                )
                status = str(status_raw).upper() if status_raw else "Unknown"

                tc = event_dict.get("transit_call") or {}
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
                        vessel_data = tc.get("vessel_details") or {}
                        v_name = vessel_data.get("ship_name")
                        if v_name:
                            vessel = v_name

                # Backup location extraction
                if loc_code == "Unknown":
                    el = event_dict.get("event_geo_node") or {}
                    if isinstance(el, dict):
                        loc_code = el.get("un_loc_code", "Unknown")
                        if not facility:
                            facility = el.get("node_name", "")

                date_raw = event_dict.get("timestamp")
                if date_raw and isinstance(date_raw, str):
                    date_raw = date_raw.replace("Z", "+00:00").replace("T", " ")
                    display_date = date_raw[:10]
                    sort_date = date_raw
                else:
                    display_date = "Unknown"
                    sort_date = "1970-01-01 00:00:00"

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

            # Hand over standard events to the base class for ETA calculation and history building
            return self._process_standard_events(parsed_events)

        except Exception as e:
            return {
                "error": f"Parsing Error: {str(e)} | Trace: {traceback.format_exc()}"
            }
