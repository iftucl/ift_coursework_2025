from __future__ import annotations

import importlib
from datetime import date

import pytest

source_b = importlib.import_module("modules.input.extract_source_b")


def test_minio_config_normalizes_endpoint(monkeypatch):
    monkeypatch.setenv("MINIO_ENDPOINT", "http://localhost:9000")
    cfg = source_b._minio_config({"minio": {"bucket": "csreport"}})
    assert cfg["endpoint"] == "localhost:9000"
    assert cfg["bucket"] == "csreport"
    assert cfg["secure"] is False


def test_month_windows_cover_backfill_and_incremental():
    windows = source_b._month_windows("2026-02-14", 1)
    assert windows[0] == (date(2025, 2, 1), date(2025, 2, 28))
    assert windows[-1] == (date(2026, 2, 1), date(2026, 2, 14))

    incremental = source_b._month_windows("2026-02-14", 0)
    assert incremental == [(date(2026, 2, 1), date(2026, 2, 14))]


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
    incoming = [{"url": "https://x.com/1", "title": "New", "summary": "new"}]
    merged = source_b._merge_month_articles(existing, incoming)
    by_url = {row["url"]: row for row in merged}
    assert len(merged) == 2
    assert by_url["https://x.com/1"]["title"] == "New"
    assert by_url["https://x.com/2"]["title"] == "Keep"


def test_fetch_provider_articles_routes_av_before_cutoff(monkeypatch):
    """Windows before av_cutoff_date should use AV, not Finnhub."""
    monkeypatch.setattr(
        source_b,
        "_fetch_av_articles",
        lambda symbol, fetch_start, fetch_end, config=None: [  # noqa: ARG005
            {
                "url": "https://x.com/av1",
                "title": "AV article",
                "summary": "Strong profit",
                "time_published": "20260210T090000",
                "source": "Reuters",
                "data_source": "alpha_vantage",
            }
        ],
    )
    monkeypatch.setattr(
        source_b,
        "_fetch_finnhub_articles",
        lambda symbol, fetch_start, fetch_end: [  # noqa: ARG005
            {
                "url": "https://x.com/fh1",
                "title": "Finnhub article",
                "summary": "Weak loss",
                "time_published": "20260210T090000",
                "source": "Bloomberg",
                "data_source": "finnhub",
            }
        ],
    )
    # cutoff = 2026-03-05, window ends before cutoff → AV only
    monkeypatch.setattr(
        source_b,
        "_resolve_av_cutoff_date",
        lambda config=None: date(2026, 3, 5),
    )
    monkeypatch.setattr(source_b, "_resolve_alpha_key", lambda config=None: "test-key")

    out = source_b._fetch_provider_articles(
        "AAPL",
        fetch_start=date(2026, 2, 10),
        fetch_end=date(2026, 2, 28),
    )
    urls = [row["url"] for row in out]
    assert urls == ["https://x.com/av1"]


def test_missing_timestamp_articles_use_fetch_start_not_fetch_end(monkeypatch):
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
    cnt_rows = [r for r in out if r["factor_name"] == "news_article_count_daily"]
    cnt_by_date = {r["observation_date"]: r["factor_value"] for r in cnt_rows}
    assert cnt_by_date["2026-02-10"] == 2.0
    assert cnt_by_date["2026-02-12"] == 1.0
    assert "2026-02-14" not in cnt_by_date
    assert {r["publish_date"] for r in cnt_rows} == {"2026-02-10", "2026-02-12"}


