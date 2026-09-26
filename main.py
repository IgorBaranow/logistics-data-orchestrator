import concurrent.futures
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple

from integrations.provider_alpha import ProviderAlphaIntegration
from integrations.provider_beta import ProviderBetaIntegration
from integrations.provider_gamma import ProviderGammaIntegration
from integrations.provider_delta import ProviderDeltaIntegration
from integrations.provider_epsilon import ProviderEpsilonIntegration
from integrations.provider_zeta import ProviderZetaIntegration
from integrations.provider_omega import ProviderOmegaIntegration
from config import PIPELINES
from utils.constants import CORE_INPUT_COLS, CORE_TRACKING_COLS
from utils.data_cleaner import load_and_clean_input
from utils.excel_writer import write_excel_dashboard
from utils.logger import get_system_logger
from utils.remote_sync import extract_state_memory, commit_to_remote_volume

logger = get_system_logger("Orchestrator")


def get_target_provider(svc_name: str, providers_dict: dict):
    name = svc_name.upper()
    if "OMEGA" in name:
        return providers_dict.get("omega")
    if "ZETA" in name:
        return providers_dict.get("zeta")
    if "DELTA" in name:
        return providers_dict.get("delta")
    if "GAMMA" in name:
        return providers_dict.get("gamma")
    if "ALPHA" in name:
        return providers_dict.get("alpha")
    if "EPSILON" in name:
        return providers_dict.get("epsilon")
    if "BETA" in name:
        return providers_dict.get("beta")
    return None


def fetch_telemetry_data(
    provider_instance, entity_id: str, tx_ref: str = ""
) -> Tuple[str, dict]:
    time.sleep(random.uniform(0.5, 1.5))
    try:
        if provider_instance.carrier_code == "PROVIDER_EPSILON":
            raw_data = provider_instance.track_equipment(entity_id, tx_ref)
        else:
            raw_data = provider_instance.track_equipment(entity_id)
        return entity_id, provider_instance.normalize_response(raw_data)
    except Exception as e:
        return entity_id, {"error": str(e)}


