"""
Tests for the FX rate extraction module (modules/extraction/fx_extractor.py).

Tests FX pair fetching, retry logic, error handling, and MultiIndex handling.
"""

from unittest.mock import patch

import pandas as pd

from modules.extraction.fx_extractor import FX_PAIRS, fetch_fx_rates


class TestFxPairsConstant:
    """Tests for the FX_PAIRS constant."""

    def test_contains_required_pairs(self):
        assert "GBPUSD=X" in FX_PAIRS
        assert "EURUSD=X" in FX_PAIRS
        assert "CADUSD=X" in FX_PAIRS
        assert "CHFUSD=X" in FX_PAIRS

    def test_four_pairs(self):
        assert len(FX_PAIRS) == 4


class TestFetchFxRates:
    """Tests for the fetch_fx_rates function."""

    @patch("modules.extraction.fx_extractor.yf.download")
    @patch("modules.extraction.fx_extractor.time.sleep", return_value=None)
    def test_successful_fetch(self, mock_sleep, mock_download):
        df = pd.DataFrame(
            {"Open": [1.25], "High": [1.26], "Low": [1.24], "Close": [1.255]},
            index=pd.to_datetime(["2024-01-02"]),
        )
        mock_download.return_value = df

        result = fetch_fx_rates("2024-01-01", "2024-01-05", pairs=["GBPUSD=X"])
        assert "GBPUSD=X" in result
        assert not result["GBPUSD=X"].empty
        assert len(result["GBPUSD=X"]) == 1

    @patch("modules.extraction.fx_extractor.yf.download")
    @patch("modules.extraction.fx_extractor.time.sleep", return_value=None)
    def test_empty_response(self, mock_sleep, mock_download):
        mock_download.return_value = pd.DataFrame()

        result = fetch_fx_rates("2024-01-01", "2024-01-05", pairs=["GBPUSD=X"], max_retries=1)
        assert "GBPUSD=X" in result
        assert result["GBPUSD=X"].empty

    @patch("modules.extraction.fx_extractor.yf.download")
    @patch("modules.extraction.fx_extractor.time.sleep", return_value=None)
    def test_none_response(self, mock_sleep, mock_download):
        mock_download.return_value = None

        result = fetch_fx_rates("2024-01-01", "2024-01-05", pairs=["GBPUSD=X"], max_retries=1)
        assert "GBPUSD=X" in result
        assert result["GBPUSD=X"].empty

    @patch("modules.extraction.fx_extractor.yf.download")
    @patch("modules.extraction.fx_extractor.time.sleep", return_value=None)
    def test_exception_retries(self, mock_sleep, mock_download):
        mock_download.side_effect = Exception("Network error")

        result = fetch_fx_rates("2024-01-01", "2024-01-05", pairs=["GBPUSD=X"], max_retries=2)
        assert "GBPUSD=X" in result
        assert result["GBPUSD=X"].empty
        # Should have retried
        assert mock_download.call_count == 2

    @patch("modules.extraction.fx_extractor.yf.download")
    @patch("modules.extraction.fx_extractor.time.sleep", return_value=None)
    def test_multiple_pairs(self, mock_sleep, mock_download):
        df = pd.DataFrame({"Close": [1.10]}, index=pd.to_datetime(["2024-01-02"]))
        mock_download.return_value = df

        result = fetch_fx_rates("2024-01-01", "2024-01-05")
        assert len(result) == 4
        for pair in FX_PAIRS:
            assert pair in result

    @patch("modules.extraction.fx_extractor.yf.download")
    @patch("modules.extraction.fx_extractor.time.sleep", return_value=None)
    def test_multiindex_columns_flattened(self, mock_sleep, mock_download):
        arrays = [["Close", "Open"], ["GBPUSD=X", "GBPUSD=X"]]
        tuples = list(zip(*arrays))
        index = pd.MultiIndex.from_tuples(tuples)
        df = pd.DataFrame([[1.25, 1.24]], columns=index, index=pd.to_datetime(["2024-01-02"]))
        mock_download.return_value = df

        result = fetch_fx_rates("2024-01-01", "2024-01-05", pairs=["GBPUSD=X"])
        assert "GBPUSD=X" in result
        # MultiIndex should be flattened
        assert not isinstance(result["GBPUSD=X"].columns, pd.MultiIndex)

    @patch("modules.extraction.fx_extractor.yf.download")
    @patch("modules.extraction.fx_extractor.time.sleep", return_value=None)
    def test_custom_pairs(self, mock_sleep, mock_download):
        df = pd.DataFrame({"Close": [150.0]}, index=pd.to_datetime(["2024-01-02"]))
        mock_download.return_value = df

        result = fetch_fx_rates("2024-01-01", "2024-01-05", pairs=["JPYUSD=X"])
        assert "JPYUSD=X" in result
        assert len(result) == 1

    @patch("modules.extraction.fx_extractor.yf.download")
    @patch("modules.extraction.fx_extractor.time.sleep", return_value=None)
    def test_retry_then_success(self, mock_sleep, mock_download):
        df = pd.DataFrame({"Close": [1.25]}, index=pd.to_datetime(["2024-01-02"]))
        mock_download.side_effect = [Exception("error"), df]

        result = fetch_fx_rates("2024-01-01", "2024-01-05", pairs=["GBPUSD=X"], max_retries=2)
        assert "GBPUSD=X" in result
        assert not result["GBPUSD=X"].empty
