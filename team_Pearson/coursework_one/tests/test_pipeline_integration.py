import os

import pytest

import Main
from modules.db import db_connection as db_connection_mod
from modules.input import extract_source_a as source_a_mod
from modules.output.normalize import normalize_records
from modules.output.quality import run_quality_checks


class _FakeScalarResult:
    def __init__(self, payload):
        self._payload = payload

    def mappings(self):
        return self

    def one(self):
        return self._payload


class _FakeConn:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def execute(self, stmt, params):
        self.calls.append((stmt, params))
        return _FakeScalarResult(self.payload)


class _FakeBeginCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def begin(self):
        return _FakeBeginCtx(self._conn)


def test_collect_normalize_quality_chain(monkeypatch):
    monkeypatch.setenv("CW1_TEST_MODE", "1")
    symbols = ["SYM00001", "SYM00002"]

    raw = Main.collect_raw_records(symbols, "2026-02-14", "daily", 5)
    assert len(raw) > 0

    curated = normalize_records(raw)
    assert len(curated) == len(raw)

    report = run_quality_checks(curated)

    assert report["row_count"] == len(curated)
    assert "missing_values" in report
    assert "duplicates" in report


def test_resolve_backfill_years_cli_then_env_then_config_then_default(monkeypatch):
    monkeypatch.delenv("PIPELINE_BACKFILL_YEARS", raising=False)
    assert Main._resolve_backfill_years(0, {}) == 0
    monkeypatch.setenv("PIPELINE_BACKFILL_YEARS", "3")
    assert Main._resolve_backfill_years(None, {"backfill_years": 2}) == 3
    monkeypatch.delenv("PIPELINE_BACKFILL_YEARS", raising=False)
    assert Main._resolve_backfill_years(None, {"backfill_years": 2}) == 2
    assert Main._resolve_backfill_years(None, {}) == 5

    with pytest.raises(ValueError):
        Main._resolve_backfill_years(-1, {})


def test_resolve_frequency_cli_then_env_then_config_then_default(monkeypatch):
    monkeypatch.delenv("PIPELINE_FREQUENCY", raising=False)
    assert Main._resolve_frequency("weekly", {"frequency": "monthly"}) == "weekly"
    monkeypatch.setenv("PIPELINE_FREQUENCY", "annual")
    assert Main._resolve_frequency(None, {"frequency": "monthly"}) == "annual"
    monkeypatch.delenv("PIPELINE_FREQUENCY", raising=False)
    assert Main._resolve_frequency(None, {"frequency": "monthly"}) == "monthly"
    assert Main._resolve_frequency(None, {}) == "daily"

    with pytest.raises(ValueError):
        Main._resolve_frequency("hourly", {})


def test_resolve_company_limit_cli_then_env_then_config_then_default(monkeypatch):
    monkeypatch.delenv("PIPELINE_COMPANY_LIMIT", raising=False)
    assert Main._resolve_company_limit(None, {"company_limit": None}) is None
    monkeypatch.setenv("PIPELINE_COMPANY_LIMIT", "7")
    assert Main._resolve_company_limit(None, {"company_limit": 3}) == 7
    monkeypatch.delenv("PIPELINE_COMPANY_LIMIT", raising=False)
    assert Main._resolve_company_limit(0, {}) is None
    assert Main._resolve_company_limit(-1, {}) is None
    assert Main._resolve_company_limit(5, {}) == 5
    assert Main._resolve_company_limit(None, {}) == 20

    with pytest.raises(ValueError):
        Main._resolve_company_limit("oops", {})


def test_resolve_enabled_extractors_cli_then_env_then_config_then_default(monkeypatch):
    monkeypatch.delenv("PIPELINE_ENABLED_EXTRACTORS", raising=False)
    assert Main._resolve_enabled_extractors(["source_a"], {}) == ["source_a"]
    monkeypatch.setenv("PIPELINE_ENABLED_EXTRACTORS", "source_b,source_a")
    assert Main._resolve_enabled_extractors(None, {"enabled_extractors": ["source_a"]}) == [
        "source_b",
        "source_a",
    ]
    monkeypatch.delenv("PIPELINE_ENABLED_EXTRACTORS", raising=False)
    assert Main._resolve_enabled_extractors(None, {"enabled_extractors": ["source_b"]}) == [
        "source_b"
    ]
    assert Main._resolve_enabled_extractors(None, {}) == ["source_a", "source_b"]

    with pytest.raises(
        ValueError,
        match=r"Allowed: \['market_factors', 'source_a', 'source_b'\]",
    ):
        Main._resolve_enabled_extractors(["source_c"], {})


