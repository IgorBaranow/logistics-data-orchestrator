import json
import traceback
from datetime import datetime

from .base_carrier_integration import BaseCarrierIntegration

try:
    from config import PROVIDER_BETA_CLIENT_ID, PROVIDER_BETA_CLIENT_SECRET
except ImportError:
    PROVIDER_BETA_CLIENT_SECRET = ""
    PROVIDER_BETA_CLIENT_ID = ""


class ProviderBetaIntegration(BaseCarrierIntegration):
    """
    Integration class for 'Provider Beta' - a major global EDI/telemetry aggregator.
    Handles deeply nested, conditionally stringified JSON payloads and complex
    timestamp resolutions (ISO 8601 vs UNIX epoch). Features custom business
    overrides for Final Destination (FND) and Port of Discharge (POD) heuristics.
    """

    def __init__(self):
        super().__init__("PROVIDER_BETA")
        self.app_key = str(PROVIDER_BETA_CLIENT_SECRET)
        self.customer_id = str(PROVIDER_BETA_CLIENT_ID)
        # Obfuscated enterprise B2B endpoint
        self.api_url = "https://api.beta-freight-matrix.com/v3/edi-gateway/telemetry/query"

        # Mapping proprietary network status codes to standard DCSA EDI milestones
        self.STATUS_MAP = {
            "NET_010": "MTY",
            "NET_020": "GTIN",
            "NET_030": "LOAD",
            "NET_040": "ARRI",
            "NET_045": "DISC",
            "NET_050": "DEPA",
            "NET_060": "LOAD",
            "NET_067": "DEPA",
            "NET_068": "DEPA",
            "NET_070": "DEPA",
            "NET_080": "ARRI",
            "NET_090": "LOAD",
            "NET_100": "DISC",
            "NET_110": "DEPA",
            "NET_120": "ARRI",
            "NET_130": "DISC",
            "NET_140": "RELS",
            "NET_160": "DEPA",
            "NET_170": "LOAD",
            "NET_190": "DLVR",
            "NET_195": "ARRI",
            "NET_200": "DISC",
            "NET_210": "MTY",
            "NET_220": "RELS",
            "NET_260": "AVAL",
            "NET_277": "ARRI",
            "NET_300": "STUF",
            "NET_320": "STRY",
            "NET_330": "STUF",
            "NET_350": "TRAN",
            "NET_955": "DISC",
            "NET_958": "ARRI",
        }

    def track_equipment(self, equipment_number: str) -> dict:
        if not self.app_key or not self.customer_id:
            return {"error": "Provider Beta API Credentials Missing"}

        headers = {"X-App-Key": self.app_key, "Content-Type": "application/json"}
        payload = {
            "booking_reference": "",
            "bill_of_lading_id": "",
            "asset_id": equipment_number,
            "query_timestamp": "",
            "carrier_scac_override": "BETA",
            "account_id": self.customer_id,
        }

        return self._execute_request(
            "POST", self.api_url, headers=headers, json_payload=payload
        )

    def normalize_response(self, raw_data: dict) -> dict:
        if "error" in raw_data:
            return {"error": f"API Error: {raw_data['error']}"}

        if raw_data.get("faults") and len(raw_data["faults"]) > 0:
            err_msg = raw_data["faults"][0].get("fault_description", "Unknown Error")
            return {"error": f"EDI Gateway Error: {err_msg}"}

        # Handling legacy systems that return nested JSON as an escaped string
        payload_content_str = raw_data.get("asset_telemetry_payload")
        if not payload_content_str:
            return {"status": "No Telemetry Content Found"}

        try:
            content = (
                json.loads(payload_content_str)
                if isinstance(payload_content_str, str)
                else payload_content_str
            )
            asset_details = content.get("asset_details", [])

            # Standardize structural inconsistencies (dict vs list)
            if isinstance(asset_details, dict):
                asset_details = [asset_details]
            if not asset_details:
                return {"status": "No Asset Details Found"}

            events = asset_details[0].get("milestone_list", [])
            if isinstance(events, dict):
                events = [events]
            if not events:
                return {"status": "No Milestones Found"}

            # Extract Global Vessel from deeply nested routing array
            global_vessel = "TBN"
            route_info = asset_details[0].get("routing_manifest") or {}
            transit_legs = route_info.get("transit_leg", [])

            if isinstance(transit_legs, dict):
                transit_legs = [transit_legs]

            for leg in transit_legs:
                if not isinstance(leg, dict):
                    continue
                voyage_data = leg.get("voyage_details") or {}
                vessel_name = (voyage_data.get("discharge_node") or {}).get(
                    "ship_name"
                ) or (voyage_data.get("loading_node") or {}).get("ship_name")

                if vessel_name:
                    global_vessel = vessel_name
                    break

            parsed_events = []
            for event_dict in events:
                if not isinstance(event_dict, dict):
                    continue

                network_event = event_dict.get("network_event") or {}
                network_code = str(network_event.get("network_event_code", "")).upper()
                status = self.STATUS_MAP.get(network_code)

                # Fallback logic if network code is unmapped
                if not status:
                    internal_code = str(event_dict.get("internal_status_code", "")).upper()
                    if "LOAD" in internal_code:
                        status = "LOAD"
                    elif "DISC" in internal_code:
                        status = "DISC"
                    elif "ARRI" in internal_code:
                        status = "ARRI"
                    elif "DEPA" in internal_code:
                        status = "DEPA"
                    elif "GATE IN" in internal_code or "RCVD" in internal_code:
                        status = "GTIN"
                    elif "GATE OUT" in internal_code or "MTY" in internal_code:
                        status = "MTY"
                    else:
                        status = network_code[:4] if network_code else "UNKN"

                # 'E' for Estimated, 'A' for Actual
                indicator = str(network_event.get("timing_indicator", "A")).upper()
                ev_type = "EST" if indicator == "E" else "ACT"

                location_data = event_dict.get("geo_location") or {}
                city_details = location_data.get("city_profile") or {}
                loc_code_data = city_details.get("un_loc_profile") or {}

                loc_code = (
                    loc_code_data.get("un_loc_code")
                    or loc_code_data.get("unLocationCode")
                    or ""
                )

                if not loc_code:
                    city = str(city_details.get("city_name", "")).upper()
                    loc_code = city.replace(" ", "")[:5] if city else "UNKN"

                facility_data = location_data.get("facility_profile") or {}
                facility = facility_data.get("facility_id") or facility_data.get(
                    "facility_name", ""
                )

                # Complex timestamp resolution (ISO 8601 strings vs UNIX epoch)
                try:
                    event_dt = event_dict.get("timestamp_profile") or {}
                    loc_dt = event_dt.get("local_dt") or event_dt.get("Local_DT") or {}

                    text = loc_dt.get("iso_text")
                    if loc_dt and text:
                        dt = datetime.fromisoformat(text.replace("Z", ""))
                        display_date, sort_date = (
                            dt.strftime("%Y-%m-%d"),
                            dt.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    else:
                        time_ms = (loc_dt.get("_value_wrapper") or {}).get("unix_millis") or (
                            event_dt.get("utc_dt") or {}
                        ).get("unix_millis")

                        if time_ms:
                            dt = datetime.fromtimestamp(time_ms / 1000.0)
                            display_date, sort_date = (
                                dt.strftime("%Y-%m-%d"),
                                dt.strftime("%Y-%m-%d %H:%M:%S"),
                            )
                        else:
                            display_date, sort_date = "Unknown", "1970-01-01 00:00:00"
                except Exception:
                    display_date, sort_date = "Unknown", "1970-01-01 00:00:00"

                mode = str(event_dict.get("transport_mode", "Unknown")).upper()
                if mode in ["UNKNOWN", ""]:
                    mode = (
                        "VESSEL"
                        if status in ["ARRI", "DEPA", "LOAD", "DISC"]
                        else "UNKNOWN"
                    )

                parsed_events.append(
                    {
                        "ev_type": ev_type,
                        "status": status,
                        "loc": loc_code,
                        "term": facility,
                        "date": display_date,
                        "sort_date": sort_date,
                        "mode": mode,
                        "vessel": global_vessel,
                    }
                )

            # Route standardized events through the Base Integration pipeline
            base_result = self._process_standard_events(parsed_events)

            # Apply Smart Final Destination Override Heuristics
            if (
                "error" not in base_result
                and base_result.get("status") != "No Valid Events Found"
            ):
                latest_status = base_result["status"]
                curr_term = base_result["terminal"]

                fnd_term = str(
                    route_info.get("final_destination", {})
                    .get("facility_profile", {})
                    .get("facility_id", "")
                ).strip()

                pod_term = str(
                    route_info.get("last_discharge_port", {})
                    .get("facility_profile", {})
                    .get("facility_id", "")
                ).strip()

                if latest_status in ["DLVR", "MTY", "RELS"]:
                    base_result["eta_port"] = "-"
                    base_result["eta_details"] = f"Journey Completed ({latest_status})"
                elif curr_term and (
                    (fnd_term and fnd_term in curr_term)
                    or (pod_term and pod_term in curr_term)
                ):
                    if latest_status in ["ARRI", "DISC", "AVAL"]:
                        base_result["eta_port"] = "-"
                        base_result["eta_details"] = "Arrived at Final PRT"

            return base_result

        except Exception as e:
            return {
                "error": f"Parsing Error: {str(e)} | Trace: {traceback.format_exc()}"
            }
