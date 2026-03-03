from __future__ import annotations

import importlib
import sys
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


def test_article_dedupe_key_prefers_article_id_then_url_then_source_title_date():
    a = {
        "article_id": "X123",
        "url": "https://x.com/a",
        "source": "Reuters",
        "title": "T",
        "time_published": "20260210T101010",
    }
    assert source_b._article_dedupe_key(a).startswith("article_id:")

    b = {
        "article_id": "",
        "url": "https://x.com/a",
        "source": "Reuters",
        "title": "T",
        "time_published": "20260210T101010",
    }
    assert source_b._article_dedupe_key(b).startswith("url:")

    c = {
        "article_id": "",
        "url": "",
        "source": "Reuters",
        "title": "T",
        "time_published": "20260210T101010",
    }
    assert source_b._article_dedupe_key(c).startswith("src_title_date:")


def test_merge_month_articles_incoming_overwrites_existing_on_same_key():
    existing = [
        {"url": "https://x.com/1", "title": "Old", "summary": "old"},
        {"url": "https://x.com/2", "title": "Keep", "summary": "keep"},
    ]
    incoming = [
        {"url": "https://x.com/1", "title": "New", "summary": "new"},
    ]
    merged = source_b._merge_month_articles(existing, incoming)
    by_url = {row["url"]: row for row in merged}
    assert len(merged) == 2
    assert by_url["https://x.com/1"]["title"] == "New"
    assert by_url["https://x.com/2"]["title"] == "Keep"


def test_missing_timestamp_articles_do_not_collapse_to_fetch_end(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "month_start": "2026-02-01",
            "month_end": "2026-02-28",
            "fetch_start": "2026-02-10",
            "fetch_end": "2026-02-14",
            "feed": [
                {"title": "No ts 1", "summary": "s", "time_published": ""},
                {"title": "No ts 2", "summary": "s", "time_published": ""},
                {"title": "Has ts", "summary": "s", "time_published": "20260212T120000"},
            ],
        }
    ]
    out = source_b.transform_source_b_features(raw_payloads, ["AAPL"], "2026-02-14", "daily")
    by_factor = {}
    for row in out:
        by_factor.setdefault(row["factor_name"], []).append(row)

    cnt_rows = by_factor["news_article_count_daily"]
    cnt_by_date = {r["observation_date"]: r["factor_value"] for r in cnt_rows}
    assert cnt_by_date["2026-02-10"] == 2.0
    assert cnt_by_date["2026-02-12"] == 1.0
    # Key guard: missing-time rows must not be squeezed into fetch_end/run_date.
    assert "2026-02-14" not in cnt_by_date


def test_merge_is_idempotent_for_repeated_same_input():
    article = {
        "article_id": "id-1",
        "url": "https://x.com/1",
        "source": "Reuters",
        "title": "A",
        "time_published": "20260213T101010",
    }
    merged_once = source_b._merge_month_articles([], [article])
    merged_twice = source_b._merge_month_articles(merged_once, [article])
    assert len(merged_once) == 1
    assert len(merged_twice) == 1

    payload = [
        {
            "symbol": "AAPL",
            "fetch_start": "2026-02-13",
            "feed": merged_twice,
        }
    ]
    out = source_b.transform_source_b_features(payload, ["AAPL"], "2026-02-14", "daily")
    count_rows = [r for r in out if r["factor_name"] == "news_article_count_daily"]
    assert len(count_rows) == 1
    assert count_rows[0]["factor_value"] == 1.0


def test_month_incremental_merge_builds_complete_coverage_with_dedup():
    first_run = [
        {
            "url": f"https://x.com/{d}",
            "title": f"d{d}",
            "source": "Reuters",
            "time_published": f"202602{d:02d}T090000",
        }
        for d in range(1, 14)
    ]
    # Simulate second incremental window with overlap from buffer (12-13) plus new (14-15).
    second_run = [
        {
            "url": f"https://x.com/{d}",
            "title": f"d{d}",
            "source": "Reuters",
            "time_published": f"202602{d:02d}T090000",
        }
        for d in range(12, 16)
    ]

    merged = source_b._merge_month_articles(first_run, second_run)
    assert len(merged) == 15
    got_days = sorted(int(str(r["time_published"])[6:8]) for r in merged)
    assert got_days == list(range(1, 16))


