import re
import pandas as pd


def clean_entity_id(raw_val: str) -> str:
    val = str(raw_val).upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", val)
    match = re.search(r"([A-Z]{4})(\d{7})", cleaned)
    return match.group(1) + match.group(2) if match else cleaned


def load_and_clean_input(input_path: str) -> pd.DataFrame:
    df = pd.read_excel(input_path)

    col_entity = "ENTTIY_ID" if "ENTTIY_ID" in df.columns else "ENTITY_ID"
    col_provider = "SVC_PROV_NAME"

    if col_entity not in df.columns or col_provider not in df.columns:
        raise ValueError("Missing required columns in input excel.")

    df = df.dropna(subset=[col_entity, col_provider])
    df = df[df[col_entity].astype(str).str.strip() != ""]
    df = df[df[col_entity].astype(str).str.upper() != "NAN"]

    df[col_entity] = df[col_entity].apply(clean_entity_id)

    provider_mapping = {
        "PROVIDER_ALPHA S.A.": "ALPHA",
        "PROVIDER_DELTA AG": "DELTA",
        "PROVIDER_OMEGA S.A.": "OMEGA",
        "PROVIDER_BETA CO., LTD": "BETA",
        "PROVIDER_ZETA A/S": "ZETA",
        "PROVIDER_GAMMA LINE": "GAMMA",
        "PROVIDER_EPSILON CO., LTD.": "EPSILON",
        "PROVIDER_THETA LTD.": "THETA",
    }
    df[col_provider] = df[col_provider].apply(
        lambda x: provider_mapping.get(str(x).strip(), str(x).strip())
    )

    rename_map = {
        col_entity: "Entity_ID",
        "SRC_NODE_CODE": "Source_Node",
        "TX_REF_NUM": "Transaction_Ref",
        "PREV_HOST_ID": "Primary_Host",
        "MAIN_ROUTING_ID": "Routing_Group_ID",
        "TGT_NODE_CODE": "Target_Node",
        "SUBSCRIBER_LST": "Subscriber_UID",
        col_provider: "Service_Provider",
    }

    existing_cols = [c for c in rename_map.keys() if c in df.columns]
    df = df[existing_cols].copy()
    df.rename(columns=rename_map, inplace=True)

    return df