def test_apply_env_defaults_from_config_populates_alpha_key_from_conf(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    status = Main.apply_env_defaults_from_config({"api": {"alpha_vantage_key": "abc123"}})
    assert os.getenv("ALPHA_VANTAGE_API_KEY") == "abc123"
    assert status["alpha_vantage_key_source"] == "conf"


def test_apply_env_defaults_from_config_ignores_placeholder_alpha_key(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    status = Main.apply_env_defaults_from_config({"api": {"alpha_vantage_key": "YOUR_KEY"}})
    assert os.getenv("ALPHA_VANTAGE_API_KEY") in (None, "")
    assert status["alpha_vantage_key_source"] == "missing"


def test_load_dotenv_sets_missing_vars_only(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ALPHA_VANTAGE_API_KEY=from_file\n", encoding="utf-8")

    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    Main._load_dotenv(str(env_file))
    assert os.getenv("ALPHA_VANTAGE_API_KEY") == "from_file"

    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "from_env")
    Main._load_dotenv(str(env_file))
    assert os.getenv("ALPHA_VANTAGE_API_KEY") == "from_env"


def test_source_a_supporting_rows_exist_requires_financials_when_registry_expects_them(monkeypatch):
    conn = _FakeConn({"has_price_rows": True, "has_financial_rows": False})
    monkeypatch.setattr(db_connection_mod, "get_db_engine", lambda: _FakeEngine(conn))
    monkeypatch.setattr(source_a_mod, "_rolling_window_start_date", lambda *_: "2025-04-15")

    out = Main._source_a_supporting_rows_exist(
        run_date="2026-04-15",
        backfill_years=1,
        symbol="AAPL",
        reusable_details={"curated_rows": 100, "financial_rows": 4, "loaded_rows": 104},
    )

    assert out is False
    assert conn.calls[0][1]["symbol"] == "AAPL"
    assert conn.calls[0][1]["start_date"] == "2025-04-15"


def test_source_a_supporting_rows_exist_allows_price_only_registry(monkeypatch):
    conn = _FakeConn({"has_price_rows": True, "has_financial_rows": False})
    monkeypatch.setattr(db_connection_mod, "get_db_engine", lambda: _FakeEngine(conn))
    monkeypatch.setattr(source_a_mod, "_rolling_window_start_date", lambda *_: "2025-04-15")

    out = Main._source_a_supporting_rows_exist(
        run_date="2026-04-15",
        backfill_years=1,
        symbol="SPY",
        reusable_details={"curated_rows": 100, "financial_rows": 0, "loaded_rows": 100},
    )

    assert out is True


def test_source_b_supporting_rows_exist_requires_rows_when_registry_expects_them(monkeypatch):
    conn = _FakeConn({"has_source_b_rows": False})
    monkeypatch.setattr(db_connection_mod, "get_db_engine", lambda: _FakeEngine(conn))

    out = Main._source_b_supporting_rows_exist(
        symbol="AAPL",
        month_start="2026-02-01",
        fetch_end="2026-02-28",
        reusable_details={"articles": 10, "loaded_rows": 19},
    )

    assert out is False
    assert conn.calls[0][1]["symbol"] == "AAPL"
    assert conn.calls[0][1]["month_start"] == "2026-02-01"
    assert conn.calls[0][1]["fetch_end"] == "2026-02-28"


def test_source_b_supporting_rows_exist_allows_empty_registry_without_rows(monkeypatch):
    monkeypatch.setattr(
        db_connection_mod,
        "get_db_engine",
        lambda: pytest.fail("DB should not be queried when no Source B rows are expected"),
    )

    out = Main._source_b_supporting_rows_exist(
        symbol="AAPL",
        month_start="2026-02-01",
        fetch_end="2026-02-28",
        reusable_details={"articles": 0, "loaded_rows": 0},
    )

    assert out is True