def test_monthly_current_helpers_no_minio_config_are_noop():
    key = source_b._monthly_current_object_path("AAPL", date(2026, 2, 1))
    assert "raw/source_b/news_current/" in key
    loaded = source_b._load_current_month_articles(
        config={}, symbol="AAPL", month_start=date(2026, 2, 1)
    )
    assert loaded == []
    source_b._save_current_month_articles(
        config={},
        symbol="AAPL",
        month_start=date(2026, 2, 1),
        articles=[{"url": "https://x.com/1"}],
    )


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
        source_b,
        "_month_windows",
        lambda run_date, backfill_years: [(date(2026, 2, 1), date(2026, 2, 14))],
    )
    monkeypatch.setattr(
        source_b,
        "_fetch_news_for_range",
        lambda symbol, api_key, time_from, time_to: {
            "feed": [{"title": "good", "summary": "profit"}]
        },
    )
    monkeypatch.setattr(source_b, "_load_month_cursor_closed", lambda *args, **kwargs: False)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_load_current_month_articles", lambda *args, **kwargs: [])
    monkeypatch.setattr(source_b, "_save_current_month_articles", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)
    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-14", 1, "daily", config={})
    assert len(out) == 1
    assert out[0]["symbol"] == "AAPL"
    assert out[0]["month_start"] == "2026-02-01"
    assert out[0]["month_end"] == "2026-02-28"
    assert out[0]["fetch_start"] == "2026-02-01"
    assert out[0]["fetch_end"] == "2026-02-14"


def test_ingest_source_b_raw_incremental_range_uses_buffer(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(
        source_b,
        "_month_windows",
        lambda run_date, backfill_years: [(date(2026, 2, 1), date(2026, 2, 15))],
    )
    monkeypatch.setattr(source_b, "SOURCE_B_INCREMENTAL_BUFFER_DAYS", 3)
    monkeypatch.setattr(source_b, "_load_month_cursor_closed", lambda *args, **kwargs: False)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: date(2026, 2, 13))

    captured = {}

    def _fake_fetch(symbol, api_key, time_from, time_to):
        captured["time_from"] = time_from
        captured["time_to"] = time_to
        return {"feed": []}

    monkeypatch.setattr(source_b, "_fetch_news_for_range", _fake_fetch)
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_load_current_month_articles", lambda *args, **kwargs: [])
    monkeypatch.setattr(source_b, "_save_current_month_articles", lambda *args, **kwargs: None)
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
    monkeypatch.setattr(source_b, "_load_month_cursor_closed", lambda *args, **kwargs: False)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: date(2026, 2, 11))

    called = {"fetch": 0}

    def _fake_fetch(symbol, api_key, time_from, time_to):  # noqa: ARG001
        called["fetch"] += 1
        return {"feed": []}

    monkeypatch.setattr(source_b, "_fetch_news_for_range", _fake_fetch)
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_load_current_month_articles", lambda *args, **kwargs: [])
    monkeypatch.setattr(source_b, "_save_current_month_articles", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)

    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-10", 1, "daily", config={})
    assert out == []
    assert called["fetch"] == 0


def test_ingest_source_b_raw_skips_closed_month(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(
        source_b,
        "_month_windows",
        lambda run_date, backfill_years: [(date(2026, 1, 1), date(2026, 1, 31))],
    )
    monkeypatch.setattr(source_b, "_load_month_cursor_closed", lambda *args, **kwargs: True)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: date(2026, 1, 31))
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_load_current_month_articles", lambda *args, **kwargs: [])
    monkeypatch.setattr(source_b, "_save_current_month_articles", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)

    called = {"fetch": 0}

    def _fake_fetch(symbol, api_key, time_from, time_to):  # noqa: ARG001
        called["fetch"] += 1
        return {"feed": []}

    monkeypatch.setattr(source_b, "_fetch_news_for_range", _fake_fetch)

    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-14", 1, "daily", config={})
    assert out == []
    assert called["fetch"] == 0


