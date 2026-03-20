"""Unit tests for Pipeline C data loader module."""

from unittest.mock import MagicMock, patch

import pandas as pd
from modules.db_loader.data_loader import load_factor_inputs


def _cfg():
    return {"user": "u", "password": "p", "host": "h", "port": 5432, "database": "db"}


def _sample_df():
    return pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT"],
            "gics_sector": ["Technology", "Technology"],
            "closing_price": [150.0, 300.0],
            "shares_outstanding": [1_000_000, 2_000_000],
            "total_assets": [500e6, 800e6],
            "total_liabilities": [200e6, 300e6],
            "net_income_ttm": [10e6, 30e6],
            "ebitda_ttm": [20e6, 50e6],
            "total_debt": [50e6, 100e6],
            "cash_and_equivalents": [10e6, 20e6],
            "book_value": [300e6, 500e6],
            "revenue": [120e6, 300e6],
            "gross_profit": [60e6, 150e6],
            "free_cash_flow": [8e6, 25e6],
            "current_assets": [80e6, 120e6],
            "current_liabilities": [40e6, 60e6],
            "annual_dividend_rate": [0.96, 0.0],
        }
    )


def _patch_read_sql(return_value):
    return patch("modules.db_loader.data_loader.pd.read_sql", return_value=return_value)


class TestLoadFactorInputs:
    @patch("modules.db_loader.data_loader.create_engine")
    def test_returns_dataframe(self, mock_engine_cls):
        mock_engine_cls.return_value = MagicMock()
        with _patch_read_sql(_sample_df()):
            result = load_factor_inputs(_cfg(), "2024-12-31")
        assert isinstance(result, pd.DataFrame)

    @patch("modules.db_loader.data_loader.create_engine")
    def test_returns_correct_row_count(self, mock_engine_cls):
        mock_engine_cls.return_value = MagicMock()
        with _patch_read_sql(_sample_df()):
            result = load_factor_inputs(_cfg(), "2024-12-31")
        assert len(result) == 2

    @patch("modules.db_loader.data_loader.create_engine")
    def test_fills_null_gics_sector_with_unknown(self, mock_engine_cls):
        mock_engine_cls.return_value = MagicMock()
        df = _sample_df()
        df.loc[0, "gics_sector"] = None
        with _patch_read_sql(df):
            result = load_factor_inputs(_cfg(), "2024-12-31")
        assert result.loc[0, "gics_sector"] == "Unknown"
        assert result.loc[1, "gics_sector"] == "Technology"

    @patch("modules.db_loader.data_loader.create_engine")
    def test_lag_cutoff_is_3_months_before_december(self, mock_engine_cls):
        mock_engine_cls.return_value = MagicMock()
        captured = {}

        def capture(*args, **kwargs):
            captured.update(kwargs.get("params", {}))
            return _sample_df()

        with patch("modules.db_loader.data_loader.pd.read_sql", side_effect=capture):
            load_factor_inputs(_cfg(), "2024-12-31")

        assert captured["lag_cutoff"] == "2024-09-30"

    @patch("modules.db_loader.data_loader.create_engine")
    def test_lag_cutoff_is_3_months_before_march(self, mock_engine_cls):
        mock_engine_cls.return_value = MagicMock()
        captured = {}

        def capture(*args, **kwargs):
            captured.update(kwargs.get("params", {}))
            return _sample_df()

        with patch("modules.db_loader.data_loader.pd.read_sql", side_effect=capture):
            load_factor_inputs(_cfg(), "2024-03-31")

        assert captured["lag_cutoff"] == "2023-12-31"

    @patch("modules.db_loader.data_loader.create_engine")
    def test_rebalance_date_passed_as_qdate(self, mock_engine_cls):
        mock_engine_cls.return_value = MagicMock()
        captured = {}

        def capture(*args, **kwargs):
            captured.update(kwargs.get("params", {}))
            return _sample_df()

        with patch("modules.db_loader.data_loader.pd.read_sql", side_effect=capture):
            load_factor_inputs(_cfg(), "2023-12-31")

        assert captured["qdate"] == "2023-12-31"
