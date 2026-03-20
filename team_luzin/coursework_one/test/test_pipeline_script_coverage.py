"""Coverage-focused tests for pipeline step scripts."""

from pathlib import Path

import pandas as pd
import pytest
import yaml

from modules.pipeline_results import ExportStatus
from pipeline import calculate_composite_portfolio as step2
from pipeline import calculate_var_all_stocks as step1
from pipeline import export_analytics_to_minio as step4
from pipeline import trading_execution as step3

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


def _make_price_df(rows: int = 300) -> pd.DataFrame:
    """Create deterministic OHLCV data with lowercase column names."""
    idx = list(range(rows))
    close = [100 + i * 0.1 for i in idx]
    return pd.DataFrame(
        {
            "open": [c - 0.2 for c in close],
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "volume": [1_000_000 + i * 100 for i in idx],
        }
    )


def _seed_step2_factors(base: Path) -> None:
    """Create minimal factors_latest.csv expected by step 2."""
    portfolio_dir = base / "analytics" / "portfolio"
    portfolio_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "gics_sector": "Technology",
                "normalized_sector": "Information Technology",
                "momentum_252": 0.12,
                "volatility_252": 0.20,
                "risk_adjusted_momentum_252": 0.60,
                "volume_60d_avg": 2_100_000,
                "var_95": -0.035,
                "atr_pct": 2.1,
                "atr_14": 2.5,
            },
            {
                "symbol": "AAB",
                "gics_sector": "Technology",
                "normalized_sector": "Information Technology",
                "momentum_252": 0.10,
                "volatility_252": 0.22,
                "risk_adjusted_momentum_252": 0.45,
                "volume_60d_avg": 1_900_000,
                "var_95": -0.042,
                "atr_pct": 2.4,
                "atr_14": 2.8,
            },
            {
                "symbol": "BBB",
                "gics_sector": "Healthcare",
                "normalized_sector": "Healthcare",
                "momentum_252": 0.08,
                "volatility_252": 0.18,
                "risk_adjusted_momentum_252": 0.44,
                "volume_60d_avg": 1_200_000,
                "var_95": -0.028,
                "atr_pct": 1.7,
                "atr_14": 1.9,
            },
            {
                "symbol": "BBC",
                "gics_sector": "Healthcare",
                "normalized_sector": "Healthcare",
                "momentum_252": 0.06,
                "volatility_252": 0.19,
                "risk_adjusted_momentum_252": 0.35,
                "volume_60d_avg": 1_100_000,
                "var_95": -0.031,
                "atr_pct": 1.8,
                "atr_14": 2.0,
            },
        ]
    )
    df.to_csv(portfolio_dir / "factors_latest.csv", index=False)


def _seed_step3_inputs(base: Path) -> None:
    """Create selections + portfolio latest files expected by step 3."""
    selections_dir = base / "analytics" / "selections"
    portfolio_dir = base / "analytics" / "portfolio"
    selections_dir.mkdir(parents=True, exist_ok=True)
    portfolio_dir.mkdir(parents=True, exist_ok=True)

    df_sel = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "gics_sector": "Technology",
                "normalized_sector": "Information Technology",
                "score": 1.2,
                "sector_rank": 1.0,
            },
            {
                "symbol": "BBB",
                "gics_sector": "Healthcare",
                "normalized_sector": "Healthcare",
                "score": 0.9,
                "sector_rank": 1.0,
            },
        ]
    )
    df_portfolio = pd.DataFrame(
        [
            {"symbol": "AAA", "volume_60d_avg": 2_100_000, "var_95": -0.035},
            {"symbol": "BBB", "volume_60d_avg": 1_200_000, "var_95": -0.028},
        ]
    )

    df_sel.to_csv(selections_dir / "selections_latest.csv", index=False)
    df_portfolio.to_csv(portfolio_dir / "portfolio_latest.csv", index=False)


def _seed_step4_inputs(base: Path) -> None:
    """Create step outputs expected by step 4 export."""
    analytics = base / "analytics"
    (analytics / "portfolio").mkdir(parents=True, exist_ok=True)
    (analytics / "selections").mkdir(parents=True, exist_ok=True)
    (analytics / "signals").mkdir(parents=True, exist_ok=True)

    pd.DataFrame([{"symbol": "AAA", "var_95": -0.03}]).to_csv(
        analytics / "portfolio" / "factors_latest.csv", index=False
    )
    pd.DataFrame([{"symbol": "AAA", "score": 1.2}]).to_csv(
        analytics / "portfolio" / "portfolio_latest.csv", index=False
    )
    pd.DataFrame([{"symbol": "AAA", "score": 1.2}]).to_csv(
        analytics / "selections" / "selections_latest.csv", index=False
    )
    pd.DataFrame([{"symbol": "AAA", "final_trade_signal": 0}]).to_csv(
        analytics / "signals" / "signals_latest.csv", index=False
    )