def main():
    logger.info("Initializing Integration Modules...")
    providers_dict = {
        "omega": ProviderOmegaIntegration(),
        "zeta": ProviderZetaIntegration(),
        "delta": ProviderDeltaIntegration(),
        "gamma": ProviderGammaIntegration(),
        "alpha": ProviderAlphaIntegration(),
        "epsilon": ProviderEpsilonIntegration(),
        "beta": ProviderBetaIntegration(),
    }

    for p in providers_dict.values():
        try:
            p._refresh_token_if_needed()
        except Exception:
            pass

    logger.info("=" * 50)
    logger.info("🚦 SYSTEM BOOTSTRAP (PHASE 1-3)")
    logger.info("=" * 50)

    logger.info("\n" + "=" * 50)
    logger.info("📦 PHASE 1: WORKLOAD AGGREGATION")
    logger.info("=" * 50)

    unique_tasks = {}
    valid_pipelines = []
    pipeline_dataframes = {}

    for pipeline in PIPELINES:
        p_name = pipeline.get("pipeline_name", "UNKNOWN_ROUTING")
        input_path = str(Path(pipeline.get("input_excel", "")).resolve())

        if not input_path or not os.path.exists(input_path):
            logger.warning(f"BYPASS '{p_name}': Input source missing -> {input_path}")
            continue

        try:
            df = load_and_clean_input(input_path)
            valid_pipelines.append(pipeline)
            pipeline_dataframes[p_name] = df

            new_entities = 0
            for _, row in df.iterrows():
                entity = str(row["Entity_ID"]).strip()
                svc_prov = str(row["Service_Provider"]).strip()
                tx_ref = str(row.get("Transaction_Ref", "")).strip() if "Transaction_Ref" in df.columns else ""

                if tx_ref.lower() == "nan":
                    tx_ref = ""

                if entity and entity not in unique_tasks:
                    provider = get_target_provider(svc_prov, providers_dict)
                    if provider:
                        unique_tasks[entity] = (provider, tx_ref)
                        new_entities += 1

            logger.info(
                f"[{p_name}] Processed {len(df)} nodes. Identified {new_entities} active entities."
            )

        except Exception as e:
            logger.error(f"Aggregation fault on '{p_name}': {e}")

    total_unique = len(unique_tasks)
    if total_unique == 0:
        logger.error("Zero-state workload. Terminating sequence.")
        return

    logger.info("\n" + "=" * 50)
    logger.info(f"🌐 PHASE 2: ASYNC TELEMETRY POLLING (Nodes: {total_unique})")
    logger.info("=" * 50)

    state_cache = {}
    tasks_list = [(ent, data[0], data[1]) for ent, data in unique_tasks.items()]
    random.shuffle(tasks_list)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(fetch_telemetry_data, t[1], t[0], t[2]): t[0]
            for t in tasks_list
        }

        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            ent_ref = futures[future]
            try:
                _, res = future.result()
                state_cache[ent_ref] = res
            except Exception as e:
                state_cache[ent_ref] = {"error": f"Core Exception: {str(e)}"}

            if "error" in state_cache[ent_ref]:
                logger.error(f"[{count}/{total_unique}] ❌ {ent_ref}")
            else:
                logger.info(f"[{count}/{total_unique}] ✅ {ent_ref}")

    logger.info("\n" + "=" * 50)
    logger.info("🏭 PHASE 3: COMPILATION & REMOTE SYNC")
    logger.info("=" * 50)

    processed_count = 0
    failed_count = 0

    for pipeline in valid_pipelines:
        p_name = pipeline.get("pipeline_name", "UNKNOWN_ROUTING")
        local_out_dir = str(Path(pipeline["local_out_dir"]).resolve())

        try:
            df = pipeline_dataframes[p_name]

            hist_data, header_styles, header_widths, manual_cols = (
                extract_state_memory(
                    pipeline.get("sp_history_dir", ""),
                    pipeline.get("default_manual_cols", []),
                )
            )

            for col in CORE_TRACKING_COLS + manual_cols:
                if col not in df.columns:
                    df[col] = None

            indices_to_drop = []
            for index, row in df.iterrows():
                ent = str(row["Entity_ID"]).strip()

                if ent in hist_data:
                    for manual_col in manual_cols:
                        if manual_col in hist_data[ent]:
                            df.at[index, manual_col] = hist_data[ent][manual_col]

                if ent in state_cache:
                    res = state_cache[ent]
                    if "Ignored" in str(res.get("status", "")):
                        indices_to_drop.append(index)
                        continue

                    if "error" in res:
                        df.at[index, "Current_Status_Code"] = res["error"]
                    else:
                        df.at[index, "Milestone_Date"] = res.get("date")
                        df.at[index, "Geo_Location"] = res.get("location")
                        df.at[index, "Facility_Terminal"] = res.get("terminal")
                        df.at[index, "Milestone_Classifier"] = res.get("event_type")
                        df.at[index, "Current_Status_Code"] = res.get("status")
                        df.at[index, "Transport_Mode"] = res.get("transport_mode")
                        df.at[index, "Conveyance_Name"] = res.get("vessel")

                        eta_val = str(res.get("eta_port", "")).strip()

                        invalid_markers = [
                            "N/A", "Unknown", "None", "", "To Be Advised",
                            "TBA", "-", "Pending", "Pending Carrier Schedule", "nan",
                        ]

                        if not eta_val or eta_val.lower() in [m.lower() for m in invalid_markers]:
                            df.at[index, "Calculated_ETA"] = ""
                            df.at[index, "Next_Planned_Event"] = "Terminal evaluation (No EST/PLN)"
                        else:
                            df.at[index, "Calculated_ETA"] = eta_val
                            df.at[index, "Next_Planned_Event"] = str(res.get("eta_details", "")).strip()

                        df.at[index, "System_Audit_Notes"] = ""

            if indices_to_drop:
                df = df.drop(index=indices_to_drop)

            os.makedirs(local_out_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
            final_excel_path = os.path.join(
                local_out_dir,
                f"{pipeline.get('file_prefix', 'STATE_DUMP')}_{timestamp}.xlsx",
            )

            final_cols = CORE_INPUT_COLS + CORE_TRACKING_COLS + manual_cols
            write_excel_dashboard(
                df,
                final_excel_path,
                final_cols,
                header_styles,
                header_widths,
                state_cache,
            )

            logger.info(f" Committing {p_name} to Remote Volume...")
            commit_to_remote_volume(
                final_excel_path,
                pipeline.get("sp_history_dir", ""),
                pipeline.get("sp_archive_dir", ""),
                pipeline.get("file_prefix", ""),
                timestamp,
            )

            processed_count += 1
            logger.info(f"[✅] SUCCESS: {p_name} committed.")

        except Exception as e:
            logger.error(f"[❌] FAILED for {p_name}: {e}")
            failed_count += 1

    logger.info("\n" + "=" * 50)
    logger.info("🏁 EXECUTION COMPLETE")
    logger.info("=" * 50)
    logger.info(f"Total Unique Nodes Polled: {total_unique}")
    logger.info(f"Successful Pipelines: {processed_count}")
    if failed_count > 0:
        logger.error(f"Failed Pipelines: {failed_count}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
