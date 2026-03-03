from __future__ import annotations

import importlib
from datetime import date

import pytest

source_b = importlib.import_module("modules.input.extract_source_b")


def test_resolve_alpha_key_reads_env(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "abc123")
    assert source_b._resolve_alpha_key({}) == "abc123"


def test_resolve_alpha_key_ignores_placeholders(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    out = source_b._resolve_alpha_key({"api": {"alpha_vantage_key": "YOUR_KEY"}})
    assert out == ""


def test_resolve_alpha_key_reads_legacy_conf_field(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    out = source_b._resolve_alpha_key({"alpha_vantage": {"api_key": "abc123"}})
    assert out == "abc123"


def test_minio_config_normalizes_endpoint(monkeypatch):
    monkeypatch.setenv("MINIO_ENDPOINT", "http://localhost:9000")
    cfg = source_b._minio_config({"minio": {"bucket": "csreport"}})
    assert cfg["endpoint"] == "localhost:9000"
    assert cfg["bucket"] == "csreport"
    assert cfg["secure"] is False


def test_month_helpers():
    months = source_b._month_end_dates("2026-02-14", 1)
    assert len(months) == 12
    assert months[0] == date(2025, 2, 28)
    assert months[-1] == date(2026, 1, 31)
    assert months[-1] <= date(2026, 2, 14)
    months_inc = source_b._month_end_dates("2026-02-14", 0)
    assert months_inc == [date(2026, 2, 14)]
    start, end = source_b._month_time_range(date(2026, 2, 28))
    assert start == "20260201T0000"
    assert end == "20260228T2359"
    key = source_b._raw_object_path("AAPL", "2026-02-14", date(2026, 2, 28))
    assert "run_date=2026-02-14" in key and "month=02" in key and "symbol=AAPL.jsonl" in key


def test_dedupe_articles_prefers_url_fallback_title_ts():
    feed = [
        {
            "url": "https://a.com/1",
            "title": "A",
            "summary": "x",
            "time_published": "20260201T010101",
        },
        {
            "url": "https://a.com/1",
            "title": "A dup",
            "summary": "x",
            "time_published": "20260201T010102",
        },
        {"url": "", "title": "No URL", "summary": "x", "time_published": "20260201T020000"},
        {"url": "", "title": "No URL", "summary": "x2", "time_published": "20260201T020000"},
    ]
    out = source_b._dedupe_articles(feed)
    assert len(out) == 2


def test_score_text_fallback_branch(monkeypatch):
    monkeypatch.setattr(source_b, "_LM_ANALYZER", False)
    score = source_b._score_text("strong profit growth but also risk")
    assert isinstance(score, float)


def test_score_text_lm_branch(monkeypatch):
    class FakeLM:
        @staticmethod
        def tokenize(text):  # noqa: ARG004
            return ["x"]

        @staticmethod
        def get_score(tokens):  # noqa: ARG004
            return {"Positive": 3, "Negative": 1}

    monkeypatch.setattr(source_b, "_LM_ANALYZER", FakeLM())
    score = source_b._score_text("any text")
    assert score > 0


def test_compute_sentiment_scores_from_text(monkeypatch):
    monkeypatch.setattr(source_b, "_LM_ANALYZER", False)
    feed = [
        {"title": "Strong profit growth", "summary": "Positive outlook and upgrade"},
        {"title": "Weak quarter and loss", "summary": "Negative risk remains"},
        {"title": "", "summary": ""},
    ]
    scores = source_b.compute_sentiment_scores(feed)
    assert len(scores) == 2
    assert scores[0] > scores[1]


def test_fetch_news_for_month_success(monkeypatch):
    class FakeResp:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"feed": [{"title": "ok", "summary": "ok"}]}

    def fake_get(url, params, timeout):  # noqa: ARG001
        assert params["function"] == "NEWS_SENTIMENT"
        return FakeResp()

    monkeypatch.setattr(source_b.requests, "get", fake_get)
    payload = source_b._fetch_news_for_month("AAPL", date(2026, 2, 28), "k")
    assert "feed" in payload


def test_fetch_news_for_month_invalid_url(monkeypatch):
    monkeypatch.setattr(source_b, "ALPHA_VANTAGE_BASE_URL", "http://evil.local/query")
    with pytest.raises(RuntimeError):
        source_b._fetch_news_for_month("AAPL", date(2026, 2, 28), "k")


def test_ingest_source_b_raw_returns_empty_without_key(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-14", 1, "daily", config={})
    assert out == []


def test_source_b_symbol_filter_default_skips_suffix():
    cfg = {"symbol_filter": {"skip_suffix_symbols": True, "symbol_regex_allow": r"^[A-Z0-9]+$"}}
    symbols = source_b._filter_symbols_for_source_b(["AAPL", "VOD.L", "AAPL"], config=cfg)
    assert symbols == ["AAPL"]


def test_source_b_symbol_filter_can_relax_rules():
    cfg = {"symbol_filter": {"skip_suffix_symbols": False, "symbol_regex_allow": r"^[A-Z0-9.]+$"}}
    symbols = source_b._filter_symbols_for_source_b(["AAPL", "VOD.L"], config=cfg)
    assert symbols == ["AAPL", "VOD.L"]


def test_ingest_source_b_raw_collects_payloads(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(
        source_b, "_month_windows", lambda run_date, backfill_years: [(date(2026, 2, 1), date(2026, 2, 14))]
    )
    monkeypatch.setattr(
        source_b,
        "_fetch_news_for_range",
        lambda symbol, api_key, time_from, time_to: {"feed": [{"title": "good", "summary": "profit"}]},
    )
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)
    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-14", 1, "daily", config={})
    assert len(out) == 1
    assert out[0]["symbol"] == "AAPL"
    assert out[0]["month_end"] == "2026-02-14"


def test_ingest_source_b_raw_incremental_range_uses_buffer(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(
        source_b,
        "_month_windows",
        lambda run_date, backfill_years: [(date(2026, 2, 1), date(2026, 2, 15))],
    )
    monkeypatch.setattr(source_b, "SOURCE_B_INCREMENTAL_BUFFER_DAYS", 3)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: date(2026, 2, 13))

    captured = {}

    def _fake_fetch(symbol, api_key, time_from, time_to):
        captured["time_from"] = time_from
        captured["time_to"] = time_to
        return {"feed": []}

    monkeypatch.setattr(source_b, "_fetch_news_for_range", _fake_fetch)
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)

    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-15", 1, "daily", config={})
    assert len(out) == 1
    assert captured["time_from"] == "20260210T0000"
    assert captured["time_to"] == "20260215T2359"


def test_ingest_source_b_raw_incremental_skips_when_cursor_ahead(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(
        source_b,
        "_month_windows",
        lambda run_date, backfill_years: [(date(2026, 2, 1), date(2026, 2, 10))],
    )
    monkeypatch.setattr(source_b, "SOURCE_B_INCREMENTAL_BUFFER_DAYS", 0)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: date(2026, 2, 11))

    called = {"fetch": 0}

    def _fake_fetch(symbol, api_key, time_from, time_to):  # noqa: ARG001
        called["fetch"] += 1
        return {"feed": []}

    monkeypatch.setattr(source_b, "_fetch_news_for_range", _fake_fetch)
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)

    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-10", 1, "daily", config={})
    assert out == []
    assert called["fetch"] == 0


