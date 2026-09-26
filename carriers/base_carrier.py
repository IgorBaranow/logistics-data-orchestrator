import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

import requests
from utils.logger import get_logger


class BaseCarrierIntegration(ABC):
    """
    Abstract base class for global freight carrier integrations.
    Provides shared network session management, resilient retry mechanisms,
    rate-limit handling, and standardized event pipeline processing for EDI/API data.
    """

    def __init__(self, carrier_code: str):
        self.carrier_code = carrier_code
        self.session = requests.Session()
        self.logger = get_logger(f"Integration.Carrier.{self.carrier_code}")

    @abstractmethod
    def track_equipment(self, equipment_number: str) -> Dict[str, Any]:
        """Fetch raw tracking telemetry from the carrier's external API."""
        pass

    @abstractmethod
    def normalize_response(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and map raw carrier-specific JSON to the unified system schema."""
        pass

    def _execute_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        data_payload: Optional[Dict[str, Any]] = None,
        timeout: tuple = (10, 20),
        max_retries: int = 10,
    ) -> Dict[str, Any]:
        """
        Executes HTTP requests with robust fault tolerance.
        Features exponential backoff for HTTP 429 (Rate Limits) and safeguards
        against Edge/WAF layer interceptions (e.g., HTML block pages instead of JSON).
        """
        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_payload,
                    data=data_payload,
                    timeout=timeout,
                )

                # Handle Carrier API Rate Limiting with exponential backoff
                if response.status_code == 429:
                    sleep_time = (1.5 ** attempt) + 2.0
                    self.logger.warning(
                        f"Rate limit exceeded (429). Backing off for {round(sleep_time, 1)}s..."
                    )
                    time.sleep(sleep_time)
                    continue

                if response.status_code == 404:
                    return {"error": "Equipment/Telemetry Not Found"}

                if response.status_code in [400, 401, 403]:
                    self.logger.error(
                        f"Client Error {response.status_code}: {response.text}"
                    )
                    return {
                        "error": f"Client Error {response.status_code}: {response.text}"
                    }

                response.raise_for_status()

                # Mitigate unexpected Edge Provider/WAF responses (HTML/Captcha instead of JSON)
                try:
                    return response.json()
                except ValueError:
                    self.logger.error(
                        f"Non-JSON response intercepted (Status {response.status_code}). "
                        f"Possible Edge/WAF block. Snippet: {response.text[:150]}..."
                    )
                    if attempt == max_retries - 1:
                        return {"error": "Invalid API Response format (WAF Interception)"}
                    time.sleep(3)
                    continue

            except requests.exceptions.RequestException as e:
                self.logger.warning(
                    f"Network fault (Attempt {attempt + 1}/{max_retries}). "
                    f"Retrying in 3s... Details: {str(e)}"
                )

                if attempt == max_retries - 1:
                    self.logger.error(f"Max retries exhausted for endpoint: {url}")
                    return {"error": str(e)}
                time.sleep(3)

        return {"error": "Max retries exceeded - pipeline aborted"}

    @staticmethod
    def _generate_terminal_alias(name: str) -> str:
        """Generates a standardized, shortened alphanumeric alias for facility/terminal names."""
        name = str(name).strip()
        if not name or len(name) <= 8:
            return name

        words = name.split()
        if len(words) == 1:
            return name[:8].upper()

        alias = ""
        for word in words:
            clean_word = "".join(char for char in word if char.isalnum())
            if clean_word:
                if clean_word.isdigit():
                    alias += clean_word
                else:
                    alias += clean_word[0].upper()
        return alias

    def _process_standard_events(self, standardized_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes core business logic on a unified event pipeline:
        - Vessel forward-filling across transit legs.
        - Heuristic ETA (Estimated Time of Arrival) calculation based on milestone prioritization.
        - Chronological history compilation.
        """
        if not standardized_events:
            return {"status": "Ignored (Empty telemetry or No Physical Milestones)"}

        # 1. Sort chronologically ascending to forward-fill maritime vessel data
        standardized_events.sort(key=lambda x: x["sort_date"])
        last_known_vessel = "TBN"  # To Be Nominated

        for event in standardized_events:
            if event.get("mode") == "VESSEL":
                current_vessel = event.get("vessel")
                if current_vessel and current_vessel not in ["TBN", "Unknown", None, ""]:
                    last_known_vessel = current_vessel
                elif (not current_vessel or current_vessel == "TBN") and last_known_vessel != "TBN":
                    event["vessel"] = last_known_vessel

            if not event.get("vessel"):
                event["vessel"] = "TBN"

        # 2. Reverse sort (newest to oldest) for latest status extraction
        standardized_events.sort(key=lambda x: x["sort_date"], reverse=True)

        actual_events = [e for e in standardized_events if e.get("ev_type") == "ACT"]

        # Calculate chronological baseline from the last actual occurrence
        last_act_date = actual_events[0]["sort_date"][:10] if actual_events else "1970-01-01"

        # Filter strictly future plans/estimates (PLN/EST) beyond the last actual event
        future_events = [
            e for e in standardized_events
            if e.get("ev_type") in ["EST", "PLN"] and e.get("sort_date", "")[:10] > last_act_date
        ]

        eta_event = None

        # Tier A Strategy: Strictly look for terminal arrival/discharge milestones
        for event in future_events:
            status_upper = str(event.get("status", "")).upper()
            if any(target in status_upper for target in ["DLVR", "ARRI", "DISC"]):
                eta_event = event
                break

        # Tier B Strategy: If no definitive arrival, fallback to any non-departure/gate event
        if not eta_event:
            for event in future_events:
                status_upper = str(event.get("status", "")).upper()
                if not any(
                    bad_status in status_upper
                    for bad_status in ["MTY", "GTOT", "DEPA", "LOAD", "GTIN", "STRY", "STUF"]
                ):
                    eta_event = event
                    break

        # Tier C Strategy: Absolute fallback to the next immediate planned milestone
        if not eta_event and future_events:
            eta_event = future_events[0]

        eta_port = "To Be Advised"
        eta_details = "Pending Carrier Schedule"

        if eta_event:
            eta_port = eta_event.get("date", "N/A")
            eta_details = f"{eta_event.get('mode', '')} - {eta_event.get('ev_type', '')} - {eta_event.get('status', '')} - {eta_event.get('loc', '')}"

        # Determine the most relevant target event for current status representation
        target_event = (
            actual_events[0] if actual_events
            else (future_events[-1] if future_events else standardized_events[0])
        )

        # Extrapolate Global Best Vessel
        global_best_vessel = "N/A"
        if target_event.get("vessel") and target_event.get("vessel") not in ["TBN", "Unknown", None, ""]:
            global_best_vessel = target_event["vessel"]
        else:
            for event in standardized_events:
                if event.get("vessel") and event.get("vessel") not in ["TBN", "Unknown", None, ""]:
                    global_best_vessel = event["vessel"]
                    break

        # Compile human-readable audit trail
        history_lines = []
        for event in standardized_events:
            loc_str = event.get("loc", "")
            raw_term = event.get("term", "")

            short_term = self._generate_terminal_alias(raw_term) if raw_term else ""
            if short_term:
                loc_str += f" [{short_term}]"

            line = f"[{event.get('date', '')}] - {event.get('ev_type', '')} - {event.get('status', '')} - {loc_str} ({event.get('mode', '')})"
            history_lines.append(line)

        history_str = "\n".join(history_lines)

        target_raw_term = target_event.get("term", "")
        target_short_term = self._generate_terminal_alias(target_raw_term) if target_raw_term else ""

        return {
            "event_type": target_event.get("ev_type", "N/A"),
            "status": target_event.get("status", "N/A"),
            "location": target_event.get("loc", "N/A"),
            "terminal": target_short_term,
            "date": target_event.get("date", "N/A"),
            "transport_mode": target_event.get("mode", "N/A"),
            "vessel": global_best_vessel,
            "eta_port": eta_port,
            "eta_details": eta_details,
            "history": history_str,
        }