def test_strict_time_drops_missing_timestamp_rows(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "fetch_start": "2026-02-10",
            "feed": [
                {"title": "No ts", "summary": "s", "time_published": ""},
                {"title": "Has ts", "summary": "s", "time_published": "20260212T120000"},
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
    cnt_rows = [r for r in out if r["factor_name"] == "news_article_count_daily"]
    assert cnt_rows == [
        {
            "symbol": "AAPL",
            "observation_date": "2026-02-12",
            "factor_name": "news_article_count_daily",
            "factor_value": 1.0,
            "source": "av+finnhub",
            "metric_frequency": "daily",
            "source_report_date": "2026-02-12",
            "publish_date": "2026-02-12",
            "timestamp_inferred": 0,
        }
    ]


def test_strict_time_accepts_provider_publish_date_when_timestamp_missing(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "fetch_start": "2026-02-10",
            "feed": [
                {
                    "title": "Provider date only",
                    "summary": "s",
                    "time_published": "",
                    "publish_date": "2026-02-11",
                },
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
    cnt_rows = [r for r in out if r["factor_name"] == "news_article_count_daily"]
    assert cnt_rows[0]["observation_date"] == "2026-02-11"
    assert cnt_rows[0]["publish_date"] == "2026-02-11"


def test_normalize_article_adds_schema_and_provider_version_metadata():
    article = source_b._normalize_article(
        {
            "headline": "Provider event",
            "summary": "Analyst downgrade after earnings miss.",
            "publish_date": "2026-02-12",
            "url": "https://example.com/aapl1",
            "topics": "earnings",
            "ticker_sentiment": [{"ticker": "AAPL"}],
        },
        fallback_symbol="AAPL",
    )
    assert article is not None
    assert article["publish_date"] == "2026-02-12"
    assert article["time_published"] == "20260212T000000"
    assert article["time_precision"] == "date"
    assert article["normalized_schema_version"] == "v2"
    assert article["provider_payload_version"] == "news_sentiment_v1"
    assert article["schema_validation_status"] == "warning"
    assert "topics_scalar_coerced" in article["schema_validation_errors"]


def test_transform_source_b_features_emits_event_proxy_counts(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payloads = [
        {
            "symbol": "AAPL",
            "fetch_start": "2026-02-10",
            "feed": [
                {
                    "title": "Apple downgraded after weak guidance",
                    "summary": "Analysts downgrade shares after earnings miss and guidance cut.",
                    "time_published": "20260212T120000",
                },
                {
                    "title": "Apple beats earnings estimates",
                    "summary": "Broker upgrades the stock after strong quarter.",
                    "time_published": "20260212T140000",
                },
            ],
        }
    ]
    out = source_b.transform_source_b_features(raw_payloads, ["AAPL"], "2026-02-14", "daily")
    by_factor = {row["factor_name"]: row for row in out if row["observation_date"] == "2026-02-12"}
    assert by_factor["earnings_news_count_daily"]["factor_value"] == 2.0
    assert by_factor["earnings_negative_news_count_daily"]["factor_value"] == 1.0
    assert by_factor["rating_downgrade_count_daily"]["factor_value"] == 1.0
    assert by_factor["rating_upgrade_count_daily"]["factor_value"] == 1.0


def test_build_source_b_kafka_payloads_returns_article_and_proxy_events(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    raw_payload = {
        "symbol": "AAPL",
        "fetch_start": "2026-02-10",
        "feed": [
            {
                "title": "Apple downgraded after weak guidance",
                "summary": "Analysts downgrade shares after earnings miss.",
                "time_published": "20260212T120000",
                "url": "https://example.com/aapl1",
                "data_source": "alpha_vantage",
            }
        ],
    }
    records = source_b.transform_source_b_features([raw_payload], ["AAPL"], "2026-02-14", "daily")

    payloads = source_b.build_source_b_kafka_payloads(
        raw_payload=raw_payload,
        records=records,
        run_id="run-1",
        run_date="2026-02-14",
    )

    assert len(payloads["news_structured"]) == 1
    article = payloads["news_structured"][0]
    assert article["symbol"] == "AAPL"
    assert article["earnings_negative"] is True
    assert article["rating_downgrade"] is True
    assert article["normalized_schema_version"] == "v2"
    assert article["provider_payload_version"] == "news_sentiment_v1"
    assert article["publish_date"] == "2026-02-12"

    proxy_names = {row["factor_name"] for row in payloads["event_proxies"]}
    assert "news_sentiment_daily" in proxy_names
    assert "earnings_negative_news_count_daily" in proxy_names
    assert all(row["publish_date"] for row in payloads["event_proxies"])


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


def test_extract_source_b_window_test_mode(monkeypatch):
    monkeypatch.setenv("CW1_TEST_MODE", "1")
    result = source_b.extract_source_b_window(
        symbol="AAPL",
        run_date="2026-02-14",
        month_start=date(2026, 2, 1),
        fetch_end=date(2026, 2, 14),
        backfill_years=1,
        frequency="daily",
        config={},
    )
    assert result["article_count"] == 0
    assert {row["factor_name"] for row in result["records"]} == {
        "news_sentiment_daily",
        "news_article_count_daily",
    }


def test_ingest_symbol_month_replays_closed_history_from_current_articles(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    saved_current = []
    saved_cursor = []

    monkeypatch.setattr(source_b, "_resolve_av_cutoff_date", lambda config=None: date(2026, 3, 1))
    monkeypatch.setattr(
        source_b,
        "_load_current_month_articles",
        lambda config, symbol, month_start: [  # noqa: ARG005
            {
                "title": "Historical current view",
                "summary": "Strong profit growth.",
                "time_published": "20260212T120000",
                "url": "https://example.com/current-aapl",
                "data_source": "alpha_vantage",
            }
        ],
    )
    monkeypatch.setattr(
        source_b,
        "_load_latest_raw_month_articles",
        lambda config, symbol, month_start: [],  # noqa: ARG005
    )
    monkeypatch.setattr(
        source_b,
        "_load_month_cursor_closed",
        lambda config, symbol, month_start: True,  # noqa: ARG005
    )
    monkeypatch.setattr(
        source_b,
        "_fetch_provider_articles",
        lambda *args, **kwargs: pytest.fail("provider fetch should not run for replayed history"),
    )
    monkeypatch.setattr(
        source_b,
        "_save_current_month_articles",
        lambda config, symbol, month_start, articles: saved_current.append(
            list(articles)
        ),  # noqa: ARG005
    )
    monkeypatch.setattr(
        source_b,
        "_save_month_cursor",
        lambda config, symbol, month_start, last_ingested_date, *, is_closed=False: saved_cursor.append(  # noqa: ARG005
            {
                "symbol": symbol,
                "month_start": month_start,
                "last_ingested_date": last_ingested_date,
                "is_closed": is_closed,
            }
        ),
    )

    payload = source_b._ingest_symbol_month(
        symbol="AAPL",
        run_date="2026-04-15",
        month_start=date(2026, 2, 1),
        fetch_end=date(2026, 2, 28),
        backfill_start_date=date(2021, 4, 15),
        config={},
    )

    assert payload is not None
    assert payload["ingestion_mode"] == "archive_replay"
    assert len(payload["feed"]) == 1
    assert saved_current and saved_current[0][0]["url"] == "https://example.com/current-aapl"
    assert saved_cursor and saved_cursor[0]["is_closed"] is True


def test_ingest_symbol_month_replays_history_from_raw_archive_when_current_missing(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)

    monkeypatch.setattr(source_b, "_resolve_av_cutoff_date", lambda config=None: date(2026, 3, 1))
    monkeypatch.setattr(
        source_b,
        "_load_current_month_articles",
        lambda config, symbol, month_start: [],  # noqa: ARG005
    )
    monkeypatch.setattr(
        source_b,
        "_load_latest_raw_month_articles",
        lambda config, symbol, month_start: [  # noqa: ARG005
            {
                "title": "Historical raw replay",
                "summary": "Analysts stay constructive.",
                "time_published": "20260218T080000",
                "url": "https://example.com/raw-aapl",
                "data_source": "alpha_vantage",
            }
        ],
    )
    monkeypatch.setattr(
        source_b,
        "_load_month_cursor_closed",
        lambda config, symbol, month_start: False,  # noqa: ARG005
    )
    monkeypatch.setattr(
        source_b,
        "_fetch_provider_articles",
        lambda *args, **kwargs: pytest.fail(
            "provider fetch should not run when archived raw exists"
        ),
    )

    payload = source_b._ingest_symbol_month(
        symbol="AAPL",
        run_date="2026-04-15",
        month_start=date(2026, 2, 1),
        fetch_end=date(2026, 2, 28),
        backfill_start_date=date(2021, 4, 15),
        config={},
    )

    assert payload is not None
    assert payload["ingestion_mode"] == "archive_replay"
    assert payload["feed"][0]["url"] == "https://example.com/raw-aapl"


def test_source_b_supporting_objects_exist_accepts_archived_raw_for_closed_history(monkeypatch):
    monkeypatch.setattr(source_b, "_resolve_av_cutoff_date", lambda config=None: date(2026, 3, 1))
    monkeypatch.setattr(
        source_b,
        "_build_raw_archive_index",
        lambda config=None: {
            (
                "2026",
                "02",
                "AAPL",
            ): "raw/source_b/news/run_date=2026-03-05/year=2026/month=02/symbol=AAPL.jsonl"
        },
    )
    monkeypatch.setattr(
        source_b,
        "_build_minio_client",
        lambda cfg: pytest.fail(
            "historical raw support check should not stat current/cursor objects"
        ),
    )

    out = source_b._source_b_supporting_objects_exist(
        {
            "minio": {
                "endpoint": "localhost:9000",
                "access_key": "a",
                "secret_key": "b",
                "bucket": "csreport",
            }
        },
        symbol="AAPL",
        run_date="2026-04-15",
        month_start=date(2026, 2, 1),
    )

    assert out is True


def test_source_b_supporting_objects_exist_requires_incremental_objects_after_cutoff(monkeypatch):
    class _Client:
        def __init__(self):
            self.seen = []

        def stat_object(self, bucket, key):
            self.seen.append((bucket, key))
            raise FileNotFoundError(key)

    client = _Client()
    monkeypatch.setattr(source_b, "_resolve_av_cutoff_date", lambda config=None: date(2026, 3, 1))
    monkeypatch.setattr(source_b, "_build_minio_client", lambda cfg: client)

    out = source_b._source_b_supporting_objects_exist(
        {
            "minio": {
                "endpoint": "localhost:9000",
                "access_key": "a",
                "secret_key": "b",
                "bucket": "csreport",
            }
        },
        symbol="AAPL",
        run_date="2026-04-15",
        month_start=date(2026, 3, 1),
    )

    assert out is False
    assert client.seen[0][1].endswith("run_date=2026-04-15/year=2026/month=03/symbol=AAPL.jsonl")


def test_ingest_symbol_month_uses_provider_fetch_after_cutoff(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)

    monkeypatch.setattr(source_b, "_resolve_av_cutoff_date", lambda config=None: date(2026, 3, 1))
    monkeypatch.setattr(
        source_b,
        "_load_current_month_articles",
        lambda config, symbol, month_start: [  # noqa: ARG005
            {
                "title": "Should not replay March",
                "summary": "Old cached article.",
                "time_published": "20260305T080000",
                "url": "https://example.com/current-march",
                "data_source": "finnhub",
            }
        ],
    )
    monkeypatch.setattr(
        source_b,
        "_load_latest_raw_month_articles",
        lambda config, symbol, month_start: [  # noqa: ARG005
            {
                "title": "Old raw article",
                "summary": "Old raw article.",
                "time_published": "20260302T080000",
                "url": "https://example.com/raw-march",
                "data_source": "alpha_vantage",
            }
        ],
    )
    monkeypatch.setattr(
        source_b,
        "_load_month_cursor_closed",
        lambda config, symbol, month_start: False,  # noqa: ARG005
    )
    monkeypatch.setattr(
        source_b,
        "_load_month_cursor",
        lambda config, symbol, month_start: None,  # noqa: ARG005
    )
    monkeypatch.setattr(
        source_b,
        "_fetch_provider_articles",
        lambda symbol, *, fetch_start, fetch_end, config=None: [  # noqa: ARG005
            {
                "title": "Fresh March provider fetch",
                "summary": "Incremental free-tier article.",
                "time_published": "20260310T080000",
                "url": "https://example.com/provider-march",
                "data_source": "finnhub",
            }
        ],
    )

    payload = source_b._ingest_symbol_month(
        symbol="AAPL",
        run_date="2026-04-15",
        month_start=date(2026, 3, 1),
        fetch_end=date(2026, 3, 31),
        backfill_start_date=date(2021, 4, 15),
        config={},
    )

    assert payload is not None
    assert payload["ingestion_mode"] == "provider_fetch"
    assert payload["feed"][0]["url"] == "https://example.com/provider-march"
