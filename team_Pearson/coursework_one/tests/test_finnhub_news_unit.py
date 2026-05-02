"""Unit tests for modules.extract.finnhub_news.

Tests cover:
- _is_english: language detection with langid mock
- _get_api_key: env var reading
- _is_duplicate: Redis-backed deduplication
- _normalize_article: field normalization, headline filter, language filter, dedup
- fetch_news_for_symbol: chunked fetching, error handling
- run_finnhub_extraction: no-key early exit, full flow
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from modules.extract.finnhub_news import (
    _get_api_key,
    _is_duplicate,
    _is_english,
    _normalize_article,
    fetch_news_for_symbol,
    run_finnhub_extraction,
)


# ---------------------------------------------------------------------------
# _is_english
# ---------------------------------------------------------------------------

class TestIsEnglish:
    def test_short_text_defaults_to_true(self):
        assert _is_english("Hi") is True

    def test_empty_string_returns_true(self):
        assert _is_english("") is True

    def test_english_text_returns_true(self):
        with patch("langid.classify", return_value=("en", 0.99)):
            result = _is_english("Apple reports record quarterly earnings")
            assert result is True

    def test_non_english_returns_false(self):
        with patch("langid.classify", return_value=("zh", 0.99)):
            result = _is_english("苹果公司报告创纪录的季度收益")
            assert result is False

    def test_langid_exception_returns_true(self):
        with patch("langid.classify", side_effect=Exception("langid error")):
            result = _is_english("Some article text here for testing")
            assert result is True


# ---------------------------------------------------------------------------
# _get_api_key
# ---------------------------------------------------------------------------

class TestGetApiKey:
    def test_returns_key_when_set(self):
        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test_key_abc"}):
            assert _get_api_key() == "test_key_abc"

    def test_returns_none_when_empty(self):
        with patch.dict("os.environ", {"FINNHUB_API_KEY": ""}):
            assert _get_api_key() is None

    def test_returns_none_when_not_set(self):
        import os
        env = {k: v for k, v in os.environ.items() if k != "FINNHUB_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            assert _get_api_key() is None

    def test_strips_whitespace(self):
        with patch.dict("os.environ", {"FINNHUB_API_KEY": "  mykey  "}):
            assert _get_api_key() == "mykey"


# ---------------------------------------------------------------------------
# _is_duplicate (Redis mocked)
# ---------------------------------------------------------------------------

class TestIsDuplicate:
    def test_returns_false_when_redis_unavailable(self):
        # _get_redis is a local import inside _is_duplicate — patch at the source
        with patch("modules.utils.resilience._get_redis", return_value=None):
            assert _is_duplicate("https://example.com/article") is False

    def test_new_url_returns_false_and_registers(self):
        mock_redis = MagicMock()
        mock_redis.sadd.return_value = 1  # 1 = newly added
        with patch("modules.utils.resilience._get_redis", return_value=mock_redis):
            result = _is_duplicate("https://reuters.com/new-article")
            assert result is False
            mock_redis.sadd.assert_called_once()

    def test_existing_url_returns_true(self):
        mock_redis = MagicMock()
        mock_redis.sadd.return_value = 0  # 0 = already existed
        with patch("modules.utils.resilience._get_redis", return_value=mock_redis):
            result = _is_duplicate("https://reuters.com/existing-article")
            assert result is True


# ---------------------------------------------------------------------------
# _normalize_article
# ---------------------------------------------------------------------------

class TestNormalizeArticle:
    def _make_item(self, **overrides):
        base = {
            "headline": "Apple reports record profits for the quarter",
            "summary": "Net income rose 15% year over year.",
            "url": "https://reuters.com/apple-profits",
            "datetime": 1704067200,  # 2024-01-01 00:00:00 UTC
            "source": "Reuters",
            "category": "company news",
        }
        base.update(overrides)
        return base

    def test_valid_article_normalized_correctly(self):
        with patch("modules.extract.finnhub_news._is_duplicate", return_value=False), \
             patch("modules.extract.finnhub_news._is_english", return_value=True):
            result = _normalize_article("AAPL", self._make_item())
        assert result is not None
        assert result["symbol"] == "AAPL"
        assert result["headline"] == "Apple reports record profits for the quarter"
        assert result["data_source"] == "finnhub"
        assert result["publish_date"] == date(2024, 1, 1)

    def test_short_headline_returns_none(self):
        item = self._make_item(headline="Hi")
        result = _normalize_article("AAPL", item)
        assert result is None

    def test_non_english_returns_none(self):
        with patch("modules.extract.finnhub_news._is_english", return_value=False):
            result = _normalize_article("AAPL", self._make_item())
        assert result is None

    def test_duplicate_url_returns_none(self):
        with patch("modules.extract.finnhub_news._is_english", return_value=True), \
             patch("modules.extract.finnhub_news._is_duplicate", return_value=True):
            result = _normalize_article("AAPL", self._make_item())
        assert result is None

    def test_missing_datetime_gives_none_publish_date(self):
        item = self._make_item()
        del item["datetime"]
        with patch("modules.extract.finnhub_news._is_duplicate", return_value=False), \
             patch("modules.extract.finnhub_news._is_english", return_value=True):
            result = _normalize_article("AAPL", item)
        assert result is not None
        assert result["publish_date"] is None

    def test_invalid_datetime_gives_none_publish_date(self):
        item = self._make_item(datetime="not-a-timestamp")
        with patch("modules.extract.finnhub_news._is_duplicate", return_value=False), \
             patch("modules.extract.finnhub_news._is_english", return_value=True):
            result = _normalize_article("AAPL", item)
        assert result is not None
        assert result["publish_date"] is None

    def test_empty_headline_returns_none(self):
        item = self._make_item(headline="")
        result = _normalize_article("AAPL", item)
        assert result is None

    def test_none_headline_returns_none(self):
        item = self._make_item(headline=None)
        result = _normalize_article("AAPL", item)
        assert result is None


# ---------------------------------------------------------------------------
# fetch_news_for_symbol
# ---------------------------------------------------------------------------

class TestFetchNewsForSymbol:
    def _make_raw_article(self):
        return {
            "headline": "Apple beats earnings estimates by wide margin",
            "summary": "iPhone sales drove the outperformance.",
            "url": "https://reuters.com/apple-earnings",
            "datetime": 1704067200,
            "source": "Reuters",
            "category": "company news",
        }

    def test_returns_articles_for_valid_symbol(self):
        # Use a 10-day range to guarantee a single chunk (CHUNK_DAYS=30)
        with patch("modules.extract.finnhub_news._fetch_company_news_raw",
                   return_value=[self._make_raw_article()]), \
             patch("modules.extract.finnhub_news._is_duplicate", return_value=False), \
             patch("modules.extract.finnhub_news._is_english", return_value=True):
            articles = fetch_news_for_symbol(
                "AAPL",
                from_date=date(2024, 1, 1),
                to_date=date(2024, 1, 10),
                api_key="test_key",
            )
        assert len(articles) == 1
        assert articles[0]["symbol"] == "AAPL"

    def test_handles_fetch_error_gracefully(self):
        with patch("modules.extract.finnhub_news._fetch_company_news_raw",
                   side_effect=Exception("API error")):
            articles = fetch_news_for_symbol(
                "AAPL",
                from_date=date(2024, 1, 1),
                to_date=date(2024, 1, 31),
                api_key="test_key",
            )
        assert articles == []

    def test_multiple_chunks_combined(self):
        """A 60-day range should produce 2 chunks of 30 days each."""
        raw = [self._make_raw_article()]
        call_count = []

        def fake_fetch(symbol, from_d, to_d, api_key):
            call_count.append(1)
            return raw

        with patch("modules.extract.finnhub_news._fetch_company_news_raw", side_effect=fake_fetch), \
             patch("modules.extract.finnhub_news._is_duplicate", return_value=False), \
             patch("modules.extract.finnhub_news._is_english", return_value=True):
            articles = fetch_news_for_symbol(
                "AAPL",
                from_date=date(2024, 1, 1),
                to_date=date(2024, 3, 1),
                api_key="test_key",
            )
        assert len(call_count) >= 2  # At least 2 chunks for a 60-day range

    def test_duplicate_articles_filtered(self):
        with patch("modules.extract.finnhub_news._fetch_company_news_raw",
                   return_value=[self._make_raw_article()]), \
             patch("modules.extract.finnhub_news._is_english", return_value=True), \
             patch("modules.extract.finnhub_news._is_duplicate", return_value=True):
            articles = fetch_news_for_symbol(
                "AAPL",
                from_date=date(2024, 1, 1),
                to_date=date(2024, 1, 31),
                api_key="test_key",
            )
        assert articles == []


# ---------------------------------------------------------------------------
# run_finnhub_extraction
# ---------------------------------------------------------------------------

class TestRunFinnhubExtraction:
    def test_returns_empty_when_no_api_key(self):
        with patch("modules.extract.finnhub_news._get_api_key", return_value=None):
            result = run_finnhub_extraction(["AAPL", "MSFT"])
        assert result == []

    def test_processes_all_symbols(self):
        fake_article = {
            "symbol": "AAPL",
            "publish_date": date(2024, 1, 5),
            "headline": "Apple earnings beat",
            "summary": "",
            "url": "https://reuters.com/x",
            "source": "reuters.com",
            "data_source": "finnhub",
            "category": "",
        }
        with patch("modules.extract.finnhub_news._get_api_key", return_value="key"), \
             patch("modules.extract.finnhub_news.fetch_news_for_symbol",
                   return_value=[fake_article]):
            result = run_finnhub_extraction(
                ["AAPL", "MSFT"],
                backfill_years=1,
                as_of=date(2024, 6, 1),
            )
        assert len(result) == 2  # 1 article × 2 symbols

    def test_backfill_years_capped_at_max(self):
        """backfill_years > 2 should be capped to _MAX_HISTORY_YEARS (2)."""
        captured_from_dates = []

        def fake_fetch(symbol, *, from_date, to_date, api_key):
            captured_from_dates.append(from_date)
            return []

        with patch("modules.extract.finnhub_news._get_api_key", return_value="key"), \
             patch("modules.extract.finnhub_news.fetch_news_for_symbol",
                   side_effect=fake_fetch):
            run_finnhub_extraction(["AAPL"], backfill_years=10, as_of=date(2024, 6, 1))

        # With max 2 years, from_date should be ≥ 2022-06-01
        assert captured_from_dates[0] >= date(2022, 1, 1)
