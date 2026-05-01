from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pandas as pd
try:
    import yaml
except Exception:
    yaml = None

from modules.models import CW1Inputs


DATE_COLUMN_CANDIDATES = [
    "snapshot_date",
    "as_of_date",
    "formation_date",
    "rebalance_date",
    "month_end",
    "date",
]


def _load_table(csv_path: Path, parquet_path: Path) -> pd.DataFrame:
    if parquet_path.exists():
        try:
            return pd.read_parquet(parquet_path)
        except Exception:
            pass
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


def _load_table_from_bytes(content: bytes, suffix: str) -> pd.DataFrame:
    if suffix == ".parquet":
        return pd.read_parquet(io.BytesIO(content))
    return pd.read_csv(io.BytesIO(content))


def _load_yaml_config(config_path: Path) -> dict:
    if yaml is None:
        return {}
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_minio_settings(config: dict, analytics_dir: Path) -> dict:
    settings = dict(config.get("minio", {}))
    cw1_conf = _load_yaml_config(analytics_dir.parent / "config" / "conf.yaml")
    cw1_minio = cw1_conf.get("minio", {}) if isinstance(cw1_conf, dict) else {}

    env_or_config = {
        "endpoint": os.getenv("MINIO_ENDPOINT"),
        "access_key": os.getenv("MINIO_ACCESS_KEY"),
        "secret_key": os.getenv("MINIO_SECRET_KEY"),
        "bucket": os.getenv("MINIO_BUCKET"),
        "use_ssl": os.getenv("MINIO_SECURE"),
    }
    for key, value in env_or_config.items():
        if value is not None and value != "":
            settings[key] = value

    for key in ["endpoint", "access_key", "secret_key", "bucket", "use_ssl"]:
        if key not in settings and key in cw1_minio:
            settings[key] = cw1_minio[key]

    if "use_ssl" in settings and isinstance(settings["use_ssl"], str):
        settings["use_ssl"] = settings["use_ssl"].lower() == "true"
    settings.setdefault("bucket", "csreport")
    return settings


def _init_minio_client(config: dict, analytics_dir: Path):
    settings = _resolve_minio_settings(config, analytics_dir)
    endpoint = settings.get("endpoint")
    access_key = settings.get("access_key")
    secret_key = settings.get("secret_key")
    if not endpoint or not access_key or not secret_key:
        return None, settings

    try:
        from minio import Minio
    except Exception:
        return None, settings

    try:
        client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=bool(settings.get("use_ssl", False)),
        )
        return client, settings
    except Exception:
        return None, settings


def _get_object_bytes(client, bucket: str, object_name: str) -> bytes:
    response = client.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _load_minio_table(client, bucket: str, candidates: list[str]) -> pd.DataFrame:
    for object_name in candidates:
        try:
            content = _get_object_bytes(client, bucket, object_name)
            suffix = Path(object_name).suffix.lower()
            return _load_table_from_bytes(content, suffix)
        except Exception:
            continue
    return pd.DataFrame()


def _load_price_history(analytics_dir: Path) -> pd.DataFrame:
    raw_prices_dir = analytics_dir / "raw" / "prices"
    records = []

    if not raw_prices_dir.exists():
        return pd.DataFrame()

    for csv_file in sorted(raw_prices_dir.glob("*.csv")):
        symbol = csv_file.stem
        df = pd.read_csv(csv_file)
        if "Date" in df.columns:
            df = df.rename(columns={"Date": "date"})
        if "Close" in df.columns:
            df = df.rename(columns={"Close": "close"})
        df["symbol"] = symbol
        records.append(df)

    if not records:
        return pd.DataFrame()

    prices = pd.concat(records, ignore_index=True)
    if "date" in prices.columns:
        prices["date"] = pd.to_datetime(prices["date"], utc=True).dt.tz_localize(None)
    return prices


def _load_price_history_from_minio(client, bucket: str) -> pd.DataFrame:
    records = []
    try:
        objects = client.list_objects(bucket, prefix="raw/prices/", recursive=True)
    except Exception:
        return pd.DataFrame()

    for obj in objects:
        object_name = getattr(obj, "object_name", "")
        suffix = Path(object_name).suffix.lower()
        if suffix not in {".csv", ".parquet"}:
            continue
        try:
            content = _get_object_bytes(client, bucket, object_name)
            df = _load_table_from_bytes(content, suffix)
        except Exception:
            continue

        symbol = Path(object_name).stem
        if "Date" in df.columns:
            df = df.rename(columns={"Date": "date"})
        if "Close" in df.columns:
            df = df.rename(columns={"Close": "close"})
        if "Adj Close" in df.columns and "close" not in df.columns:
            df = df.rename(columns={"Adj Close": "close"})
        df["symbol"] = symbol
        records.append(df)

    if not records:
        return pd.DataFrame()

    prices = pd.concat(records, ignore_index=True)
    if "date" in prices.columns:
        prices["date"] = pd.to_datetime(prices["date"], errors="coerce", utc=True).dt.tz_localize(None)
    return prices.dropna(subset=["date"]).reset_index(drop=True)