def test_step1_calculate_var_all_stocks_success(monkeypatch, tmp_path):
    """Step 1 should complete and publish latest factor files."""

    class FakeDB:
        def get_company_universe(self):
            return [{"symbol": "AAA", "gics_sector": "Technology"}]

        def disconnect(self):
            return None

    class FakeExtractor:
        def __init__(self, years):
            self.years = years

        def fetch_price_data(self, symbol):
            return _make_price_df(300)

    fake_file = tmp_path / "pipeline" / "calculate_var_all_stocks.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# test", encoding="utf-8")

    monkeypatch.setattr(step1, "__file__", str(fake_file))
    monkeypatch.setattr(step1, "load_config", lambda: {"postgres": {}})
    monkeypatch.setattr(step1, "PostgresConnector", lambda _: FakeDB())
    monkeypatch.setattr(step1, "PriceDataExtractor", FakeExtractor)

    assert step1.calculate_var_all_stocks() is True
    assert (tmp_path / "analytics" / "portfolio" / "factors_latest.csv").exists()
    assert (tmp_path / "analytics" / "portfolio" / "factors_latest.parquet").exists()


def test_step1_calculate_var_all_stocks_empty_universe(monkeypatch, tmp_path):
    """Step 1 should fail gracefully when company universe is empty."""

    class FakeDB:
        def get_company_universe(self):
            return []

        def disconnect(self):
            return None

    fake_file = tmp_path / "pipeline" / "calculate_var_all_stocks.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# test", encoding="utf-8")

    monkeypatch.setattr(step1, "__file__", str(fake_file))
    monkeypatch.setattr(step1, "load_config", lambda: {"postgres": {}})
    monkeypatch.setattr(step1, "PostgresConnector", lambda _: FakeDB())

    assert step1.calculate_var_all_stocks() is False


def test_step2_composite_portfolio_success(monkeypatch, tmp_path):
    """Step 2 should create portfolio and selections latest outputs."""
    _seed_step2_factors(tmp_path)

    fake_file = tmp_path / "pipeline" / "calculate_composite_portfolio.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# test", encoding="utf-8")
    monkeypatch.setattr(step2, "__file__", str(fake_file))

    assert step2.calculate_composite_portfolio() is True
    assert (tmp_path / "analytics" / "portfolio" / "portfolio_latest.csv").exists()
    assert (tmp_path / "analytics" / "selections" / "selections_latest.csv").exists()


def test_step2_load_factors_missing_file(monkeypatch, tmp_path):
    """Step 2 loader should return None when factors file is missing."""
    fake_file = tmp_path / "pipeline" / "calculate_composite_portfolio.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# test", encoding="utf-8")
    monkeypatch.setattr(step2, "__file__", str(fake_file))

    assert step2.load_factors() is None


def test_step3_trading_execution_success(monkeypatch, tmp_path):
    """Step 3 should create latest signal outputs from selections."""
    _seed_step3_inputs(tmp_path)

    class FakeExtractor:
        def __init__(self, years):
            self.years = years

        def fetch_price_data(self, symbol):
            return _make_price_df(320)

    fake_file = tmp_path / "pipeline" / "trading_execution.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# test", encoding="utf-8")

    monkeypatch.setattr(step3, "__file__", str(fake_file))
    monkeypatch.setattr(step3, "PriceDataExtractor", FakeExtractor)

    assert step3.trading_execution() is True
    assert (tmp_path / "analytics" / "signals" / "signals_latest.csv").exists()
    assert (tmp_path / "analytics" / "signals" / "signals_latest.parquet").exists()


def test_step3_trading_execution_no_selections(monkeypatch, tmp_path):
    """Step 3 should fail gracefully when selections are unavailable."""
    fake_file = tmp_path / "pipeline" / "trading_execution.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# test", encoding="utf-8")
    monkeypatch.setattr(step3, "__file__", str(fake_file))

    assert step3.trading_execution() is False


