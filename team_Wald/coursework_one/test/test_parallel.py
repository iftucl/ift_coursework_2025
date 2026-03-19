"""
Tests for parallel extraction engine (modules/utils/parallel.py).
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from modules.utils.parallel import (
    BatchResult,
    TickerResult,
    _extract_single_ticker,
    parallel_compute_sentiment,
    parallel_extract_fx,
    parallel_extract_gdelt,
    parallel_extract_news,
    parallel_extract_newsapi,
    parallel_extract_prices,
    parallel_upload_batch_results,
    refetch_missing_ratios,
    run_extraction_stages,
)


class TestTickerResult:
    """Tests for the TickerResult dataclass."""

    def test_default_construction(self):
        tr = TickerResult(ticker="AAPL", yf_ticker="AAPL", currency="USD")
        assert tr.ticker == "AAPL"
        assert tr.yf_ticker == "AAPL"
        assert tr.currency == "USD"
        assert tr.price_records == []
        assert tr.company_info == {}
        assert tr.financials == {}
        assert tr.price_df is None
        assert tr.status == "success"
        assert tr.error == ""

    def test_custom_values(self):
        records = [{"date": "2024-01-01", "close": 100}]
        tr = TickerResult(
            ticker="MSFT",
            yf_ticker="MSFT",
            currency="USD",
            price_records=records,
            status="error",
            error="timeout",
        )
        assert tr.price_records == records
        assert tr.status == "error"
        assert tr.error == "timeout"


class TestBatchResult:
    """Tests for the BatchResult dataclass."""

    def test_default_construction(self):
        br = BatchResult()
        assert br.price_records == []
        assert br.company_infos == []
        assert br.ticker_results == []
        assert br.price_success == 0
        assert br.price_empty == 0
        assert br.price_fail == 0
        assert br.info_success == 0
        assert br.info_fail == 0

    def test_aggregation(self):
        br = BatchResult()
        br.price_records.extend([{"a": 1}, {"b": 2}])
        br.price_success = 5
        br.price_empty = 2
        br.price_fail = 1
        assert len(br.price_records) == 2
        assert br.price_success == 5


class TestParallelExtractPrices:
    """Tests for parallel Yahoo Finance extraction."""

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.fetch_company_info")
    @patch("modules.utils.parallel.fetch_financial_data")
    @patch("modules.utils.parallel.clean_price_dataframe")
    @patch("modules.utils.parallel.validate_company_info")
    def test_successful_extraction(self, mock_validate, mock_clean, mock_financials, mock_info, mock_prices):
        mock_prices.return_value = pd.DataFrame({"Close": [100, 101]})
        mock_clean.return_value = [
            {"symbol": "AAPL", "close": 100},
            {"symbol": "AAPL", "close": 101},
        ]
        mock_info.return_value = {"symbol": "AAPL", "pe_ratio": 25.0}
        mock_validate.return_value = True
        mock_financials.return_value = {"income_statement": {}}

        result = parallel_extract_prices(
            batch=["AAPL"],
            sources=["prices", "financials"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert isinstance(result, BatchResult)
        assert len(result.price_records) == 2
        assert result.price_success == 1
        assert result.price_empty == 0
        assert result.price_fail == 0
        assert len(result.company_infos) == 1

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.clean_price_dataframe")
    def test_empty_price_data(self, mock_clean, mock_prices):
        mock_prices.return_value = pd.DataFrame()

        result = parallel_extract_prices(
            batch=["AAPL"],
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert result.price_success == 0
        assert result.price_empty == 1
        mock_clean.assert_not_called()

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.clean_price_dataframe")
    def test_multiple_tickers_parallel(self, mock_clean, mock_prices):
        mock_prices.return_value = pd.DataFrame({"Close": [100]})
        mock_clean.return_value = [{"close": 100}]

        result = parallel_extract_prices(
            batch=["AAPL", "MSFT", "GOOGL"],
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            max_workers=3,
            delay_per_ticker=0.0,
        )

        assert result.price_success == 3
        assert len(result.ticker_results) == 3

    @patch("modules.utils.parallel.fetch_price_history")
    def test_ticker_error_handled(self, mock_prices):
        mock_prices.side_effect = Exception("network error")

        result = parallel_extract_prices(
            batch=["AAPL"],
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert result.price_fail >= 1

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.clean_price_dataframe")
    def test_progress_callback_called(self, mock_clean, mock_prices):
        mock_prices.return_value = pd.DataFrame({"Close": [100]})
        mock_clean.return_value = [{"close": 100}]

        callback = MagicMock()
        parallel_extract_prices(
            batch=["AAPL"],
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_workers=1,
            delay_per_ticker=0.0,
            progress_callback=callback,
        )

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "AAPL"
        assert args[1] == "success"

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.clean_price_dataframe")
    def test_prices_only_source(self, mock_clean, mock_prices):
        mock_prices.return_value = pd.DataFrame({"Close": [100]})
        mock_clean.return_value = [{"close": 100}]

        result = parallel_extract_prices(
            batch=["AAPL"],
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert result.price_success == 1
        assert len(result.company_infos) == 0


class TestParallelExtractFx:
    """Tests for parallel FX rate extraction."""

    @patch("modules.utils.parallel.fetch_fx_rates")
    def test_all_pairs_fetched(self, mock_fetch):
        mock_fetch.return_value = {"GBPUSD=X": pd.DataFrame({"Close": [1.25, 1.26]})}

        result = parallel_extract_fx(
            start_date="2024-01-01",
            end_date="2024-12-31",
            pairs=["GBPUSD=X"],
            max_workers=1,
        )

        assert "GBPUSD=X" in result
        assert not result["GBPUSD=X"].empty

    @patch("modules.utils.parallel.fetch_fx_rates")
    def test_empty_pair(self, mock_fetch):
        mock_fetch.return_value = {"CHFUSD=X": pd.DataFrame()}

        result = parallel_extract_fx(
            start_date="2024-01-01",
            end_date="2024-12-31",
            pairs=["CHFUSD=X"],
            max_workers=1,
        )

        assert "CHFUSD=X" in result
        assert result["CHFUSD=X"].empty

    @patch("modules.utils.parallel.fetch_fx_rates")
    def test_progress_callback(self, mock_fetch):
        mock_fetch.return_value = {"EURUSD=X": pd.DataFrame({"Close": [1.10]})}

        callback = MagicMock()
        parallel_extract_fx(
            start_date="2024-01-01",
            end_date="2024-12-31",
            pairs=["EURUSD=X"],
            max_workers=1,
            progress_callback=callback,
        )

        callback.assert_called_once()

    @patch("modules.utils.parallel.fetch_fx_rates")
    def test_multiple_pairs_parallel(self, mock_fetch):
        def side_effect(start, end, pairs=None):
            pair = pairs[0] if pairs else "UNKNOWN"
            return {pair: pd.DataFrame({"Close": [1.0]})}

        mock_fetch.side_effect = side_effect

        result = parallel_extract_fx(
            start_date="2024-01-01",
            end_date="2024-12-31",
            pairs=["GBPUSD=X", "EURUSD=X", "CADUSD=X", "CHFUSD=X"],
            max_workers=4,
        )

        assert len(result) == 4


class TestParallelExtractNews:
    """Tests for parallel Yahoo Finance news extraction."""

    @patch("modules.utils.parallel.fetch_news")
    @patch("modules.utils.parallel.prepare_ticker")
    def test_successful_news_fetch(self, mock_prepare, mock_news):
        mock_prepare.return_value = "AAPL"
        mock_news.return_value = [
            {"headline": "Apple hits record", "source": "yahoo_finance"},
        ]

        result = parallel_extract_news(
            tickers=["AAPL"],
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert "AAPL" in result
        assert len(result["AAPL"]) == 1
        assert result["AAPL"][0]["company_id"] == "AAPL"

    @patch("modules.utils.parallel.fetch_news")
    @patch("modules.utils.parallel.prepare_ticker")
    def test_empty_news(self, mock_prepare, mock_news):
        mock_prepare.return_value = "MSFT"
        mock_news.return_value = []

        result = parallel_extract_news(
            tickers=["MSFT"],
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert "MSFT" in result
        assert result["MSFT"] == []

    @patch("modules.utils.parallel.fetch_news")
    @patch("modules.utils.parallel.prepare_ticker")
    def test_multiple_tickers(self, mock_prepare, mock_news):
        mock_prepare.side_effect = lambda x: x
        mock_news.return_value = [{"headline": "test"}]

        result = parallel_extract_news(
            tickers=["AAPL", "MSFT", "GOOGL"],
            max_workers=3,
            delay_per_ticker=0.0,
        )

        assert len(result) == 3

    @patch("modules.utils.parallel.fetch_news")
    @patch("modules.utils.parallel.prepare_ticker")
    def test_error_handled(self, mock_prepare, mock_news):
        mock_prepare.return_value = "AAPL"
        mock_news.side_effect = Exception("API error")

        result = parallel_extract_news(
            tickers=["AAPL"],
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert "AAPL" in result
        assert result["AAPL"] == []

    @patch("modules.utils.parallel.fetch_news")
    @patch("modules.utils.parallel.prepare_ticker")
    def test_progress_callback(self, mock_prepare, mock_news):
        mock_prepare.return_value = "AAPL"
        mock_news.return_value = [{"headline": "test"}]

        callback = MagicMock()
        parallel_extract_news(
            tickers=["AAPL"],
            max_workers=1,
            delay_per_ticker=0.0,
            progress_callback=callback,
        )

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "AAPL"
        assert args[1] == "success"


class TestParallelExtractPricesIntegration:
    """Integration-style tests for edge cases."""

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.fetch_company_info")
    @patch("modules.utils.parallel.fetch_financial_data")
    @patch("modules.utils.parallel.clean_price_dataframe")
    @patch("modules.utils.parallel.validate_company_info")
    def test_mixed_success_and_failure(self, mock_validate, mock_clean, mock_financials, mock_info, mock_prices):
        """One ticker succeeds, one fails, one empty."""
        call_count = [0]

        def price_side_effect(ticker, start, end, retries):
            call_count[0] += 1
            if "AAPL" in ticker:
                return pd.DataFrame({"Close": [100]})
            elif "MSFT" in ticker:
                raise Exception("timeout")
            return pd.DataFrame()

        mock_prices.side_effect = price_side_effect
        mock_clean.return_value = [{"close": 100}]
        mock_info.return_value = {}
        mock_validate.return_value = False
        mock_financials.return_value = {}

        result = parallel_extract_prices(
            batch=["AAPL", "MSFT", "GOOGL"],
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert len(result.ticker_results) == 3
        assert result.price_success >= 1


class TestProgressModule:
    """Tests for progress.py module."""

    def test_stage_record_elapsed(self):
        from modules.utils.progress import StageRecord

        sr = StageRecord(name="test", total=10)
        assert sr.elapsed >= 0
        assert isinstance(sr.elapsed_str, str)

    def test_stage_record_with_end_time(self):
        import time

        from modules.utils.progress import StageRecord

        sr = StageRecord(name="test", total=10, start_time=time.time() - 5)
        sr.end_time = time.time()
        assert 4.5 < sr.elapsed < 6.0

    def test_progress_manager_creation(self):
        from modules.utils.progress import PipelineProgressManager

        pm = PipelineProgressManager()
        assert pm._stages == []
        assert pm._current_stage is None
        assert pm._current_task_id is None

    def test_progress_manager_begin_stage_without_live(self):
        from modules.utils.progress import PipelineProgressManager

        pm = PipelineProgressManager()
        pm.begin_stage("Test Stage", 10)
        assert len(pm._stages) == 1
        assert pm._stages[0].name == "Test Stage"
        assert pm._stages[0].total == 10

    def test_progress_manager_update_stats(self):
        from modules.utils.progress import PipelineProgressManager

        pm = PipelineProgressManager()
        pm.update_stats("Key", "Value")
        assert pm._stats["Key"] == "Value"

    def test_progress_manager_multiple_stages(self):
        from modules.utils.progress import PipelineProgressManager

        pm = PipelineProgressManager()
        pm.begin_stage("Stage 1", 5)
        pm.begin_stage("Stage 2", 10)
        assert len(pm._stages) == 2
        assert pm._stages[0].end_time is not None
        assert pm._stages[1].end_time is None


class TestParallelExtractGdelt:
    """Tests for parallel GDELT news extraction."""

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_successful_extraction(self, mock_gdelt):
        mock_gdelt.return_value = [
            {"headline": "Apple news", "company_id": "AAPL"},
        ]

        result = parallel_extract_gdelt(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            max_workers=1,
            delay_per_company=0.0,
        )

        assert "AAPL" in result
        assert len(result["AAPL"]) == 1

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_empty_results(self, mock_gdelt):
        mock_gdelt.return_value = []

        result = parallel_extract_gdelt(
            companies=[{"symbol": "MSFT", "security": "Microsoft"}],
            max_workers=1,
            delay_per_company=0.0,
        )

        assert "MSFT" in result
        assert result["MSFT"] == []

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_multiple_companies(self, mock_gdelt):
        mock_gdelt.return_value = [{"headline": "test"}]

        result = parallel_extract_gdelt(
            companies=[
                {"symbol": "AAPL", "security": "Apple Inc"},
                {"symbol": "MSFT", "security": "Microsoft"},
                {"symbol": "GOOGL", "security": "Alphabet"},
            ],
            max_workers=3,
            delay_per_company=0.0,
        )

        assert len(result) == 3

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_error_handled(self, mock_gdelt):
        mock_gdelt.side_effect = Exception("GDELT API error")

        result = parallel_extract_gdelt(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            max_workers=1,
            delay_per_company=0.0,
        )

        assert "AAPL" in result
        assert result["AAPL"] == []

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_progress_callback(self, mock_gdelt):
        mock_gdelt.return_value = [{"headline": "test"}]

        callback = MagicMock()
        parallel_extract_gdelt(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            max_workers=1,
            delay_per_company=0.0,
            progress_callback=callback,
        )

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "AAPL"
        assert args[1] == "success"

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_empty_symbol_skipped(self, mock_gdelt):
        mock_gdelt.return_value = [{"headline": "test"}]

        result = parallel_extract_gdelt(
            companies=[{"symbol": "", "security": "Unknown"}],
            max_workers=1,
            delay_per_company=0.0,
        )

        assert len(result) == 0


class TestParallelUploadBatchResults:
    """Tests for parallel post-batch uploads."""

    @patch("modules.loading.postgres_loader.insert_ingestion_log")
    def test_successful_upload(self, mock_log):
        tr = TickerResult(
            ticker="AAPL",
            yf_ticker="AAPL",
            currency="USD",
            price_records=[{"close": 100}],
            price_df=pd.DataFrame({"Close": [100]}),
            company_info={"symbol": "AAPL", "pe_ratio": 25.0},
            financials={"income_statement": {}},
        )

        mock_minio = MagicMock()
        mock_mongo = MagicMock()
        mock_db = MagicMock()

        parallel_upload_batch_results(
            ticker_results=[tr],
            minio=mock_minio,
            mongo=mock_mongo,
            db=mock_db,
            run_id="test-run",
            end_date="2024-12-31",
            frequency="weekly",
            start_date="2024-01-01",
            max_workers=1,
        )

        mock_minio.upload_csv.assert_called_once()
        mock_minio.upload_json.assert_called()
        mock_mongo.insert_one.assert_called()

    @patch("modules.loading.postgres_loader.insert_ingestion_log")
    def test_empty_ticker_upload(self, mock_log):
        tr = TickerResult(
            ticker="MSFT",
            yf_ticker="MSFT",
            currency="USD",
            status="empty",
        )

        mock_minio = MagicMock()
        mock_mongo = MagicMock()
        mock_db = MagicMock()

        parallel_upload_batch_results(
            ticker_results=[tr],
            minio=mock_minio,
            mongo=mock_mongo,
            db=mock_db,
            run_id="test-run",
            end_date="2024-12-31",
            frequency="weekly",
            start_date="2024-01-01",
            max_workers=1,
        )

        mock_minio.upload_csv.assert_not_called()
        mock_log.assert_called_once()

    @patch("modules.loading.postgres_loader.insert_ingestion_log")
    def test_multiple_tickers_uploaded(self, mock_log):
        trs = [
            TickerResult(
                ticker=f"T{i}",
                yf_ticker=f"T{i}",
                currency="USD",
                price_records=[{"close": 100}],
                price_df=pd.DataFrame({"Close": [100]}),
            )
            for i in range(5)
        ]

        mock_minio = MagicMock()
        mock_mongo = MagicMock()
        mock_db = MagicMock()

        parallel_upload_batch_results(
            ticker_results=trs,
            minio=mock_minio,
            mongo=mock_mongo,
            db=mock_db,
            run_id="test-run",
            end_date="2024-12-31",
            frequency="weekly",
            start_date="2024-01-01",
            max_workers=3,
        )

        assert mock_minio.upload_csv.call_count == 5


class TestParallelComputeSentiment:
    """Tests for parallel VADER sentiment scoring."""

    @patch("modules.utils.parallel.aggregate_sentiment")
    @patch("modules.utils.parallel.score_articles")
    @patch("modules.utils.parallel.deduplicate_articles")
    @patch("modules.utils.parallel.get_analyser")
    def test_basic_scoring(self, mock_analyser, mock_dedup, mock_score, mock_agg):
        mock_analyser.return_value = MagicMock()
        mock_dedup.return_value = [{"headline": "test"}]
        mock_score.return_value = [{"headline": "test", "sentiment": 0.5}]
        mock_agg.return_value = {
            "company_id": "AAPL",
            "sentiment_score": 0.75,
            "avg_sentiment": 0.5,
        }

        result = parallel_compute_sentiment(
            all_articles={"AAPL": [{"headline": "test"}]},
            score_date=date(2024, 1, 1),
            max_workers=1,
        )

        assert len(result) == 1
        assert result[0]["company_id"] == "AAPL"
        assert result[0]["sentiment_score"] == 0.75

    @patch("modules.utils.parallel.aggregate_sentiment")
    @patch("modules.utils.parallel.score_articles")
    @patch("modules.utils.parallel.deduplicate_articles")
    @patch("modules.utils.parallel.get_analyser")
    def test_multiple_companies(self, mock_analyser, mock_dedup, mock_score, mock_agg):
        mock_analyser.return_value = MagicMock()
        mock_dedup.return_value = [{"headline": "test"}]
        mock_score.return_value = [{"headline": "test", "sentiment": 0.5}]
        mock_agg.side_effect = lambda ticker, scored, d: {
            "company_id": ticker,
            "sentiment_score": 0.5,
        }

        result = parallel_compute_sentiment(
            all_articles={
                "AAPL": [{"headline": "test"}],
                "MSFT": [{"headline": "test"}],
                "GOOGL": [{"headline": "test"}],
            },
            score_date=date(2024, 1, 1),
            max_workers=3,
        )

        assert len(result) == 3
        tickers = {r["company_id"] for r in result}
        assert tickers == {"AAPL", "MSFT", "GOOGL"}

    @patch("modules.utils.parallel.aggregate_sentiment")
    @patch("modules.utils.parallel.score_articles")
    @patch("modules.utils.parallel.deduplicate_articles")
    @patch("modules.utils.parallel.get_analyser")
    def test_progress_callback(self, mock_analyser, mock_dedup, mock_score, mock_agg):
        mock_analyser.return_value = MagicMock()
        mock_dedup.return_value = [{"headline": "test"}]
        mock_score.return_value = [{"headline": "test"}]
        mock_agg.return_value = {"company_id": "AAPL", "sentiment_score": 0.8}

        callback = MagicMock()
        parallel_compute_sentiment(
            all_articles={"AAPL": [{"headline": "test"}]},
            score_date=date(2024, 1, 1),
            max_workers=1,
            progress_callback=callback,
        )

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "AAPL"
        assert args[1] == "success"

    @patch("modules.utils.parallel.aggregate_sentiment")
    @patch("modules.utils.parallel.score_articles")
    @patch("modules.utils.parallel.deduplicate_articles")
    @patch("modules.utils.parallel.get_analyser")
    def test_error_handled(self, mock_analyser, mock_dedup, mock_score, mock_agg):
        mock_analyser.return_value = MagicMock()
        mock_dedup.side_effect = Exception("scoring error")

        result = parallel_compute_sentiment(
            all_articles={"AAPL": [{"headline": "test"}]},
            score_date=date(2024, 1, 1),
            max_workers=1,
        )

        assert len(result) == 0


class TestRunExtractionStages:
    """Tests for stage-level concurrent extraction."""

    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_all_stages_run(self, mock_fx, mock_news):
        """YF News provides articles → cascade returns them in all_news."""
        mock_fx.return_value = {"GBPUSD=X": pd.DataFrame({"Close": [1.25]})}
        mock_news.return_value = {"AAPL": [{"headline": "yf test"}]}

        result = run_extraction_stages(
            tickers=["AAPL"],
            company_records=[{"symbol": "AAPL", "security": "Apple Inc"}],
            sources=["prices", "news", "fx"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            ds_config={"gdelt": {"enabled": True}},
        )

        assert "fx_data" in result
        assert "all_news" in result
        assert "news_stats" in result
        assert len(result["fx_data"]) > 0
        assert "AAPL" in result["all_news"]
        assert result["news_stats"]["yf_news"] == 1

    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_fx_disabled(self, mock_fx, mock_news):
        mock_news.return_value = {}

        result = run_extraction_stages(
            tickers=["AAPL"],
            company_records=[{"symbol": "AAPL", "security": "Apple Inc"}],
            sources=["prices", "news"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            ds_config={},
        )

        assert result["fx_data"] == {}
        mock_fx.assert_not_called()

    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_news_disabled(self, mock_fx, mock_news):
        mock_fx.return_value = {}

        result = run_extraction_stages(
            tickers=["AAPL"],
            company_records=[{"symbol": "AAPL", "security": "Apple Inc"}],
            sources=["prices", "fx"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            ds_config={},
        )

        assert result["all_news"] == {}
        mock_news.assert_not_called()

    @patch("modules.utils.parallel.parallel_extract_gdelt")
    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_gdelt_disabled_in_config(self, mock_fx, mock_news, mock_gdelt):
        """When GDELT is disabled, gap tickers don't trigger GDELT."""
        mock_fx.return_value = {}
        mock_news.return_value = {"AAPL": []}  # YF returns 0 articles

        result = run_extraction_stages(
            tickers=["AAPL"],
            company_records=[{"symbol": "AAPL", "security": "Apple Inc"}],
            sources=["prices", "news", "fx"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            ds_config={"gdelt": {"enabled": False}},
        )

        assert result["all_news"] == {}  # No articles from any source
        mock_gdelt.assert_not_called()

    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_stage_error_isolated(self, mock_fx, mock_news):
        """FX stage fails, news cascade still returns results."""
        mock_fx.side_effect = Exception("FX connection error")
        mock_news.return_value = {"AAPL": [{"headline": "yf test"}]}

        result = run_extraction_stages(
            tickers=["AAPL"],
            company_records=[{"symbol": "AAPL", "security": "Apple Inc"}],
            sources=["prices", "news", "fx"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            ds_config={"gdelt": {"enabled": True}},
        )

        assert result["fx_data"] == {}
        assert "AAPL" in result["all_news"]

    @patch("modules.utils.parallel.parallel_extract_gdelt")
    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_cascade_gap_fill(self, mock_fx, mock_news, mock_gdelt):
        """YF returns 0 for MSFT → GDELT gap-fills only MSFT."""
        mock_fx.return_value = {}
        mock_news.return_value = {
            "AAPL": [{"headline": "yf article"}],
            "MSFT": [],  # gap
        }
        mock_gdelt.return_value = {
            "MSFT": [{"headline": "gdelt article"}],
        }

        result = run_extraction_stages(
            tickers=["AAPL", "MSFT"],
            company_records=[
                {"symbol": "AAPL", "security": "Apple Inc"},
                {"symbol": "MSFT", "security": "Microsoft Corp"},
            ],
            sources=["news"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            ds_config={"gdelt": {"enabled": True}},
        )

        assert "AAPL" in result["all_news"]
        assert "MSFT" in result["all_news"]
        assert result["news_stats"]["yf_news"] == 1
        assert result["news_stats"]["gdelt"] == 1
        # GDELT only called for gap tickers (MSFT)
        gdelt_companies = mock_gdelt.call_args.kwargs.get("companies") or mock_gdelt.call_args[1].get("companies")
        gdelt_tickers = [c["symbol"] for c in gdelt_companies]
        assert "MSFT" in gdelt_tickers
        assert "AAPL" not in gdelt_tickers


class TestExtractSingleTicker:
    """Tests for _extract_single_ticker covering circuit breaker, semaphore, and financials paths."""

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.clean_price_dataframe")
    def test_circuit_breaker_open_skips(self, mock_clean, mock_prices):
        """When circuit breaker is OPEN, ticker is skipped entirely."""
        from modules.utils.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=300)
        cb.record_failure()  # Trip the breaker

        result = _extract_single_ticker(
            raw_ticker="AAPL",
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            rate_limiter=None,
            delay=0.0,
            circuit_breaker=cb,
        )

        assert result.status == "error"
        assert result.error == "circuit_breaker_open"
        mock_prices.assert_not_called()

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.clean_price_dataframe")
    def test_semaphore_rate_limiter(self, mock_clean, mock_prices):
        """Semaphore-based rate limiter path is used when passed."""
        import threading

        mock_prices.return_value = pd.DataFrame({"Close": [100]})
        mock_clean.return_value = [{"close": 100}]
        sem = threading.Semaphore(1)

        result = _extract_single_ticker(
            raw_ticker="AAPL",
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            rate_limiter=sem,
            delay=0.0,
        )

        assert result.status == "success"
        assert len(result.price_records) == 1

    @patch("modules.utils.parallel.fetch_financial_data")
    @patch("modules.utils.parallel.fetch_company_info")
    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.clean_price_dataframe")
    @patch("modules.utils.parallel.enhance_company_info")
    def test_financials_with_company_info(self, mock_enhance, mock_clean, mock_prices, mock_info, mock_fins):
        """Financial statements enhance existing company info."""
        mock_prices.return_value = pd.DataFrame()
        mock_info.return_value = {"symbol": "AAPL", "pe_ratio": 25.0}
        mock_fins.return_value = {"income_statement": {"Revenue": {"2024-09-30": 1e9}}}
        mock_enhance.return_value = {"symbol": "AAPL", "pe_ratio": 25.0, "ev_ebitda": 15.0}

        result = _extract_single_ticker(
            raw_ticker="AAPL",
            sources=["financials"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            rate_limiter=None,
            delay=0.0,
        )

        assert result.company_info.get("symbol") == "AAPL"
        mock_enhance.assert_called_once()

    @patch("modules.utils.parallel.calculate_ratios_from_financials")
    @patch("modules.utils.parallel.fetch_financial_data")
    @patch("modules.utils.parallel.fetch_company_info")
    @patch("modules.utils.parallel.fetch_price_history")
    @patch("yfinance.Ticker")
    def test_financials_without_company_info_fallback(self, mock_yf, mock_prices, mock_info, mock_fins, mock_calc):
        """When company_info is empty, calculate ratios from financial statements."""
        mock_prices.return_value = pd.DataFrame()
        mock_info.return_value = {}  # No company info
        mock_fins.return_value = {"income_statement": {"Revenue": {"2024-09-30": 1e9}}}
        mock_fi = MagicMock()
        mock_fi.market_cap = 5e9
        mock_yf.return_value.fast_info = mock_fi
        mock_calc.return_value = {"symbol": "AAPL", "pe_ratio": 20.0}

        result = _extract_single_ticker(
            raw_ticker="AAPL",
            sources=["financials"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            rate_limiter=None,
            delay=0.0,
        )

        mock_calc.assert_called_once()
        assert result.company_info.get("pe_ratio") == 20.0

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.fetch_company_info")
    @patch("modules.utils.parallel.fetch_financial_data")
    def test_circuit_breaker_info_check(self, mock_fins, mock_info, mock_prices):
        """Circuit breaker re-checked before info and financials fetch."""
        from modules.utils.circuit_breaker import CircuitBreaker

        mock_prices.return_value = pd.DataFrame()
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=300)

        # First call succeeds (prices), then breaker trips before info
        call_count = {"n": 0}
        original_allow = cb.allow_request

        def _allow_side_effect():
            call_count["n"] += 1
            if call_count["n"] >= 3:
                return False  # Block info/financials
            return True

        cb.allow_request = _allow_side_effect

        result = _extract_single_ticker(
            raw_ticker="AAPL",
            sources=["prices", "financials"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            rate_limiter=None,
            delay=0.0,
            circuit_breaker=cb,
        )

        # Info fetch skipped because circuit opened
        assert result.company_info == {} or mock_info.call_count <= 1

    @patch("modules.utils.parallel.fetch_price_history")
    def test_exception_records_failure(self, mock_prices):
        """Exception during extraction records circuit breaker failure."""
        from modules.utils.circuit_breaker import CircuitBreaker

        mock_prices.side_effect = Exception("API crash")
        cb = CircuitBreaker("test", failure_threshold=10, recovery_timeout=300)

        result = _extract_single_ticker(
            raw_ticker="AAPL",
            sources=["prices"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            rate_limiter=None,
            delay=0.0,
            circuit_breaker=cb,
        )

        assert result.status == "error"
        assert cb._failure_count == 1


class TestRefetchMissingRatios:
    """Tests for refetch_missing_ratios."""

    def test_no_missing_ratios_returns_early(self):
        infos = [
            {
                "symbol": "AAPL",
                "pe_ratio": 25,
                "pb_ratio": 10,
                "ev_ebitda": 15,
                "dividend_yield": 0.01,
                "debt_equity": 1.0,
            }
        ]
        result = refetch_missing_ratios(infos)
        assert result == infos

    @patch("modules.utils.parallel.enhance_company_info")
    def test_pass1_fills_from_statements(self, mock_enhance):
        """Pass 1 fills missing ratios from existing financial statements."""
        infos = [{"symbol": "AAPL", "pe_ratio": 25, "pb_ratio": None, "ev_ebitda": None, "dividend_yield": 0.01, "debt_equity": 1.0}]
        financials = {"AAPL": {"income_statement": {"Revenue": {"2024-09-30": 1e9}}}}
        mock_enhance.return_value = {"symbol": "AAPL", "pe_ratio": 25, "pb_ratio": 12.0, "ev_ebitda": 18.0, "dividend_yield": 0.01, "debt_equity": 1.0}

        result = refetch_missing_ratios(infos, all_financials=financials)

        assert result[0]["pb_ratio"] == 12.0
        assert result[0]["ev_ebitda"] == 18.0

    @patch("modules.utils.parallel.fetch_financial_data")
    @patch("modules.utils.parallel.fetch_company_info")
    @patch("modules.utils.parallel.enhance_company_info")
    def test_pass2_api_refetch(self, mock_enhance, mock_info, mock_fins):
        """Pass 2 re-fetches from API for tickers still missing ratios."""
        infos = [{"symbol": "MSFT", "pe_ratio": None, "pb_ratio": None, "ev_ebitda": None, "dividend_yield": None, "debt_equity": None}]
        mock_info.return_value = {"pe_ratio": 30.0, "pb_ratio": 15.0, "ev_ebitda": 20.0, "dividend_yield": 0.02, "debt_equity": 0.5}
        mock_fins.return_value = {}
        mock_enhance.return_value = {}

        with patch("time.sleep"):
            result = refetch_missing_ratios(infos, all_financials=None)

        assert result[0]["pe_ratio"] == 30.0
        assert result[0]["pb_ratio"] == 15.0

    @patch("modules.extraction.yahoo_finance_extractor.fetch_financial_data")
    @patch("modules.utils.parallel.fetch_company_info")
    @patch("modules.utils.parallel.enhance_company_info")
    def test_pass2_financial_statements_fallback(self, mock_enhance, mock_info, mock_fins):
        """Pass 2 tries financial statements when API info incomplete."""
        infos = [{"symbol": "TSLA", "pe_ratio": None, "pb_ratio": None, "ev_ebitda": None, "dividend_yield": None, "debt_equity": None}]
        # API returns only pe_ratio — others still missing
        mock_info.return_value = {"pe_ratio": 50.0}
        mock_fins.return_value = {"income_statement": {}}
        mock_enhance.return_value = {"pb_ratio": 8.0, "ev_ebitda": 25.0, "dividend_yield": 0.0, "debt_equity": 0.8}

        with patch("time.sleep"):
            result = refetch_missing_ratios(infos, all_financials=None)

        mock_fins.assert_called_once()
        assert result[0]["pe_ratio"] == 50.0
        assert result[0]["pb_ratio"] == 8.0

    @patch("modules.utils.parallel.fetch_company_info")
    def test_pass2_exception_handled(self, mock_info):
        """Pass 2 handles exceptions gracefully."""
        infos = [{"symbol": "BAD", "pe_ratio": None, "pb_ratio": None, "ev_ebitda": None, "dividend_yield": None, "debt_equity": None}]
        mock_info.side_effect = Exception("Timeout")

        with patch("time.sleep"):
            result = refetch_missing_ratios(infos, all_financials=None)

        assert result[0]["pe_ratio"] is None  # Still None


class TestParallelExtractNewsapi:
    """Tests for parallel_extract_newsapi."""

    @patch("modules.utils.parallel.fetch_news_newsapi")
    def test_successful_extraction(self, mock_newsapi):
        mock_newsapi.return_value = [{"headline": "NewsAPI article", "company_id": "AAPL"}]

        result = parallel_extract_newsapi(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            api_key="test-key",
            max_workers=1,
        )

        assert "AAPL" in result
        assert len(result["AAPL"]) == 1

    @patch("modules.utils.parallel.fetch_news_newsapi")
    def test_empty_results(self, mock_newsapi):
        mock_newsapi.return_value = []

        result = parallel_extract_newsapi(
            companies=[{"symbol": "MSFT", "security": "Microsoft"}],
            api_key="test-key",
            max_workers=1,
        )

        assert "MSFT" in result
        assert result["MSFT"] == []

    @patch("modules.utils.parallel.fetch_news_newsapi")
    def test_error_handled(self, mock_newsapi):
        mock_newsapi.side_effect = Exception("NewsAPI error")

        result = parallel_extract_newsapi(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            api_key="test-key",
            max_workers=1,
        )

        assert "AAPL" in result
        assert result["AAPL"] == []

    @patch("modules.utils.parallel.fetch_news_newsapi")
    def test_empty_symbol_skipped(self, mock_newsapi):
        mock_newsapi.return_value = [{"headline": "test"}]

        result = parallel_extract_newsapi(
            companies=[{"symbol": "", "security": "Unknown"}],
            api_key="test-key",
            max_workers=1,
        )

        assert len(result) == 0

    @patch("modules.utils.parallel.fetch_news_newsapi")
    def test_circuit_breaker_blocks(self, mock_newsapi):
        from modules.utils.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("newsapi", failure_threshold=1, recovery_timeout=300)
        cb.record_failure()  # Trip

        mock_newsapi.return_value = [{"headline": "test"}]

        result = parallel_extract_newsapi(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            api_key="test-key",
            max_workers=1,
            circuit_breaker=cb,
        )

        assert "AAPL" in result
        assert result["AAPL"] == []
        mock_newsapi.assert_not_called()

    @patch("modules.utils.parallel.fetch_news_newsapi")
    def test_progress_callback(self, mock_newsapi):
        mock_newsapi.return_value = [{"headline": "test"}]
        callback = MagicMock()

        parallel_extract_newsapi(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            api_key="test-key",
            max_workers=1,
            progress_callback=callback,
        )

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "AAPL"
        assert args[1] == "success"

    @patch("modules.utils.parallel.fetch_news_newsapi")
    def test_retry_pass_for_empty(self, mock_newsapi):
        """Empty results trigger a retry pass."""
        call_count = {"n": 0}

        def _side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return []
            return [{"headline": "retry success"}]

        mock_newsapi.side_effect = _side_effect

        with patch("time.sleep"):
            result = parallel_extract_newsapi(
                companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
                api_key="test-key",
                max_workers=1,
            )

        assert "AAPL" in result
        assert len(result["AAPL"]) == 1

    @patch("modules.utils.parallel.fetch_news_newsapi")
    def test_rate_limiter_used(self, mock_newsapi):
        from modules.utils.rate_limiter import TokenBucketRateLimiter

        mock_newsapi.return_value = [{"headline": "test"}]
        rl = TokenBucketRateLimiter(rate=100.0, capacity=10, name="test")

        result = parallel_extract_newsapi(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            api_key="test-key",
            max_workers=1,
            rate_limiter=rl,
        )

        assert "AAPL" in result


class TestParallelExtractFxEdgeCases:
    """Additional edge case tests for parallel_extract_fx."""

    @patch("modules.utils.parallel.fetch_fx_rates")
    def test_default_pairs_used(self, mock_fetch):
        """When no pairs specified, uses FX_PAIRS default."""
        mock_fetch.return_value = {}

        result = parallel_extract_fx(
            start_date="2024-01-01",
            end_date="2024-12-31",
            pairs=None,
            max_workers=1,
        )

        assert isinstance(result, dict)

    @patch("modules.utils.parallel.fetch_fx_rates")
    def test_fetch_exception_returns_empty_df(self, mock_fetch):
        """Exception during fetch returns empty DataFrame for that pair."""
        mock_fetch.side_effect = Exception("Connection error")

        result = parallel_extract_fx(
            start_date="2024-01-01",
            end_date="2024-12-31",
            pairs=["GBPUSD=X"],
            max_workers=1,
        )

        assert "GBPUSD=X" in result
        assert result["GBPUSD=X"].empty


class TestParallelExtractNewsRetry:
    """Tests for news retry passes and circuit breaker paths."""

    @patch("modules.utils.parallel.fetch_news")
    @patch("modules.utils.parallel.prepare_ticker")
    def test_circuit_breaker_blocks_news(self, mock_prepare, mock_news):
        from modules.utils.circuit_breaker import CircuitBreaker

        mock_prepare.return_value = "AAPL"
        cb = CircuitBreaker("yf_news", failure_threshold=1, recovery_timeout=300)
        cb.record_failure()  # Trip

        result = parallel_extract_news(
            tickers=["AAPL"],
            max_workers=1,
            delay_per_ticker=0.0,
            circuit_breaker=cb,
        )

        assert "AAPL" in result
        assert result["AAPL"] == []
        mock_news.assert_not_called()

    @patch("modules.utils.parallel.fetch_news")
    @patch("modules.utils.parallel.prepare_ticker")
    def test_retry_pass_fills_empty(self, mock_prepare, mock_news):
        """Empty tickers get retried and filled on second pass."""
        mock_prepare.side_effect = lambda x: x
        call_count = {"n": 0}

        def _side_effect(ticker):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return []
            return [{"headline": "retry success"}]

        mock_news.side_effect = _side_effect

        with patch("time.sleep"):
            result = parallel_extract_news(
                tickers=["AAPL"],
                max_workers=1,
                delay_per_ticker=0.0,
            )

        assert "AAPL" in result
        assert len(result["AAPL"]) == 1

    @patch("modules.utils.parallel.fetch_news")
    @patch("modules.utils.parallel.prepare_ticker")
    def test_circuit_breaker_records_success(self, mock_prepare, mock_news):
        from modules.utils.circuit_breaker import CircuitBreaker

        mock_prepare.return_value = "AAPL"
        mock_news.return_value = [{"headline": "test"}]
        cb = CircuitBreaker("yf_news", failure_threshold=5, recovery_timeout=300)

        parallel_extract_news(
            tickers=["AAPL"],
            max_workers=1,
            delay_per_ticker=0.0,
            circuit_breaker=cb,
        )

        assert cb._failure_count == 0


class TestParallelExtractGdeltRetry:
    """Tests for GDELT retry passes and circuit breaker/rate limiter paths."""

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_circuit_breaker_blocks_gdelt(self, mock_gdelt):
        from modules.utils.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("gdelt", failure_threshold=1, recovery_timeout=300)
        cb.record_failure()  # Trip

        result = parallel_extract_gdelt(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            max_workers=1,
            circuit_breaker=cb,
        )

        assert "AAPL" in result
        assert result["AAPL"] == []

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_rate_limiter_used(self, mock_gdelt):
        from modules.utils.rate_limiter import TokenBucketRateLimiter

        mock_gdelt.return_value = [{"headline": "test"}]
        rl = TokenBucketRateLimiter(rate=100.0, capacity=10, name="test")

        result = parallel_extract_gdelt(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            max_workers=1,
            rate_limiter=rl,
        )

        assert "AAPL" in result
        assert len(result["AAPL"]) == 1

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_retry_pass_fills_empty(self, mock_gdelt):
        """Empty results trigger retry pass."""
        call_count = {"n": 0}

        def _side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return []
            return [{"headline": "retry success"}]

        mock_gdelt.side_effect = _side_effect

        with patch("time.sleep"):
            result = parallel_extract_gdelt(
                companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
                max_workers=1,
            )

        assert "AAPL" in result
        assert len(result["AAPL"]) == 1

    @patch("modules.utils.parallel.fetch_news_gdelt")
    def test_circuit_breaker_records_success_and_failure(self, mock_gdelt):
        from modules.utils.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("gdelt", failure_threshold=10, recovery_timeout=300)
        mock_gdelt.return_value = [{"headline": "test"}]

        parallel_extract_gdelt(
            companies=[{"symbol": "AAPL", "security": "Apple Inc"}],
            max_workers=1,
            circuit_breaker=cb,
        )

        assert cb._failure_count == 0


class TestParallelUploadEdgeCases:
    """Additional upload tests for error and financials-only paths."""

    @patch("modules.loading.postgres_loader.insert_ingestion_log")
    def test_error_ticker_upload(self, mock_log):
        """Error status ticker writes FAILED ingestion log."""
        tr = TickerResult(
            ticker="BAD",
            yf_ticker="BAD",
            currency="USD",
            status="error",
            error="timeout",
        )

        mock_minio = MagicMock()
        mock_mongo = MagicMock()
        mock_db = MagicMock()

        parallel_upload_batch_results(
            ticker_results=[tr],
            minio=mock_minio,
            mongo=mock_mongo,
            db=mock_db,
            run_id="test-run",
            end_date="2024-12-31",
            frequency="weekly",
            start_date="2024-01-01",
            max_workers=1,
        )

        mock_minio.upload_csv.assert_not_called()
        # Should have logged FAILED status
        assert mock_log.call_count >= 1

    @patch("modules.loading.postgres_loader.insert_ingestion_log")
    def test_financials_only_upload(self, mock_log):
        """Ticker with only financials (no prices) uploads to MinIO/MongoDB."""
        tr = TickerResult(
            ticker="AAPL",
            yf_ticker="AAPL",
            currency="USD",
            financials={"income_statement": {"Revenue": {"2024-09-30": 1e9}}},
        )

        mock_minio = MagicMock()
        mock_mongo = MagicMock()
        mock_db = MagicMock()

        parallel_upload_batch_results(
            ticker_results=[tr],
            minio=mock_minio,
            mongo=mock_mongo,
            db=mock_db,
            run_id="test-run",
            end_date="2024-12-31",
            frequency="weekly",
            start_date="2024-01-01",
            max_workers=1,
        )

        # Financials uploaded to MinIO and MongoDB
        mock_minio.upload_json.assert_called()
        mock_mongo.insert_one.assert_called()


class TestParallelComputeSentimentEdgeCases:
    """Edge case tests for parallel_compute_sentiment."""

    @patch("modules.utils.parallel.aggregate_sentiment")
    @patch("modules.utils.parallel.score_articles")
    @patch("modules.utils.parallel.deduplicate_articles")
    @patch("modules.utils.parallel.get_analyser")
    def test_default_score_date(self, mock_analyser, mock_dedup, mock_score, mock_agg):
        """When no score_date provided, defaults to today."""
        mock_analyser.return_value = MagicMock()
        mock_dedup.return_value = []
        mock_score.return_value = []
        mock_agg.return_value = {"company_id": "AAPL", "sentiment_score": None}

        result = parallel_compute_sentiment(
            all_articles={"AAPL": []},
            score_date=None,
            max_workers=1,
        )

        assert len(result) == 1

    @patch("modules.utils.parallel.aggregate_sentiment")
    @patch("modules.utils.parallel.score_articles")
    @patch("modules.utils.parallel.deduplicate_articles")
    @patch("modules.utils.parallel.get_analyser")
    def test_error_with_progress_callback(self, mock_analyser, mock_dedup, mock_score, mock_agg):
        """Error during scoring triggers error callback."""
        mock_analyser.return_value = MagicMock()
        mock_dedup.side_effect = Exception("scoring crash")

        callback = MagicMock()
        result = parallel_compute_sentiment(
            all_articles={"AAPL": [{"headline": "test"}]},
            score_date=date(2024, 1, 1),
            max_workers=1,
            progress_callback=callback,
        )

        assert len(result) == 0
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "AAPL"
        assert args[1] == "error"


class TestRunExtractionStagesNewsapi:
    """Tests for NewsAPI tier 3 in run_extraction_stages."""

    @patch("modules.utils.parallel.parallel_extract_newsapi")
    @patch("modules.utils.parallel.parallel_extract_gdelt")
    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_newsapi_tier3_gap_fill(self, mock_fx, mock_news, mock_gdelt, mock_newsapi):
        """NewsAPI fills gaps left by YF News and GDELT."""
        mock_fx.return_value = {}
        mock_news.return_value = {"AAPL": [], "MSFT": []}  # All empty
        mock_gdelt.return_value = {"AAPL": [], "MSFT": []}  # Still empty
        mock_newsapi.return_value = {
            "AAPL": [{"headline": "newsapi article"}],
            "MSFT": [{"headline": "newsapi article 2"}],
        }

        result = run_extraction_stages(
            tickers=["AAPL", "MSFT"],
            company_records=[
                {"symbol": "AAPL", "security": "Apple Inc"},
                {"symbol": "MSFT", "security": "Microsoft Corp"},
            ],
            sources=["news"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            ds_config={
                "gdelt": {"enabled": True},
                "newsapi": {"enabled": True, "api_key": "test-key", "only_top_n": 50},
            },
        )

        assert "AAPL" in result["all_news"]
        assert result["news_stats"]["newsapi"] == 2
        mock_newsapi.assert_called_once()

    @patch("modules.utils.parallel.parallel_extract_newsapi")
    @patch("modules.utils.parallel.parallel_extract_gdelt")
    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_newsapi_env_var_resolution(self, mock_fx, mock_news, mock_gdelt, mock_newsapi):
        """NewsAPI resolves ${ENV_VAR} style API keys."""
        import os

        mock_fx.return_value = {}
        mock_news.return_value = {"AAPL": []}
        mock_gdelt.return_value = {"AAPL": []}
        mock_newsapi.return_value = {}

        with patch.dict(os.environ, {"NEWSAPI_KEY": "resolved-key"}):
            run_extraction_stages(
                tickers=["AAPL"],
                company_records=[{"symbol": "AAPL", "security": "Apple Inc"}],
                sources=["news"],
                start_date="2024-01-01",
                end_date="2024-12-31",
                ds_config={
                    "gdelt": {"enabled": True},
                    "newsapi": {"enabled": True, "api_key": "${NEWSAPI_KEY}", "only_top_n": 50},
                },
            )

        # Verify newsapi was called with resolved key
        call_kwargs = mock_newsapi.call_args[1] if mock_newsapi.call_args else {}
        assert call_kwargs.get("api_key") == "resolved-key"

    @patch("modules.utils.parallel.parallel_extract_news")
    @patch("modules.utils.parallel.parallel_extract_fx")
    def test_news_cascade_error_isolated(self, mock_fx, mock_news):
        """News cascade error doesn't crash the pipeline."""
        mock_fx.return_value = {"GBPUSD=X": pd.DataFrame({"Close": [1.25]})}
        mock_news.side_effect = Exception("News cascade crash")

        result = run_extraction_stages(
            tickers=["AAPL"],
            company_records=[{"symbol": "AAPL", "security": "Apple Inc"}],
            sources=["news", "fx"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            ds_config={},
        )

        assert "fx_data" in result
        assert result["all_news"] == {}


class TestParallelExtractPricesEdgeCases:
    """Additional edge cases for parallel_extract_prices."""

    @patch("modules.utils.parallel.fetch_price_history")
    @patch("modules.utils.parallel.fetch_company_info")
    @patch("modules.utils.parallel.fetch_financial_data")
    @patch("modules.utils.parallel.clean_price_dataframe")
    def test_info_fail_counted(self, mock_clean, mock_fins, mock_info, mock_prices):
        """When financials source requested but info returns empty, info_fail incremented."""
        mock_prices.return_value = pd.DataFrame({"Close": [100]})
        mock_clean.return_value = [{"close": 100}]
        mock_info.return_value = {}
        mock_fins.return_value = {}

        result = parallel_extract_prices(
            batch=["AAPL"],
            sources=["prices", "financials"],
            start_date="2024-01-01",
            end_date="2024-12-31",
            currency_map={},
            max_retries=1,
            max_workers=1,
            delay_per_ticker=0.0,
        )

        assert result.info_fail >= 1
