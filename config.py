import os
from pathlib import Path
from typing import List, Optional, TypedDict

from dotenv import load_dotenv

load_dotenv()

MAX_RETRIES = 3
DELAY_BETWEEN_REQUESTS = 1.0

BASE_DIR = Path(__file__).resolve().parent
print(f"My current BASE_DIR is: {BASE_DIR}")

LOCAL_OUT_BASE = BASE_DIR.parent / "Enterprise_Telemetry_Dashboards"

RAW_JSON_DIR = BASE_DIR / "data" / "raw_jsons"
CERTS_DIR = BASE_DIR / "certs"

for directory in [RAW_JSON_DIR, CERTS_DIR, LOCAL_OUT_BASE]:
    directory.mkdir(parents=True, exist_ok=True)

REMOTE_VOLUME_BASE = (
    Path.home()
    / "Enterprise_Tenant_Drive"
    / "Global_Control_Tower_Documents"
    / "Core_Operations"
    / "Inland_Transit"
    / "_AUTOMATED_INGESTION"
)
REGION_ALPHA_BASE = REMOTE_VOLUME_BASE / "Region_Alpha" / "01.Active_Assets"

print(f"REMOTE VOLUME BASE_DIR is: {REMOTE_VOLUME_BASE}")

class PipelineConfig(TypedDict):
    pipeline_name: str
    input_excel: str
    local_out_dir: str
    file_prefix: str
    default_manual_cols: List[str]
    sp_history_dir: str
    sp_archive_dir: str


def build_pipeline_config(
    folder_name: str,
    file_name: str,
    prefix: str,
    manual_cols: Optional[List[str]] = None,
) -> PipelineConfig:
    manual_cols = manual_cols or []

    input_path = REGION_ALPHA_BASE / folder_name / "input" / file_name
    sp_history = REGION_ALPHA_BASE / folder_name / "TELEMETRY"
    sp_archive = sp_history / "Archive"

    local_target_dir = LOCAL_OUT_BASE / folder_name

    return {
        "pipeline_name": f"REGION_ALPHA_ACTIVE_{folder_name.replace(' ', '_').upper()}",
        "input_excel": str(input_path),
        "local_out_dir": str(local_target_dir),
        "file_prefix": prefix,
        "default_manual_cols": manual_cols,
        "sp_history_dir": str(sp_history),
        "sp_archive_dir": str(sp_archive),
    }


PIPELINES: List[PipelineConfig] = [
    build_pipeline_config(
        folder_name="Route_Alpha_01",
        file_name="REGION_ALPHA_ACTIVE_ASSETS_001.xlsx",
        prefix="ROUTE_A_01_TELEMETRY",
        manual_cols=[
            "Control_Desk_Notes_Outbound",
            "Control_Desk_Notes_Inland",
            "Compliance_Approval_Date",
            "Border_Clearance_Status",
            "Regulatory_Filing_Number",
            "Regulatory_Filing_Date",
        ],
    ),
    build_pipeline_config(
        folder_name="Category_Maritime",
        file_name="REGION_ALPHA_ACTIVE_ASSETS.xlsx",
        prefix="CAT_MARITIME_TELEMETRY",
    ),
    build_pipeline_config(
        folder_name="Special_Ops", file_name="REGION_ALPHA_ACTIVE_ASSETS.xlsx", prefix="SPEC_OPS_TELEMETRY"
    ),
    # build_pipeline_config(
    #     folder_name="Retail_Zone_A",
    #     file_name="ZONE_A_ACTIVE_ASSETS.xlsx",
    #     prefix="RETAIL_ZA_TELEMETRY",
    # ),
    # build_pipeline_config(
    #     folder_name="Retail_Zone_B_C",
    #     file_name="ZONE_BC_ACTIVE_ASSETS.xlsx",
    #     prefix="RETAIL_ZBC_TELEMETRY",
    # ),
    # build_pipeline_config(
    #     folder_name="Retail_Zone_D",
    #     file_name="ZONE_D_ACTIVE_ASSETS.xlsx",
    #     prefix="RETAIL_ZD_TELEMETRY",
    # ),
]


def _get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


PROVIDER_OMEGA_CLIENT_ID = _get_env("PROVIDER_OMEGA_CLIENT_ID")
PROVIDER_OMEGA_TENANT_ID = _get_env("PROVIDER_OMEGA_TENANT_ID")
PROVIDER_OMEGA_SCOPE = _get_env("PROVIDER_OMEGA_SCOPE")
PROVIDER_OMEGA_CERT_PASSWORD = _get_env("PROVIDER_OMEGA_CERT_PASSWORD")
_omega_filename = _get_env("PROVIDER_OMEGA_CERT_FILENAME")
PROVIDER_OMEGA_CERT_PATH = CERTS_DIR / _omega_filename if _omega_filename else None

PROVIDER_ZETA_CLIENT_ID = _get_env("PROVIDER_ZETA_CLIENT_ID")
PROVIDER_ZETA_CLIENT_SECRET = _get_env("PROVIDER_ZETA_CLIENT_SECRET")

PROVIDER_DELTA_CLIENT_ID = _get_env("PROVIDER_DELTA_CLIENT_ID")
PROVIDER_DELTA_CLIENT_SECRET = _get_env("PROVIDER_DELTA_CLIENT_SECRET")

PROVIDER_GAMMA_TOKEN_URL = _get_env("PROVIDER_GAMMA_TOKEN_URL")
PROVIDER_GAMMA_CLIENT_ID = _get_env("PROVIDER_GAMMA_CLIENT_ID")
PROVIDER_GAMMA_CLIENT_SECRET = _get_env("PROVIDER_GAMMA_CLIENT_SECRET")
PROVIDER_GAMMA_API_URL_BASE = _get_env("PROVIDER_GAMMA_API_URL_BASE")

PROVIDER_ALPHA_API_KEY = _get_env("PROVIDER_ALPHA_API_KEY")

PROVIDER_EPSILON_API_KEY = _get_env("PROVIDER_EPSILON_API_KEY")

PROVIDER_BETA_CLIENT_ID = _get_env("PROVIDER_BETA_CLIENT_ID")
PROVIDER_BETA_CLIENT_SECRET = _get_env("PROVIDER_BETA_CLIENT_SECRET")