def test_step4_export_to_local_and_minio_local_only(monkeypatch, tmp_path):
    """Step 4 should publish local processed/serving outputs without MinIO."""
    _seed_step4_inputs(tmp_path)

    fake_file = tmp_path / "pipeline" / "export_analytics_to_minio.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# test", encoding="utf-8")

    monkeypatch.setattr(step4, "__file__", str(fake_file))
    monkeypatch.setattr(step4, "_init_minio_client", lambda: None)

    assert step4.export_to_local_and_minio() is True
    assert (tmp_path / "analytics" / "processed" / "step1" / "factors_latest.csv").exists()
    assert (
        tmp_path / "analytics" / "serving" / "signals" / "signals_latest.csv"
    ).exists()


def test_step4_export_with_status_tracking_disabled(monkeypatch):
    """Status tracking should return DISABLED when MinIO config is missing."""
    monkeypatch.setattr(step4.MinIODiagnostics, "check_env_vars", lambda: (False, "missing"))
    monkeypatch.setattr(step4.MinIODiagnostics, "log_configuration", lambda *args, **kwargs: None)
    monkeypatch.setattr(step4, "export_to_local_and_minio", lambda: True)

    success, export_status, details = step4.export_with_status_tracking()

    assert success is True
    assert export_status == ExportStatus.DISABLED
    assert details["minio_configured"] is False


def test_step1_load_config_reads_yaml(monkeypatch, tmp_path):
    """Step 1 load_config should read config/conf.yaml from project root."""
    fake_file = tmp_path / "pipeline" / "calculate_var_all_stocks.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# test", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    expected = {"postgres": {"host": "localhost", "port": 5439}}
    (config_dir / "conf.yaml").write_text(yaml.safe_dump(expected), encoding="utf-8")

    monkeypatch.setattr(step1, "__file__", str(fake_file))
    loaded = step1.load_config()
    assert loaded == expected


def test_step1_normalize_ohlcv_and_sector_helpers():
    """Step 1 helper utilities should normalize OHLCV and sector names correctly."""
    df = pd.DataFrame(
        {
            "Open": [1],
            "HIGH": [2],
            "low": [0.5],
            "Close": [1.5],
            "volume": [1000],
        }
    )
    normalized = step1._normalize_ohlcv(df)
    assert normalized is not None
    assert list(normalized.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert step1.normalize_sector_name("Technology") == "Information Technology"
    assert step1.normalize_sector_name("  ") is None


def test_step3_cache_helpers_and_fallback(monkeypatch, tmp_path):
    """Step 3 cache and fallback functions should handle local and external flows."""
    raw_dir = tmp_path / "analytics" / "raw" / "prices"
    raw_dir.mkdir(parents=True, exist_ok=True)

    df_cached = pd.DataFrame(
        {
            "Open": [1.0, 1.1],
            "High": [1.2, 1.3],
            "Low": [0.9, 1.0],
            "Close": [1.1, 1.2],
            "Volume": [1000, 1100],
        },
        index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
    )

    step3._write_local_raw_cache("AAA", df_cached, raw_dir)
    loaded = step3._read_local_raw_cache("AAA", raw_dir)
    assert loaded is not None

    class DummyExtractor:
        def fetch_price_data(self, symbol):
            return _make_price_df(40)

    local_df, source = step3._get_prices_with_fallback("AAA", DummyExtractor(), raw_dir, 5)
    assert source == "local_cache"
    assert local_df is not None

    fresh_df, source = step3._get_prices_with_fallback(
        "BBB", DummyExtractor(), raw_dir, 5
    )
    assert source == "external_fetch"
    assert fresh_df is not None


def test_step4_init_minio_client_no_library(monkeypatch):
    """Step 4 should return None when MinIO library is unavailable."""
    monkeypatch.setattr(step4, "MINIO_AVAILABLE", False)
    assert step4._init_minio_client() is None


def test_step4_init_minio_client_missing_env(monkeypatch):
    """Step 4 should return None when mandatory MinIO env vars are absent."""
    monkeypatch.setattr(step4, "MINIO_AVAILABLE", True)
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
    monkeypatch.delenv("MINIO_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MINIO_SECRET_KEY", raising=False)
    assert step4._init_minio_client() is None


def test_step4_upload_and_raw_publish_with_fake_minio(monkeypatch, tmp_path):
    """Step 4 upload helpers should count uploaded files correctly."""

    class FakeMinio:
        def __init__(self):
            self.uploaded = []

        def fput_object(self, bucket, object_key, local_path):
            self.uploaded.append((bucket, object_key, local_path))

    # _upload_file_to_minio success
    fake_file = tmp_path / "a.csv"
    fake_file.write_text("x\n1\n", encoding="utf-8")
    fake_client = FakeMinio()
    assert step4._upload_file_to_minio(fake_client, fake_file, "x/a.csv", "bucket") is True

    # _publish_raw_data paths
    fake_step4_file = tmp_path / "pipeline" / "export_analytics_to_minio.py"
    fake_step4_file.parent.mkdir(parents=True, exist_ok=True)
    fake_step4_file.write_text("# test", encoding="utf-8")
    monkeypatch.setattr(step4, "__file__", str(fake_step4_file))

    raw_dir = tmp_path / "analytics" / "raw" / "prices"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "AAA.csv").write_text("x\n1\n", encoding="utf-8")
    pd.DataFrame([{"x": 1}]).to_parquet(raw_dir / "BBB.parquet", index=False)

    count = step4._publish_raw_data(fake_client, "bucket")
    assert count == 2


