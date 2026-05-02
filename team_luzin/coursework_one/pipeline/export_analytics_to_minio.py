#!/usr/bin/env python3
"""
Step 4: Data Lake Publishing Layer (Local + MinIO)

Reads outputs from upstream steps (Step 1, 2, 3) and publishes them into a
structured data lake with three layers:

- raw/: Source-level data (price cache)
- processed/: Step outputs with timestamped versions + latest aliases
- serving/: Latest stable files for downstream consumption

Publishes to BOTH:
- Local filesystem (analytics/)
- MinIO remote storage (same structure as local)

MinIO Config (from environment variables):
- MINIO_ENDPOINT: e.g., "localhost:9000"
- MINIO_ACCESS_KEY: MinIO access key
- MINIO_SECRET_KEY: MinIO secret key
- MINIO_BUCKET: Bucket name (auto-created if missing)
- MINIO_SECURE: "true" or "false" for SSL

Export Status:
- LOCAL_ONLY: Only local file export succeeded
- MINIO_SUCCESS: Both local and MinIO succeeded
- MINIO_FAILED: Local succeeded, MinIO failed
- DISABLED: MinIO not configured (intentional)
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import yaml

# Import structured result types
sys.path.insert(0, str(Path(__file__).parent.parent))
from modules.minio_diagnostics import MinIODiagnostics
from modules.pipeline_results import ExportStatus

try:
    from minio import Minio

    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _load_conf_yaml() -> Dict[str, Any]:
    """Load config/conf.yaml and return its dictionary payload."""
    config_path = Path(__file__).parent.parent / "config" / "conf.yaml"
    if not config_path.exists():
        return {}

    try:
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.warning(f"⚠️  Failed to read conf.yaml for MinIO settings: {e}")

    return {}


def _apply_minio_env_fallback_from_config() -> None:
    """
    Populate MINIO_* environment variables from config/conf.yaml when missing.

    Environment variables still take precedence over config values.
    """
    conf = _load_conf_yaml()
    minio_conf = conf.get("minio", {}) if isinstance(conf, dict) else {}
    if not isinstance(minio_conf, dict):
        return

    env_map = {
        "MINIO_ENDPOINT": minio_conf.get("endpoint"),
        "MINIO_ACCESS_KEY": minio_conf.get("access_key"),
        "MINIO_SECRET_KEY": minio_conf.get("secret_key"),
        "MINIO_BUCKET": minio_conf.get("bucket"),
    }

    for env_key, conf_val in env_map.items():
        if not os.getenv(env_key) and conf_val:
            os.environ[env_key] = str(conf_val)

    if not os.getenv("MINIO_SECURE") and minio_conf.get("use_ssl") is not None:
        os.environ["MINIO_SECURE"] = str(bool(minio_conf.get("use_ssl"))).lower()


def _ensure_dir(path: Path) -> None:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


def _load_csv_or_parquet(csv_path: Path, parquet_path: Path) -> pd.DataFrame:
    """
    Load data from CSV or parquet, preferring parquet if available.

    Args:
        csv_path: Path to CSV file
        parquet_path: Path to parquet file

    Returns:
        DataFrame if found, None otherwise
    """
    if parquet_path.exists():
        try:
            return pd.read_parquet(parquet_path)
        except Exception as e:
            logger.warning(f"Failed to read parquet {parquet_path}: {e}")

    if csv_path.exists():
        try:
            return pd.read_csv(csv_path)
        except Exception as e:
            logger.warning(f"Failed to read csv {csv_path}: {e}")

    return None


def _init_minio_client():
    """
    Initialize MinIO client from environment variables.

    Returns:
        Minio client or None if config missing/invalid
    """
    _apply_minio_env_fallback_from_config()

    if not MINIO_AVAILABLE:
        logger.warning("⚠️  minio library not installed; MinIO upload disabled")
        return None

    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    bucket = os.getenv("MINIO_BUCKET", "trading-analytics")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    if not endpoint or not access_key or not secret_key:
        logger.warning(
            "⚠️  MinIO config incomplete (MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY required)"
        )
        return None

    try:
        client = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure
        )
        # Try to ensure bucket exists
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info(f"✓ Created MinIO bucket: {bucket}")
        else:
            logger.info(f"✓ Connected to MinIO bucket: {bucket}")
        return client
    except Exception as e:
        logger.warning(f"⚠️  Failed to initialize MinIO client: {e}")
        return None


def _upload_file_to_minio(
    client: Minio, local_path: Path, object_key: str, bucket: str
) -> bool:
    """
    Upload a local file to MinIO.

    Args:
        client: Minio client
        local_path: Path to local file
        object_key: Object key in MinIO (path + filename)
        bucket: Bucket name

    Returns:
        True if successful, False otherwise
    """
    if not client or not local_path.exists():
        return False

    try:
        client.fput_object(bucket, object_key, str(local_path))
        logger.info(f"  ✓ Uploaded to MinIO: s3://{bucket}/{object_key}")
        return True
    except Exception as e:
        logger.warning(f"  ✗ Failed to upload {object_key}: {e}")
        return False


def _publish_dataset(
    name: str,
    df: pd.DataFrame,
    local_dir: Path,
    minio_client: Minio,
    bucket: str,
    run_timestamp: str,
    base_path: str = "processed",
) -> int:
    """
    Publish a dataset locally and to MinIO with versioning.

    Args:
        name: Dataset name (e.g., "factors", "portfolio", "selections", "signals")
        df: DataFrame to publish
        local_dir: Local base directory (e.g., processed/step1/)
        minio_client: MinIO client or None
        bucket: MinIO bucket name
        run_timestamp: Timestamp for versioning
        base_path: Base path in MinIO (e.g., "processed", "raw")

    Returns:
        Number of files successfully written
    """
    count = 0

    # Create timestamped directory
    timestamp_dir = local_dir / run_timestamp
    _ensure_dir(timestamp_dir)

    # Write timestamped CSV
    csv_path = timestamp_dir / f"{name}_{run_timestamp}.csv"
    df.to_csv(csv_path, index=False)
    logger.info(f"  ✓ Local: {csv_path}")
    count += 1

    # Upload to MinIO
    if minio_client:
        object_key = f"{base_path}/{csv_path.parent.parent.name}/{run_timestamp}/{name}_{run_timestamp}.csv"
        if _upload_file_to_minio(minio_client, csv_path, object_key, bucket):
            count += 1

    # Write timestamped Parquet
    parquet_path = timestamp_dir / f"{name}_{run_timestamp}.parquet"
    df.to_parquet(parquet_path, index=False)
    logger.info(f"  ✓ Local: {parquet_path}")
    count += 1

    # Upload to MinIO
    if minio_client:
        object_key = f"{base_path}/{parquet_path.parent.parent.name}/{run_timestamp}/{name}_{run_timestamp}.parquet"
        if _upload_file_to_minio(minio_client, parquet_path, object_key, bucket):
            count += 1

    # Write latest CSV
    latest_csv = local_dir / f"{name}_latest.csv"
    df.to_csv(latest_csv, index=False)
    logger.info(f"  ✓ Local: {latest_csv}")
    count += 1

    # Upload latest to MinIO
    if minio_client:
        object_key = f"{base_path}/{local_dir.name}/{name}_latest.csv"
        if _upload_file_to_minio(minio_client, latest_csv, object_key, bucket):
            count += 1

    # Write latest Parquet
    latest_parquet = local_dir / f"{name}_latest.parquet"
    df.to_parquet(latest_parquet, index=False)
    logger.info(f"  ✓ Local: {latest_parquet}")
    count += 1

    # Upload latest parquet to MinIO
    if minio_client:
        object_key = f"{base_path}/{local_dir.name}/{name}_latest.parquet"
        if _upload_file_to_minio(minio_client, latest_parquet, object_key, bucket):
            count += 1

    return count


def _publish_raw_data(minio_client: Minio, bucket: str) -> int:
    """
    Publish raw price cache data to MinIO.

    Args:
        minio_client: MinIO client or None
        bucket: MinIO bucket name

    Returns:
        Number of files successfully uploaded to MinIO
    """
    count = 0
    raw_cache_dir = Path(__file__).parent.parent / "analytics" / "raw" / "prices"

    if not raw_cache_dir.exists():
        logger.debug("No raw price cache found")
        return count

    if not minio_client:
        logger.info("Skipping raw data upload (MinIO not available)")
        return count

    logger.info("Publishing raw price cache to MinIO...")
    csv_files = list(raw_cache_dir.glob("*.csv"))
    parquet_files = list(raw_cache_dir.glob("*.parquet"))

    all_files = csv_files + parquet_files
    if not all_files:
        logger.debug("No price cache files found")
        return count

    for file_path in all_files:
        object_key = f"raw/prices/{file_path.name}"
        if _upload_file_to_minio(minio_client, file_path, object_key, bucket):
            count += 1

    logger.info(f"✓ Published {count} raw data files to MinIO")
    return count


def export_to_local_and_minio():
    """
    Step 4: Persist pipeline outputs to local lake and MinIO.

    Publishes:
    1. Raw layer: Price cache
    2. Processed layer: Timestamped outputs + latest aliases
    3. Serving layer: Latest CSV files for consumption
    """
    logger.info("Step 4/4: Data Lake Publishing (Local + MinIO)")
    logger.info("=" * 70)

    # Initialize MinIO if available
    _apply_minio_env_fallback_from_config()
    bucket = os.getenv("MINIO_BUCKET", "trading-analytics")
    minio_client = _init_minio_client()

    try:
        # Define base paths
        analytics_base = Path(__file__).parent.parent / "analytics"
        run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Layer directories
        processed_base = analytics_base / "processed"
        serving_base = analytics_base / "serving"

        write_count = 0
        warning_count = 0

        # =====================================================================
        # RAW LAYER: Price cache
        # =====================================================================
        logger.info("📦 Publishing raw layer...")
        raw_count = _publish_raw_data(minio_client, bucket)
        write_count += raw_count

        # =====================================================================
        # STEP 1: Load and persist factors (monthly)
        # =====================================================================
        factors_csv = analytics_base / "portfolio" / "factors_latest.csv"
        factors_parquet = analytics_base / "portfolio" / "factors_latest.parquet"

        if factors_csv.exists() or factors_parquet.exists():
            logger.info("📊 Publishing Step 1 factors...")
            df_factors = _load_csv_or_parquet(factors_csv, factors_parquet)

            if df_factors is not None:
                step1_dir = processed_base / "step1"
                _ensure_dir(step1_dir)
                count = _publish_dataset(
                    "factors",
                    df_factors,
                    step1_dir,
                    minio_client,
                    bucket,
                    run_timestamp,
                    "processed",
                )
                write_count += count
                logger.info(
                    f"✓ Step 1 complete: {len(df_factors)} factors, {count} files written"
                )
            else:
                logger.warning("✗ Could not load Step 1 factors")
                warning_count += 1
        else:
            logger.warning("✗ Step 1 factors not found")
            warning_count += 1

        # =====================================================================
        # STEP 2: Load and persist portfolio & selections (monthly)
        # =====================================================================
        portfolio_csv = analytics_base / "portfolio" / "portfolio_latest.csv"
        portfolio_parquet = analytics_base / "portfolio" / "portfolio_latest.parquet"
        selections_csv = analytics_base / "selections" / "selections_latest.csv"
        selections_parquet = analytics_base / "selections" / "selections_latest.parquet"

        if portfolio_csv.exists() or portfolio_parquet.exists():
            logger.info("📋 Publishing Step 2 portfolio...")
            df_portfolio = _load_csv_or_parquet(portfolio_csv, portfolio_parquet)

            if df_portfolio is not None:
                step2_dir = processed_base / "step2"
                _ensure_dir(step2_dir)
                count = _publish_dataset(
                    "portfolio",
                    df_portfolio,
                    step2_dir,
                    minio_client,
                    bucket,
                    run_timestamp,
                    "processed",
                )
                write_count += count
                logger.info(
                    f"✓ Step 2 portfolio complete: {len(df_portfolio)} rows, {count} files written"
                )

                # Also copy to serving layer
                _ensure_dir(serving_base / "portfolio")
                serving_portfolio = serving_base / "portfolio" / "portfolio_latest.csv"
                df_portfolio.to_csv(serving_portfolio, index=False)
                logger.info(f"  ✓ Serving: {serving_portfolio}")
                write_count += 1

                # Upload to MinIO serving
                if minio_client:
                    object_key = "serving/portfolio/portfolio_latest.csv"
                    if _upload_file_to_minio(
                        minio_client, serving_portfolio, object_key, bucket
                    ):
                        write_count += 1
            else:
                logger.warning("✗ Could not load Step 2 portfolio")
                warning_count += 1
        else:
            logger.warning("✗ Step 2 portfolio not found")
            warning_count += 1

        if selections_csv.exists() or selections_parquet.exists():
            logger.info("📋 Publishing Step 2 selections...")
            df_selections = _load_csv_or_parquet(selections_csv, selections_parquet)

            if df_selections is not None:
                step2_dir = processed_base / "step2"
                _ensure_dir(step2_dir)
                count = _publish_dataset(
                    "selections",
                    df_selections,
                    step2_dir,
                    minio_client,
                    bucket,
                    run_timestamp,
                    "processed",
                )
                write_count += count
                logger.info(
                    f"✓ Step 2 selections complete: {len(df_selections)} rows, {count} files written"
                )

                # Also copy to serving layer
                _ensure_dir(serving_base / "selections")
                serving_selections = (
                    serving_base / "selections" / "selections_latest.csv"
                )
                df_selections.to_csv(serving_selections, index=False)
                logger.info(f"  ✓ Serving: {serving_selections}")
                write_count += 1

                # Upload to MinIO serving
                if minio_client:
                    object_key = "serving/selections/selections_latest.csv"
                    if _upload_file_to_minio(
                        minio_client, serving_selections, object_key, bucket
                    ):
                        write_count += 1
            else:
                logger.warning("✗ Could not load Step 2 selections")
                warning_count += 1
        else:
            logger.warning("✗ Step 2 selections not found")
            warning_count += 1

        # =====================================================================
        # STEP 3: Load and persist signals (daily) - CRITICAL
        # =====================================================================
        signals_csv = analytics_base / "signals" / "signals_latest.csv"
        signals_parquet = analytics_base / "signals" / "signals_latest.parquet"

        if signals_csv.exists() or signals_parquet.exists():
            logger.info("⚡ Publishing Step 3 signals...")
            df_signals = _load_csv_or_parquet(signals_csv, signals_parquet)

            if df_signals is not None:
                step3_dir = processed_base / "step3"
                _ensure_dir(step3_dir)
                count = _publish_dataset(
                    "signals",
                    df_signals,
                    step3_dir,
                    minio_client,
                    bucket,
                    run_timestamp,
                    "processed",
                )
                write_count += count

                # Signal distribution
                buy_count = len(df_signals[df_signals["final_trade_signal"] == 1])
                sell_count = len(df_signals[df_signals["final_trade_signal"] == -1])
                hold_count = len(df_signals[df_signals["final_trade_signal"] == 0])
                logger.info(
                    f"  Signal counts: BUY={buy_count}, SELL={sell_count}, HOLD={hold_count}"
                )
                logger.info(
                    f"✓ Step 3 signals complete: {len(df_signals)} rows, {count} files written"
                )

                # Also copy to serving layer
                _ensure_dir(serving_base / "signals")
                serving_signals = serving_base / "signals" / "signals_latest.csv"
                df_signals.to_csv(serving_signals, index=False)
                logger.info(f"  ✓ Serving: {serving_signals}")
                write_count += 1

                # Upload to MinIO serving
                if minio_client:
                    object_key = "serving/signals/signals_latest.csv"
                    if _upload_file_to_minio(
                        minio_client, serving_signals, object_key, bucket
                    ):
                        write_count += 1
            else:
                logger.error("✗ Could not load Step 3 signals - CRITICAL")
                return False
        else:
            logger.error("✗ Step 3 signals not found - CRITICAL")
            return False

        # =====================================================================
        # Summary
        # =====================================================================
        logger.info("=" * 70)
        logger.info(f"✓ Step 4 complete: {write_count} files published (local + MinIO)")
        if warning_count > 0:
            logger.warning(f"⚠️  {warning_count} warnings during publishing")
        if minio_client:
            logger.info(f"✓ MinIO bucket: {bucket}")
        else:
            logger.warning("⚠️  MinIO not available (local publishing only)")

        logger.info("📦 Data lake structure:")
        logger.info("  analytics/raw/prices/               → raw price cache")
        logger.info(
            "  analytics/processed/step1/          → factors (versioned + latest)"
        )
        logger.info(
            "  analytics/processed/step2/          → portfolio + selections (versioned + latest)"
        )
        logger.info(
            "  analytics/processed/step3/          → signals (versioned + latest)"
        )
        logger.info(
            "  analytics/serving/                  → latest CSV files for consumption"
        )

        return True

    except Exception as e:
        logger.error(f"Step 4 failed: {e}", exc_info=True)
        return False


def export_with_status_tracking():
    """
    Execute export with detailed status tracking.

    Returns:
        (success: bool, export_status: ExportStatus, details: dict)
    """
    logger.info("Step 4/4: Data Lake Publishing (Local + MinIO)")
    logger.info("=" * 70)

    # Check MinIO configuration first
    _apply_minio_env_fallback_from_config()
    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    bucket = os.getenv("MINIO_BUCKET", "trading-analytics")

    config_provided, config_error = MinIODiagnostics.check_env_vars()

    # Log configuration (without secrets)
    MinIODiagnostics.log_configuration(
        endpoint, bucket, bool(access_key), bool(secret_key)
    )

    details = {
        "minio_configured": config_provided,
        "minio_endpoint": endpoint,
        "minio_bucket": bucket,
        "minio_connection_error": None,
        "minio_upload_errors": 0,
        "local_files_created": 0,
    }

    # If MinIO not configured, just do local export
    if not config_provided:
        logger.info(f"ℹ  MinIO not configured: {config_error}")
        logger.info("Proceeding with local-only export...")
        success = export_to_local_and_minio()
        return success, ExportStatus.DISABLED, details

    # MinIO is configured, do preflight check
    logger.info("Running MinIO preflight checks...")
    preflight_ok, preflight_error = MinIODiagnostics.preflight_check_connectivity(
        endpoint, access_key, secret_key, bucket
    )

    if not preflight_ok:
        details["minio_connection_error"] = preflight_error
        logger.error(f"❌ MinIO preflight check failed: {preflight_error}")
        logger.error("Proceeding with local-only export...")
        success = export_to_local_and_minio()
        if success:
            return True, ExportStatus.MINIO_FAILED, details
        else:
            return False, ExportStatus.MINIO_FAILED, details

    # Preflight passed, proceed with full export (includes MinIO)
    logger.info("✓ MinIO preflight check passed, proceeding with full export...")
    success = export_to_local_and_minio()

    # Determine final export status
    if success:
        export_status = ExportStatus.MINIO_SUCCESS
    else:
        export_status = ExportStatus.MINIO_FAILED

    return success, export_status, details


if __name__ == "__main__":
    import json

    success, export_status, details = export_with_status_tracking()

    # Output status as JSON for run_pipeline.py to parse
    status_output = {
        "success": success,
        "export_status": export_status.value,
        "minio_configured": details["minio_configured"],
        "minio_endpoint": details["minio_endpoint"],
        "minio_bucket": details["minio_bucket"],
        "minio_connection_error": details["minio_connection_error"],
    }

    # Print status JSON to stdout (run_pipeline.py will parse this)
    print(f"__EXPORT_STATUS_JSON__:{json.dumps(status_output)}")

    sys.exit(0 if success else 1)