def _standardise_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    renamed = df.rename(
        columns={
            "normalized_sector": "sector",
            "score": "composite_score",
        }
    ).copy()

    if "sector" not in renamed.columns and "gics_sector" in renamed.columns:
        renamed["sector"] = renamed["gics_sector"]

    return renamed


def _find_date_column(df: pd.DataFrame) -> str | None:
    for column in DATE_COLUMN_CANDIDATES:
        if column in df.columns:
            return column
    return None


def _extract_date_from_name(name: str) -> pd.Timestamp | None:
    patterns = [
        r"(20\d{2}[-_]\d{2}[-_]\d{2})",
        r"(20\d{6})",
        r"(20\d{2}[-_]\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, name)
        if not match:
            continue
        token = match.group(1).replace("_", "-")
        parsed = pd.to_datetime(token, errors="coerce")
        if pd.notna(parsed):
            return parsed.normalize()
    return None


def _normalise_snapshot_history(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    history = _standardise_columns(df)
    date_column = _find_date_column(history)
    if date_column is None:
        return pd.DataFrame()

    if date_column != "snapshot_date":
        history = history.rename(columns={date_column: "snapshot_date"})
    history["snapshot_date"] = pd.to_datetime(history["snapshot_date"], errors="coerce", utc=True).dt.tz_localize(None)
    history = history.dropna(subset=["snapshot_date"]).sort_values(["snapshot_date"])
    return history.reset_index(drop=True)


def _load_local_snapshot_history(analytics_dir: Path, dataset_name: str, relative_dirs: list[str]) -> pd.DataFrame:
    direct_files = []
    for relative_dir in relative_dirs:
        base_dir = analytics_dir / relative_dir
        direct_files.extend(
            [
                base_dir / f"{dataset_name}_history.parquet",
                base_dir / f"{dataset_name}_history.csv",
                base_dir / f"{dataset_name}_panel.parquet",
                base_dir / f"{dataset_name}_panel.csv",
                base_dir / f"{dataset_name}.parquet",
                base_dir / f"{dataset_name}.csv",
            ]
        )

    for candidate in direct_files:
        if not candidate.exists():
            continue
        history = _normalise_snapshot_history(_load_table(candidate.with_suffix(".csv"), candidate.with_suffix(".parquet")))
        if not history.empty:
            return history

    combined_records = []
    for relative_dir in relative_dirs:
        base_dir = analytics_dir / relative_dir
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.glob(f"{dataset_name}*.csv")) + sorted(base_dir.glob(f"{dataset_name}*.parquet")):
            if "latest" in path.name.lower():
                continue
            loaded = _load_table(path.with_suffix(".csv"), path.with_suffix(".parquet"))
            if loaded.empty:
                continue
            if _find_date_column(loaded) is None:
                extracted = _extract_date_from_name(path.name)
                if extracted is None:
                    continue
                loaded = loaded.copy()
                loaded["snapshot_date"] = extracted
            combined_records.append(loaded)

    if not combined_records:
        return pd.DataFrame()

    return _normalise_snapshot_history(pd.concat(combined_records, ignore_index=True))


def _load_minio_snapshot_history(client, bucket: str, dataset_name: str, prefixes: list[str]) -> pd.DataFrame:
    direct_candidates = []
    for prefix in prefixes:
        direct_candidates.extend(
            [
                f"{prefix}/{dataset_name}_history.parquet",
                f"{prefix}/{dataset_name}_history.csv",
                f"{prefix}/{dataset_name}_panel.parquet",
                f"{prefix}/{dataset_name}_panel.csv",
                f"{prefix}/{dataset_name}.parquet",
                f"{prefix}/{dataset_name}.csv",
            ]
        )

    for object_name in direct_candidates:
        try:
            content = _get_object_bytes(client, bucket, object_name)
        except Exception:
            continue
        history = _normalise_snapshot_history(_load_table_from_bytes(content, Path(object_name).suffix.lower()))
        if not history.empty:
            return history

    combined_records = []
    for prefix in prefixes:
        try:
            objects = client.list_objects(bucket, prefix=f"{prefix}/", recursive=True)
        except Exception:
            continue
        for obj in objects:
            object_name = getattr(obj, "object_name", "")
            file_name = Path(object_name).name.lower()
            if dataset_name not in file_name or "latest" in file_name:
                continue
            if Path(object_name).suffix.lower() not in {".csv", ".parquet"}:
                continue
            try:
                content = _get_object_bytes(client, bucket, object_name)
                loaded = _load_table_from_bytes(content, Path(object_name).suffix.lower())
            except Exception:
                continue
            if _find_date_column(loaded) is None:
                extracted = _extract_date_from_name(object_name)
                if extracted is None:
                    continue
                loaded = loaded.copy()
                loaded["snapshot_date"] = extracted
            combined_records.append(loaded)

    if not combined_records:
        return pd.DataFrame()

    return _normalise_snapshot_history(pd.concat(combined_records, ignore_index=True))


def load_cw1_inputs(config: dict) -> CW1Inputs:
    """
    Load CW1 as a frozen upstream data product.

    CW2 intentionally consumes only the latest published CW1 outputs.
    It does not modify CW1 and it does not attempt to recreate a historical
    archive of monthly factor snapshots.
    """
    analytics_dir = Path(config["paths"]["cw1_analytics_dir"])
    minio_client, minio_settings = _init_minio_client(config, analytics_dir)
    bucket = minio_settings.get("bucket", "csreport")

    factors = _load_table(
        analytics_dir / "processed" / "step1" / "factors_latest.csv",
        analytics_dir / "processed" / "step1" / "factors_latest.parquet",
    )
    if factors.empty:
        factors = _load_table(
            analytics_dir / "portfolio" / "factors_latest.csv",
            analytics_dir / "portfolio" / "factors_latest.parquet",
        )
    if factors.empty and minio_client is not None:
        factors = _load_minio_table(
            minio_client,
            bucket,
            [
                "processed/step1/factors_latest.parquet",
                "processed/step1/factors_latest.csv",
                "portfolio/factors_latest.parquet",
                "portfolio/factors_latest.csv",
            ],
        )
    factors = _standardise_columns(factors)
    historical_factors = _load_local_snapshot_history(
        analytics_dir,
        "factors",
        ["processed/step1", "portfolio", "factors", "history/factors"],
    )
    if historical_factors.empty and minio_client is not None:
        historical_factors = _load_minio_snapshot_history(
            minio_client,
            bucket,
            "factors",
            ["processed/step1", "portfolio", "factors", "history/factors", "serving/factors"],
        )

    selections = _load_table(
        analytics_dir / "processed" / "step2" / "selections_latest.csv",
        analytics_dir / "processed" / "step2" / "selections_latest.parquet",
    )
    if selections.empty:
        selections = _load_table(
            analytics_dir / "selections" / "selections_latest.csv",
            analytics_dir / "selections" / "selections_latest.parquet",
        )
    if selections.empty and minio_client is not None:
        selections = _load_minio_table(
            minio_client,
            bucket,
            [
                "processed/step2/selections_latest.parquet",
                "processed/step2/selections_latest.csv",
                "selections/selections_latest.parquet",
                "selections/selections_latest.csv",
                "serving/selections/selections_latest.csv",
            ],
        )
    selections = _standardise_columns(selections)
    historical_selections = _load_local_snapshot_history(
        analytics_dir,
        "selections",
        ["processed/step2", "selections", "history/selections"],
    )
    if historical_selections.empty and minio_client is not None:
        historical_selections = _load_minio_snapshot_history(
            minio_client,
            bucket,
            "selections",
            ["processed/step2", "selections", "history/selections", "serving/selections"],
        )

    signals = _load_table(
        analytics_dir / "processed" / "step3" / "signals_latest.csv",
        analytics_dir / "processed" / "step3" / "signals_latest.parquet",
    )
    if signals.empty:
        signals = _load_table(
            analytics_dir / "signals" / "signals_latest.csv",
            analytics_dir / "signals" / "signals_latest.parquet",
        )
    if signals.empty and minio_client is not None:
        signals = _load_minio_table(
            minio_client,
            bucket,
            [
                "processed/step3/signals_latest.parquet",
                "processed/step3/signals_latest.csv",
                "signals/signals_latest.parquet",
                "signals/signals_latest.csv",
                "serving/signals/signals_latest.csv",
            ],
        )
    signals = _standardise_columns(signals)
    historical_signals = _load_local_snapshot_history(
        analytics_dir,
        "signals",
        ["processed/step3", "signals", "history/signals"],
    )
    if historical_signals.empty and minio_client is not None:
        historical_signals = _load_minio_snapshot_history(
            minio_client,
            bucket,
            "signals",
            ["processed/step3", "signals", "history/signals", "serving/signals"],
        )

    price_history = _load_price_history(analytics_dir)
    if price_history.empty and minio_client is not None:
        price_history = _load_price_history_from_minio(minio_client, bucket)
    universe_snapshot = factors.copy()

    return CW1Inputs(
        universe_snapshot=universe_snapshot,
        factors=factors,
        selections=selections,
        signals=signals,
        price_history=price_history,
        historical_factors=historical_factors,
        historical_selections=historical_selections,
        historical_signals=historical_signals,
    )