def test_step4_init_minio_client_success(monkeypatch):
    """Step 4 should initialize MinIO client and create bucket when missing."""

    class FakeMinioClient:
        def __init__(self, endpoint, access_key, secret_key, secure):
            self.endpoint = endpoint
            self.access_key = access_key
            self.secret_key = secret_key
            self.secure = secure
            self.created = False

        def bucket_exists(self, bucket):
            return False

        def make_bucket(self, bucket):
            self.created = True

    monkeypatch.setattr(step4, "MINIO_AVAILABLE", True)
    monkeypatch.setattr(step4, "Minio", FakeMinioClient)
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "key")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MINIO_BUCKET", "bucket")
    monkeypatch.setenv("MINIO_SECURE", "false")

    client = step4._init_minio_client()
    assert client is not None
    assert client.created is True


def test_step4_load_csv_or_parquet_fallback_to_csv(tmp_path):
    """Step 4 loader should fall back to CSV when parquet read fails."""
    csv_path = tmp_path / "data.csv"
    parquet_path = tmp_path / "data.parquet"

    # Intentionally write invalid parquet content to force parquet read failure.
    parquet_path.write_text("not-a-parquet", encoding="utf-8")
    pd.DataFrame([{"a": 1}, {"a": 2}]).to_csv(csv_path, index=False)

    df = step4._load_csv_or_parquet(csv_path, parquet_path)
    assert df is not None
    assert len(df) == 2


def test_step4_export_with_status_tracking_preflight_fail(monkeypatch):
    """Step 4 should return MINIO_FAILED when preflight fails but local export succeeds."""
    monkeypatch.setattr(step4.MinIODiagnostics, "check_env_vars", lambda: (True, None))
    monkeypatch.setattr(step4.MinIODiagnostics, "log_configuration", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        step4.MinIODiagnostics,
        "preflight_check_connectivity",
        lambda endpoint, access_key, secret_key, bucket: (False, "connect error"),
    )
    monkeypatch.setattr(step4, "export_to_local_and_minio", lambda: True)
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "key")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MINIO_BUCKET", "bucket")

    success, export_status, details = step4.export_with_status_tracking()
    assert success is True
    assert export_status == ExportStatus.MINIO_FAILED
    assert details["minio_connection_error"] == "connect error"


def test_step4_export_with_status_tracking_preflight_success(monkeypatch):
    """Step 4 should return MINIO_SUCCESS when preflight and export both succeed."""
    monkeypatch.setattr(step4.MinIODiagnostics, "check_env_vars", lambda: (True, None))
    monkeypatch.setattr(step4.MinIODiagnostics, "log_configuration", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        step4.MinIODiagnostics,
        "preflight_check_connectivity",
        lambda endpoint, access_key, secret_key, bucket: (True, None),
    )
    monkeypatch.setattr(step4, "export_to_local_and_minio", lambda: True)
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "key")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MINIO_BUCKET", "bucket")

    success, export_status, _ = step4.export_with_status_tracking()
    assert success is True
    assert export_status == ExportStatus.MINIO_SUCCESS


def test_step4_export_with_status_tracking_preflight_success_export_fail(monkeypatch):
    """Step 4 should return MINIO_FAILED when preflight succeeds but export fails."""
    monkeypatch.setattr(step4.MinIODiagnostics, "check_env_vars", lambda: (True, None))
    monkeypatch.setattr(step4.MinIODiagnostics, "log_configuration", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        step4.MinIODiagnostics,
        "preflight_check_connectivity",
        lambda endpoint, access_key, secret_key, bucket: (True, None),
    )
    monkeypatch.setattr(step4, "export_to_local_and_minio", lambda: False)
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "key")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MINIO_BUCKET", "bucket")

    success, export_status, _ = step4.export_with_status_tracking()
    assert success is False
    assert export_status == ExportStatus.MINIO_FAILED