def test_ingest_source_b_raw_marks_cursor_closed_at_month_end(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(
        source_b,
        "_month_windows",
        lambda run_date, backfill_years: [(date(2026, 1, 1), date(2026, 1, 31))],
    )
    monkeypatch.setattr(source_b, "_load_month_cursor_closed", lambda *args, **kwargs: False)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: date(2026, 1, 29))
    monkeypatch.setattr(source_b, "_load_current_month_articles", lambda *args, **kwargs: [])
    monkeypatch.setattr(source_b, "_save_current_month_articles", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(source_b, "_fetch_news_for_range", lambda *args, **kwargs: {"feed": []})

    captured = {}

    def _fake_save_cursor(config, symbol, month_start, last_ingested_date, **kwargs):
        captured["symbol"] = symbol
        captured["month_start"] = month_start
        captured["last_ingested_date"] = last_ingested_date
        captured["is_closed"] = kwargs.get("is_closed")

    monkeypatch.setattr(source_b, "_save_month_cursor", _fake_save_cursor)

    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-14", 1, "daily", config={})
    assert len(out) == 1
    assert captured["symbol"] == "AAPL"
    assert captured["month_start"] == date(2026, 1, 1)
    assert captured["last_ingested_date"] == date(2026, 1, 31)
    assert captured["is_closed"] is True


def test_ingest_source_b_raw_first_backfill_month_clamped_to_backfill_start(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(
        source_b,
        "_month_windows",
        lambda run_date, backfill_years: [(date(2025, 2, 1), date(2025, 2, 28))],
    )
    monkeypatch.setattr(source_b, "_load_month_cursor_closed", lambda *args, **kwargs: False)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_load_current_month_articles", lambda *args, **kwargs: [])
    monkeypatch.setattr(source_b, "_save_current_month_articles", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)

    captured = {}

    def _fake_fetch(symbol, api_key, time_from, time_to):  # noqa: ARG001
        captured["time_from"] = time_from
        captured["time_to"] = time_to
        return {"feed": []}

    monkeypatch.setattr(source_b, "_fetch_news_for_range", _fake_fetch)

    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-14", 1, "daily", config={})
    assert len(out) == 1
    assert captured["time_from"] == "20250214T0000"
    assert captured["time_to"] == "20250228T2359"


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
        [{"symbol": "", "fetch_start": "", "feed": []}],
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
            "month_start": "2026-02-01",
            "month_end": "2026-02-28",
            "fetch_start": "2026-02-10",
            "fetch_end": "2026-02-14",
            "feed": [
                {"title": "Strong profit", "summary": "Positive growth", "time_published": ""}
            ],
        }
    ]
    out = source_b.transform_source_b_features(raw_payloads, ["AAPL"], "2026-02-14", "daily")
    assert len(out) == 2
    assert all(r["observation_date"] == "2026-02-10" for r in out)
    assert all(r["timestamp_inferred"] == 1 for r in out)


