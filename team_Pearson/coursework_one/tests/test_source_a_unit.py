import importlib
import json
import math

import pandas as pd

source_a = importlib.import_module("modules.input.extract_source_a")


class _FakeTickerWithDebt:
    def __init__(self):
        self.quarterly_balance_sheet = pd.DataFrame({"2025Q4": [123.0]}, index=["Total Debt"])


class _FakeTickerNoDebt:
    def __init__(self):
        self.quarterly_balance_sheet = pd.DataFrame()
        self.info = {}


def test_extract_source_a_test_mode(monkeypatch):
    monkeypatch.setenv("CW1_TEST_MODE", "1")
    out = source_a.extract_source_a(
        symbols=["AAPL", "MSFT"],
        run_date="2026-02-14",
        backfill_years=1,
        frequency="daily",
    )
    assert len(out) == 2
    assert all(r["source"] == "alpha_vantage" for r in out)


def test_extract_total_debt_found():
    assert source_a._extract_total_debt(_FakeTickerWithDebt()) == 123.0


def test_extract_total_debt_missing_returns_none():
    assert source_a._extract_total_debt(_FakeTickerNoDebt()) is None


def test_rolling_window_start_date_is_12_months():
    assert source_a._rolling_window_start_date("2026-03-02", 1) == "2025-03-02"
    assert source_a._rolling_window_start_date("2026-03-31", 1) == "2025-03-31"
    assert source_a._rolling_window_start_date("2026-02-14", 0) == "2026-02-14"


def test_in_backfill_window_uses_rolling_month_window():
    assert source_a._in_backfill_window("2025-03-31", "2026-03-02", 1)
    assert not source_a._in_backfill_window("2025-02-28", "2026-03-02", 1)


def test_extract_fundamentals_from_yfinance_ticker():
    class _T:
        def __init__(self):
            self.quarterly_balance_sheet = pd.DataFrame({"2025Q4": [123.0]}, index=["Total Debt"])
            self.info = {
                "bookValue": 20.5,
                "totalStockholderEquity": 999.0,
                "sharesOutstanding": 1000000,
                "ebitda": 5000000,
                "totalRevenue": 15000000,
            }

    out = source_a._extract_fundamentals_from_yfinance_ticker(_T())
    assert out["total_debt"] == 123.0
    assert out["total_shareholder_equity"] == 999.0
    assert out["book_value"] == 20.5
    assert out["shares_outstanding"] == 1000000.0
    assert out["enterprise_ebitda"] == 5000000.0
    assert out["enterprise_revenue"] == 15000000.0