def test_transform_source_b_features_monthly_record(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "month_end": "2026-02-28",
            "feed": [
                {
                    "title": "Strong profit",
                    "summary": "Positive growth",
                    "time_published": "20260215T120000",
                }
            ],
        }
    ]
    out = source_b.transform_source_b_features(raw_payloads, ["AAPL"], "2026-02-14", "daily")
    assert len(out) == 2
    names = {r["factor_name"] for r in out}
    assert {"news_sentiment_daily", "news_article_count_daily"} == names
    sent = [r for r in out if r["factor_name"] == "news_sentiment_daily"][0]
    cnt = [r for r in out if r["factor_name"] == "news_article_count_daily"][0]
    assert sent["symbol"] == "AAPL"
    assert sent["metric_frequency"] == "daily"
    assert sent["source_report_date"] == "2026-02-15"
    assert sent["observation_date"] == "2026-02-15"
    assert isinstance(sent["factor_value"], float)
    assert sent["timestamp_inferred"] == 0
    assert cnt["factor_value"] == 1.0
    assert cnt["timestamp_inferred"] == 0


def test_transform_source_b_features_skips_invalid_rows(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    out = source_b.transform_source_b_features(
        [{"symbol": "", "month_end": "", "feed": []}],
        ["AAPL"],
        "2026-02-14",
        "daily",
    )
    assert out == []


def test_extract_source_b_test_mode(monkeypatch):
    monkeypatch.setenv("CW1_TEST_MODE", "1")
    out = source_b.extract_source_b(["AAPL", "MSFT"], "2026-02-14", 1, "daily", config={})
    assert len(out) == 4
    assert all(r["source"] == "extractor_b" for r in out)
    names = {r["factor_name"] for r in out}
    assert {"news_sentiment_daily", "news_article_count_daily"} == names


def test_transform_source_b_features_missing_time_fallback_marks_inferred(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "month_end": "2026-02-28",
            "feed": [
                {"title": "Strong profit", "summary": "Positive growth", "time_published": ""}
            ],
        }
    ]
    out = source_b.transform_source_b_features(raw_payloads, ["AAPL"], "2026-02-14", "daily")
    assert len(out) == 2
    assert all(r["observation_date"] == "2026-02-28" for r in out)
    assert all(r["timestamp_inferred"] == 1 for r in out)


def test_transform_source_b_features_strict_time_drops_missing_time(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "month_end": "2026-02-28",
            "feed": [
                {"title": "Strong profit", "summary": "Positive growth", "time_published": ""}
            ],
        }
    ]
    out = source_b.transform_source_b_features(
        raw_payloads,
        ["AAPL"],
        "2026-02-14",
        "daily",
        config={"source_b": {"strict_time": True}},
    )
    assert out == []