def test_transform_source_b_features_strict_time_drops_missing_time(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "month_start": "2026-02-01",
            "month_end": "2026-02-28",
            "fetch_start": "2026-02-10",
            "fetch_end": "2026-02-14",
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


def test_resolve_source_b_strict_time_variants():
    assert source_b._resolve_source_b_strict_time({"source_b": {"strict_time": "true"}}) is True
    assert source_b._resolve_source_b_strict_time({"source_b": {"strict_time": "0"}}) is False
    assert source_b._resolve_source_b_strict_time({"source_b": {"strict_time": 1}}) is True


def test_ingest_source_b_raw_returns_empty_when_symbols_filtered_out(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(source_b, "_filter_symbols_for_source_b", lambda symbols, config: [])
    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-14", 1, "daily", config={})
    assert out == []


def test_ingest_source_b_raw_merges_with_current_month_view(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    monkeypatch.setattr(
        source_b,
        "_month_windows",
        lambda run_date, backfill_years: [(date(2026, 2, 1), date(2026, 2, 14))],
    )
    monkeypatch.setattr(source_b, "_load_month_cursor_closed", lambda *args, **kwargs: False)
    monkeypatch.setattr(source_b, "_load_month_cursor", lambda *args, **kwargs: date(2026, 2, 13))
    monkeypatch.setattr(source_b.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(
        source_b,
        "_fetch_news_for_range",
        lambda *args, **kwargs: {"feed": [{"url": "https://x.com/1", "title": "New"}]},
    )
    monkeypatch.setattr(
        source_b,
        "_load_current_month_articles",
        lambda *args, **kwargs: [
            {"url": "https://x.com/1", "title": "Old"},
            {"url": "https://x.com/2"},
        ],
    )
    monkeypatch.setattr(source_b, "_save_raw_to_minio", lambda *args, **kwargs: None)
    monkeypatch.setattr(source_b, "_save_month_cursor", lambda *args, **kwargs: None)

    captured = {}

    def _fake_save_current(config, symbol, month_start, articles):
        captured["symbol"] = symbol
        captured["month_start"] = month_start
        captured["articles"] = articles

    monkeypatch.setattr(source_b, "_save_current_month_articles", _fake_save_current)

    out = source_b.ingest_source_b_raw(["AAPL"], "2026-02-14", 1, "daily", config={})
    assert len(out) == 1
    assert captured["symbol"] == "AAPL"
    by_url = {row["url"]: row for row in captured["articles"]}
    assert len(captured["articles"]) == 2
    assert by_url["https://x.com/1"]["title"] == "New"


def test_fetch_news_for_range_retries_on_note_then_succeeds(monkeypatch):
    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = {"n": 0}
    sleeps = []

    def _fake_get(url, params, timeout):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp({"Note": "rate limit"})
        return _Resp({"feed": [{"title": "ok"}]})

    monkeypatch.setattr(source_b.requests, "get", _fake_get)
    monkeypatch.setattr(source_b, "ALPHA_VANTAGE_MAX_RETRIES", 1)
    monkeypatch.setattr(source_b, "ALPHA_VANTAGE_RETRY_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(source_b.time, "sleep", lambda v: sleeps.append(v))

    out = source_b._fetch_news_for_range(
        "AAPL",
        "k",
        time_from="20260201T0000",
        time_to="20260214T2359",
    )
    assert out["feed"][0]["title"] == "ok"
    assert calls["n"] == 2
    assert sleeps == [0.01]


def test_fetch_news_for_range_raises_information(monkeypatch):
    class _Resp:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"Information": "maintenance"}

    monkeypatch.setattr(source_b.requests, "get", lambda *args, **kwargs: _Resp())
    monkeypatch.setattr(source_b, "ALPHA_VANTAGE_MAX_RETRIES", 0)

    with pytest.raises(RuntimeError, match="maintenance"):
        source_b._fetch_news_for_range(
            "AAPL",
            "k",
            time_from="20260201T0000",
            time_to="20260214T2359",
        )


def test_fetch_news_for_range_invalid_url():
    original = source_b.ALPHA_VANTAGE_BASE_URL
    source_b.ALPHA_VANTAGE_BASE_URL = "http://evil.local/query"
    try:
        with pytest.raises(RuntimeError, match="Invalid Alpha Vantage base URL"):
            source_b._fetch_news_for_range(
                "AAPL",
                "k",
                time_from="20260201T0000",
                time_to="20260214T2359",
            )
    finally:
        source_b.ALPHA_VANTAGE_BASE_URL = original


def test_transform_source_b_features_legacy_month_end_fallback_and_empty_text(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "month_end": "2026-02-28",
            "feed": [{"title": "", "summary": "", "time_published": ""}],
        }
    ]
    out = source_b.transform_source_b_features(raw_payloads, ["AAPL"], "2026-02-14", "daily")
    assert len(out) == 1
    assert out[0]["factor_name"] == "news_article_count_daily"
    assert out[0]["observation_date"] == "2026-02-28"
    assert out[0]["timestamp_inferred"] == 1


def test_source_b_minio_paths_save_and_load_helpers(monkeypatch):
    storage = {}

    class _Obj:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

        def close(self):
            return None

        def release_conn(self):
            return None

    class _FakeMinio:
        def __init__(self, endpoint, access_key, secret_key, secure=False):  # noqa: ARG002
            pass

        def bucket_exists(self, bucket):
            return bucket in storage

        def make_bucket(self, bucket):
            storage.setdefault(bucket, {})

        def put_object(self, bucket, key, data, length, content_type):  # noqa: ARG002
            payload = data.read()
            assert len(payload) == length
            storage.setdefault(bucket, {})[key] = payload

        def get_object(self, bucket, key):
            return _Obj(storage[bucket][key])

    monkeypatch.setitem(sys.modules, "minio", type("M", (), {"Minio": _FakeMinio}))
    cfg = {
        "minio": {
            "endpoint": "localhost:9000",
            "access_key": "x",
            "secret_key": "y",
            "bucket": "csreport",
            "secure": False,
        }
    }
    symbol = "AAPL"
    month_start = date(2026, 2, 1)

    source_b._save_raw_to_minio(
        cfg,
        symbol=symbol,
        run_date="2026-02-14",
        month_end=month_start,
        articles=[{"article_id": "1", "title": "t"}],
    )
    raw_keys = list(storage["csreport"].keys())
    assert any(k.startswith("raw/source_b/news/run_date=2026-02-14/") for k in raw_keys)

    source_b._save_current_month_articles(
        cfg,
        symbol=symbol,
        month_start=month_start,
        articles=[{"article_id": "1", "title": "new"}],
    )
    loaded = source_b._load_current_month_articles(cfg, symbol=symbol, month_start=month_start)
    assert loaded[0]["article_id"] == "1"
    assert loaded[0]["title"] == "new"

    source_b._save_month_cursor(
        cfg,
        symbol=symbol,
        month_start=month_start,
        last_ingested_date=date(2026, 2, 14),
        is_closed=True,
    )
    assert source_b._load_month_cursor(cfg, symbol=symbol, month_start=month_start) == date(
        2026, 2, 14
    )
    assert source_b._load_month_cursor_closed(cfg, symbol=symbol, month_start=month_start) is True