def test_extract_fundamentals_unified_order_av_then_yf_fallback(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")

    def _av_overview(symbol, api_key):  # noqa: ARG001
        return {
            "TotalDebt": "",
            "BookValue": "10.0",
            "SharesOutstanding": "",
            "EBITDA": "200.0",
            "RevenueTTM": "",
        }

    monkeypatch.setattr(source_a, "_download_overview_alpha_vantage", _av_overview)
    monkeypatch.setattr(
        source_a,
        "_download_balance_sheet_alpha_vantage",
        lambda symbol, api_key: {"quarterlyReports": [{"totalShareholderEquity": "700.0"}]},
    )

    class _Ticker:
        def __init__(self):
            self.quarterly_balance_sheet = pd.DataFrame()
            self.info = {
                "totalDebt": 300.0,
                "sharesOutstanding": 12345,
                "totalRevenue": 900.0,
            }

    out = source_a._extract_fundamentals(symbol="AAPL", ticker=_Ticker(), config={})
    # AV values kept when present
    assert out["book_value"] == 10.0
    assert out["enterprise_ebitda"] == 200.0
    assert out["total_shareholder_equity"] == 700.0
    # Missing AV values filled by yfinance
    assert out["total_debt"] == 300.0
    assert out["shares_outstanding"] == 12345.0
    assert out["enterprise_revenue"] == 900.0


def test_extract_fundamentals_uses_income_statement_for_quarterly_enterprise_metrics(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")

    monkeypatch.setattr(
        source_a,
        "_download_overview_alpha_vantage",
        lambda symbol, api_key: {
            "TotalDebt": "100",
            "BookValue": "10",
            "SharesOutstanding": "5",
            "EBITDA": "200",
            "RevenueTTM": "500",
            "LatestQuarter": "2025-12-31",
            "Currency": "USD",
        },
    )
    monkeypatch.setattr(
        source_a,
        "_download_balance_sheet_alpha_vantage",
        lambda symbol, api_key: {
            "quarterlyReports": [
                {
                    "fiscalDateEnding": "2025-12-31",
                    "totalDebt": "120",
                    "totalShareholderEquity": "300",
                    "commonStockSharesOutstanding": "10",
                },
                {
                    "fiscalDateEnding": "2025-09-30",
                    "totalDebt": "110",
                    "totalShareholderEquity": "280",
                    "commonStockSharesOutstanding": "10",
                },
            ]
        },
    )
    monkeypatch.setattr(
        source_a,
        "_download_income_statement_alpha_vantage",
        lambda symbol, api_key: {
            "quarterlyReports": [
                {
                    "fiscalDateEnding": "2025-12-31",
                    "ebitda": "210",
                    "totalRevenue": "520",
                },
                {
                    "fiscalDateEnding": "2025-09-30",
                    "ebitda": "190",
                    "totalRevenue": "480",
                },
            ]
        },
    )

    class _Ticker:
        def __init__(self):
            self.quarterly_balance_sheet = pd.DataFrame()
            self.info = {}

    out = source_a._extract_fundamentals(
        symbol="SYM1",
        ticker=_Ticker(),
        config={},
        run_date="2026-02-14",
        backfill_years=1,
    )
    qf = out["quarterly_fundamentals"]
    assert len(qf) == 2
    latest = [r for r in qf if r["report_date"] == "2025-12-31"][0]
    assert latest["enterprise_ebitda"] == 210.0
    assert latest["enterprise_revenue"] == 520.0


def test_build_records_from_history_shape():
    idx = pd.to_datetime(["2026-02-13", "2026-02-14"])
    history = pd.DataFrame(
        {
            "Close": [100.0, 101.0],
            "Dividends": [0.0, 0.1],
        },
        index=idx,
    )
    out = source_a._build_records_from_history(
        symbol="AAPL",
        history=history,
        run_date="2026-02-14",
        frequency="daily",
    )
    assert len(out) == 6
    names = {r["factor_name"] for r in out}
    assert {"adjusted_close_price", "daily_return", "dividend_per_share"} == names
    dr = [r for r in out if r["factor_name"] == "daily_return"]
    assert len(dr) == 2
    assert dr[0]["value"] is None
    assert abs(dr[1]["value"] - math.log(1.01)) < 1e-12


def test_build_fundamental_records_shape():
    out = source_a._build_fundamental_records(
        symbol="AAPL",
        run_date="2026-02-14",
        frequency="daily",
        source_label="alpha_vantage",
        fundamentals={
            "total_debt": 300.0,
            "total_shareholder_equity": 120.0,
            "book_value": 10.0,
            "shares_outstanding": 100.0,
            "enterprise_ebitda": 30.0,
            "enterprise_revenue": 200.0,
        },
    )
    assert len(out) == 6
    names = {r["factor_name"] for r in out}
    assert {
        "total_debt",
        "total_shareholder_equity",
        "book_value",
        "shares_outstanding",
        "enterprise_ebitda",
        "enterprise_revenue",
    } == names
    assert all(r["source_report_date"] is None for r in out)
    assert all(r["observation_date"] is None for r in out)


def test_build_fundamental_records_expands_quarters_within_backfill_window():
    out = source_a._build_fundamental_records(
        symbol="AAPL",
        run_date="2026-02-14",
        frequency="daily",
        source_label="alpha_vantage",
        backfill_years=1,
        fundamentals={
            "quarterly_fundamentals": [
                {
                    "report_date": "2024-09-30",
                    "total_debt": 1.0,
                    "total_shareholder_equity": 2.0,
                },
                {
                    "report_date": "2025-03-31",
                    "total_debt": 3.0,
                    "total_shareholder_equity": 4.0,
                },
                {
                    "report_date": "2025-06-30",
                    "total_debt": 5.0,
                    "total_shareholder_equity": 6.0,
                },
                {
                    "report_date": "2025-09-30",
                    "total_debt": 7.0,
                    "total_shareholder_equity": 8.0,
                },
                {
                    "report_date": "2025-12-31",
                    "total_debt": 9.0,
                    "total_shareholder_equity": 10.0,
                },
            ]
        },
    )
    report_dates = sorted({r["report_date"] for r in out if r["report_date"] is not None})
    assert report_dates == ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
    assert len(out) == 24  # 4 quarters * 6 financial metrics


def test_extract_source_a_handles_symbol_failure(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)

    def _boom(symbol, years_back, max_retries=3):
        raise RuntimeError("boom")

    monkeypatch.setattr(source_a, "_download_price_history", _boom)
    monkeypatch.setattr(source_a, "_save_raw_to_minio", lambda *args, **kwargs: None)

    out = source_a.extract_source_a(
        symbols=["AAPL"],
        run_date="2026-02-14",
        backfill_years=1,
        frequency="daily",
        config={"minio": {}},
    )
    assert out == []


def test_load_config_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "missing.yaml"
    assert source_a.load_config(str(missing)) == {}


def test_load_config_reads_yaml(tmp_path):
    cfg = tmp_path / "conf.yaml"
    cfg.write_text("pipeline:\n  company_limit: 2\n", encoding="utf-8")
    out = source_a.load_config(str(cfg))
    assert out["pipeline"]["company_limit"] == 2


def test_save_raw_to_minio_skips_when_config_incomplete():
    source_a._save_raw_to_minio(config={}, symbol="AAPL", run_date="2026-02-14", payload={})


def test_save_raw_to_minio_happy_path(monkeypatch):
    events = {"put": None}

    class _FakeMinio:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def bucket_exists(self, bucket):
            return True

        def make_bucket(self, bucket):
            raise AssertionError("should not create bucket when exists")

        def put_object(self, bucket, object_name, data, length, content_type):
            events["put"] = (bucket, object_name, length, content_type, json.loads(data.read()))

    monkeypatch.setitem(__import__("sys").modules, "minio", type("M", (), {"Minio": _FakeMinio}))
    cfg = {
        "minio": {
            "endpoint": "localhost:9000",
            "access_key": "x",
            "secret_key": "y",
            "bucket": "csreport",
            "secure": False,
        }
    }
    source_a._save_raw_to_minio(cfg, "AAPL", "2026-02-14", {"k": "v"})
    assert events["put"][0] == "csreport"
    assert "raw/source_a/pricing_fundamentals/" in events["put"][1]


def test_save_raw_to_minio_serializes_timestamp(monkeypatch):
    events = {"payload": None}

    class _FakeMinio:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def bucket_exists(self, bucket):
            return True

        def make_bucket(self, bucket):
            raise AssertionError("should not create bucket when exists")

        def put_object(self, bucket, object_name, data, length, content_type):
            _ = (bucket, object_name, length, content_type)
            events["payload"] = json.loads(data.read())

    monkeypatch.setitem(__import__("sys").modules, "minio", type("M", (), {"Minio": _FakeMinio}))
    cfg = {
        "minio": {
            "endpoint": "localhost:9000",
            "access_key": "x",
            "secret_key": "y",
            "bucket": "csreport",
            "secure": False,
        }
    }
    payload = {"history": [{"Date": pd.Timestamp("2026-02-14"), "Close": 101.0}]}
    source_a._save_raw_to_minio(cfg, "AAPL", "2026-02-14", payload)
    assert events["payload"]["history"][0]["Date"].startswith("2026-02-14")


def test_download_price_history_with_fake_yfinance(monkeypatch):
    class _FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, auto_adjust=False):
            idx = pd.to_datetime(["2026-02-13"])
            return pd.DataFrame({"Close": [101.0], "Dividends": [0.0]}, index=idx)

    monkeypatch.setitem(
        __import__("sys").modules, "yfinance", type("YF", (), {"Ticker": _FakeTicker})
    )
    ticker, history = source_a._download_price_history("AAPL", 1)
    assert ticker.symbol == "AAPL"
    assert len(history) == 1


def test_build_technical_records_drops_if_less_than_20_days():
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    history = pd.DataFrame({"Close": [float(100 + i) for i in range(10)]}, index=idx)
    out = source_a._build_technical_records("AAPL", history, "daily", "alpha_vantage")
    assert out == []


def test_build_technical_records_generates_momentum_and_volatility():
    idx = pd.date_range("2026-01-01", periods=25, freq="D")
    history = pd.DataFrame({"Close": [float(100 + i) for i in range(25)]}, index=idx)
    out = source_a._build_technical_records("AAPL", history, "daily", "alpha_vantage")
    names = {r["factor_name"] for r in out}
    assert "momentum_1m" in names
    assert "volatility_20d" in names
    assert all(r["source"] == "alpha_vantage" for r in out)


def test_build_technical_records_drops_non_positive_prices():
    idx = pd.date_range("2026-01-01", periods=25, freq="D")
    prices = [float(100 + i) for i in range(25)]
    prices[20] = 0.0
    history = pd.DataFrame({"Close": prices}, index=idx)

    out = source_a._build_technical_records("AAPL", history, "daily", "alpha_vantage")
    bad_date = idx[20].date().isoformat()
    assert all(r["observation_date"] != bad_date for r in out)
    assert all(pd.notna(r["value"]) for r in out)


def test_download_with_provider_falls_back_to_yfinance(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "x")

    def _boom(*args, **kwargs):
        raise RuntimeError("alpha down")

    class _Ticker:
        symbol = "AAPL"

    def _ok(symbol, years_back, max_retries=3):
        _ = (symbol, years_back, max_retries)
        idx = pd.to_datetime(["2026-02-13"])
        return _Ticker(), pd.DataFrame({"Close": [101.0], "Dividends": [0.0]}, index=idx)

    monkeypatch.setattr(source_a, "_download_price_history_alpha_vantage", _boom)
    monkeypatch.setattr(source_a, "_download_price_history", _ok)

    source, ticker, history = source_a._download_with_provider(
        "AAPL",
        1,
        {"source_a": {"primary_source": "alpha_vantage", "enable_yfinance_fallback": True}},
    )
    assert source == "yfinance"
    assert ticker.symbol == "AAPL"
    assert len(history) == 1


def test_resolve_alpha_key_from_config_when_env_missing(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    key = source_a._resolve_alpha_key({"api": {"alpha_vantage_key": "abc123"}})
    assert key == "abc123"


def test_resolve_alpha_key_with_source_env_overrides_conf(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "env_key")
    key, source = source_a._resolve_alpha_key_with_source(
        {"api": {"alpha_vantage_key": "conf_key"}}
    )
    assert key == "env_key"
    assert source == "env"


def test_resolve_alpha_key_with_source_conf_when_env_placeholder(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "YOUR_KEY")
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    key, source = source_a._resolve_alpha_key_with_source(
        {"alpha_vantage": {"api_key": "conf_key"}}
    )
    assert key == "conf_key"
    assert source == "conf"


def test_select_source_order_default_and_with_fallback_disabled():
    assert source_a._select_source_order({}) == ["alpha_vantage", "yfinance"]
    out = source_a._select_source_order(
        {"source_a": {"primary_source": "alpha_vantage", "enable_yfinance_fallback": False}}
    )
    assert out == ["alpha_vantage"]


def test_select_provider_order_routes_suffix_to_yfinance():
    out = source_a._select_provider_order_for_symbol(
        "VOD.L", {"routing": {"yf_for_suffixes": [".L"]}}
    )
    assert out == ["yfinance"]


def test_select_provider_order_history_blocklist_skip():
    out = source_a._select_provider_order_for_symbol(
        "ABC", {"routing": {"history_ticker_policy": "skip", "history_blocklist": ["ABC"]}}
    )
    assert out == []


def test_select_provider_order_history_blocklist_try_yf_only():
    out = source_a._select_provider_order_for_symbol(
        "ABC",
        {"routing": {"history_ticker_policy": "try_yf_only", "history_blocklist": ["ABC"]}},
    )
    assert out == ["yfinance"]


def test_history_from_payload_uses_observation_date():
    payload = {
        "history": [
            {"observation_date": "2026-02-13", "Close": 100.0, "Dividends": 0.0},
            {"observation_date": "2026-02-14", "Close": 101.0, "Dividends": 0.1},
        ]
    }
    history = source_a._history_from_payload(payload)
    assert len(history) == 2
    assert "Close" in history.columns


def test_validate_cache_payload_detects_mismatches():
    payload = {
        "symbol": "MSFT",
        "run_date": "2026-02-13",
        "rows": 3,
        "history": [{"Date": "2026-02-13"}],
    }
    issues = source_a._validate_cache_payload(payload, symbol="AAPL", run_date="2026-02-14")
    assert any("symbol_mismatch" in x for x in issues)
    assert any("run_date_mismatch" in x for x in issues)
    assert any("rows_mismatch" in x for x in issues)


def test_validate_cache_payload_no_issue_for_consistent_payload():
    payload = {
        "symbol": "AAPL",
        "run_date": "2026-02-14",
        "rows": 2,
        "history": [{"Date": "2026-02-13"}, {"Date": "2026-02-14"}],
    }
    issues = source_a._validate_cache_payload(payload, symbol="AAPL", run_date="2026-02-14")
    assert issues == []


def test_load_raw_from_minio_returns_none_when_config_incomplete():
    out = source_a._load_raw_from_minio({}, "AAPL", "2026-02-14")
    assert out is None


def test_download_with_provider_uses_alpha_vantage_first(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "x")

    def _alpha_ok(symbol, years_back, api_key, timeout_seconds=30):
        _ = (symbol, years_back, api_key, timeout_seconds)
        idx = pd.to_datetime(["2026-02-13", "2026-02-14"])
        history = pd.DataFrame({"Close": [100.0, 101.0], "Dividends": [0.0, 0.1]}, index=idx)
        return None, history

    monkeypatch.setattr(source_a, "_download_price_history_alpha_vantage", _alpha_ok)

    source, ticker, history = source_a._download_with_provider(
        "AAPL",
        1,
        {"source_a": {"primary_source": "alpha_vantage", "enable_yfinance_fallback": True}},
    )
    assert source == "alpha_vantage"
    assert ticker is None
    assert len(history) == 2
