"""
Tests for data cleaning and validation module.
"""

import pandas as pd


class TestCleanPriceDataframe:
    """Tests for clean_price_dataframe."""

    def test_valid_dataframe(self, sample_price_df):
        from modules.processing.data_cleaner import clean_price_dataframe

        records = clean_price_dataframe(sample_price_df, "AAPL", "USD")
        assert len(records) == 3
        assert records[0]["symbol"] == "AAPL"
        assert records[0]["currency"] == "USD"

    def test_record_fields(self, sample_price_df):
        from modules.processing.data_cleaner import clean_price_dataframe

        records = clean_price_dataframe(sample_price_df, "AAPL")
        rec = records[0]
        assert "symbol" in rec
        assert "cob_date" in rec
        assert "open_price" in rec
        assert "close_price" in rec
        assert "volume" in rec

    def test_nan_rows_dropped(self, sample_price_df_with_nans):
        from modules.processing.data_cleaner import clean_price_dataframe

        records = clean_price_dataframe(sample_price_df_with_nans, "AAPL")
        assert len(records) == 1  # Only first row has valid Close

    def test_empty_dataframe(self):
        from modules.processing.data_cleaner import clean_price_dataframe

        records = clean_price_dataframe(pd.DataFrame(), "AAPL")
        assert records == []

    def test_none_dataframe(self):
        from modules.processing.data_cleaner import clean_price_dataframe

        records = clean_price_dataframe(None, "AAPL")
        assert records == []

    def test_gbp_currency(self, sample_price_df):
        from modules.processing.data_cleaner import clean_price_dataframe

        records = clean_price_dataframe(sample_price_df, "VOD.L", "GBP")
        assert all(r["currency"] == "GBP" for r in records)


class TestCleanFxDataframe:
    """Tests for clean_fx_dataframe."""

    def test_valid_fx_data(self, sample_fx_df):
        from modules.processing.data_cleaner import clean_fx_dataframe

        records = clean_fx_dataframe(sample_fx_df, "GBPUSD=X")
        assert len(records) == 2
        assert records[0]["currency_pair"] == "GBPUSD=X"

    def test_empty_fx_df(self):
        from modules.processing.data_cleaner import clean_fx_dataframe

        records = clean_fx_dataframe(pd.DataFrame(), "GBPUSD=X")
        assert records == []


class TestValidateCompanyInfo:
    """Tests for validate_company_info."""

    def test_valid_info(self):
        from modules.processing.data_cleaner import validate_company_info

        info = {"symbol": "AAPL", "pe_ratio": 28.5, "pb_ratio": 40.1}
        assert validate_company_info(info) is True

    def test_missing_symbol(self):
        from modules.processing.data_cleaner import validate_company_info

        info = {"pe_ratio": 28.5}
        assert validate_company_info(info) is False

    def test_empty_info(self):
        from modules.processing.data_cleaner import validate_company_info

        assert validate_company_info({}) is False

    def test_none_info(self):
        from modules.processing.data_cleaner import validate_company_info

        assert validate_company_info(None) is False

    def test_no_ratios(self):
        from modules.processing.data_cleaner import validate_company_info

        info = {"symbol": "AAPL", "market_cap": 300000}
        assert validate_company_info(info) is False

    def test_partial_ratios_valid(self):
        from modules.processing.data_cleaner import validate_company_info

        info = {"symbol": "AAPL", "ev_ebitda": 22.0}
        assert validate_company_info(info) is True


class TestPriceValidation:
    """Tests for internal _validate_price function."""

    def test_valid_price(self):
        from modules.processing.data_cleaner import _validate_price

        assert _validate_price(150.0) == 150.0

    def test_negative_price(self):
        from modules.processing.data_cleaner import _validate_price

        assert _validate_price(-5.0) is None

    def test_none_price(self):
        from modules.processing.data_cleaner import _validate_price

        assert _validate_price(None) is None

    def test_nan_price(self):
        from modules.processing.data_cleaner import _validate_price

        assert _validate_price(float("nan")) is None

    def test_inf_price(self):
        from modules.processing.data_cleaner import _validate_price

        assert _validate_price(float("inf")) is None

    def test_string_price(self):
        from modules.processing.data_cleaner import _validate_price

        assert _validate_price("not_a_number") is None

    def test_zero_price(self):
        from modules.processing.data_cleaner import _validate_price

        assert _validate_price(0.0) == 0.0


class TestVolumeValidation:
    """Tests for internal _validate_volume function."""

    def test_valid_volume(self):
        from modules.processing.data_cleaner import _validate_volume

        assert _validate_volume(1000000) == 1000000

    def test_float_volume(self):
        from modules.processing.data_cleaner import _validate_volume

        assert _validate_volume(1000000.5) == 1000000

    def test_negative_volume(self):
        from modules.processing.data_cleaner import _validate_volume

        assert _validate_volume(-100) is None

    def test_none_volume(self):
        from modules.processing.data_cleaner import _validate_volume

        assert _validate_volume(None) is None
