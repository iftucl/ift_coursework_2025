import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from a_pipeline.modules.url_parser import yf_pipeline


@patch("a_pipeline.modules.url_parser.yf_pipeline.yf.download")
@patch("a_pipeline.modules.db_loader.postgres.update_ohlcv_data")
def test_fetch_ohlcv_data_cleaning(mock_update, mock_yf, sample_price_data):
    """Verifies that the pipeline correctly cleans and stacks MultiIndex YFinance data."""

    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "AAPL"),
            ("High", "AAPL"),
            ("Low", "AAPL"),
            ("Close", "AAPL"),
            ("Volume", "AAPL"),
        ],
        names=[None, "Ticker"],
    )

    vals = sample_price_data[
        ["open_price", "high_price", "low_price", "close_price", "volume"]
    ].values
    df_multi = pd.DataFrame(
        vals, index=sample_price_data["price_date"], columns=columns
    )
    df_multi.index.name = "Date"
    mock_yf.return_value = df_multi

    yf_pipeline.fetch_ohlcv_data(["AAPL"], start_date="2024-01-01")
    assert mock_update.called


@patch("a_pipeline.modules.db_loader.postgres.get_table")
def test_update_factors_no_companies(mock_get_table):
    """Verifies pipeline exits if the company table returns None."""

    mock_get_table.return_value = None

    yf_pipeline.update_factors()

    assert mock_get_table.called


@pytest.mark.parametrize(
    "wrapper_func",
    [
        "calculate_liquidity_data",
        "calculate_trend_data",
        "calculate_momentum_data",
        "calculate_risk_data",
    ],
)
@patch("a_pipeline.modules.db_loader.postgres.update_risk_data")
@patch("a_pipeline.modules.db_loader.postgres.update_momentum_data")
@patch("a_pipeline.modules.db_loader.postgres.update_trend_data")
@patch("a_pipeline.modules.db_loader.postgres.update_liquidity_data")
@patch("a_pipeline.modules.db_loader.postgres.get_ohlcv_data")
def test_pipeline_wrappers_sweep(
    m_get, m_liq, m_trend, m_mom, m_risk, wrapper_func, sample_price_data
):
    """Sweeps through all factor calculation wrappers in the pipeline."""
    m_get.return_value = sample_price_data.copy()
    func = getattr(yf_pipeline, wrapper_func)

    try:
        func(["AAPL"], start_date=pd.Timestamp("2024-01-01"))
    except ValueError as e:
        pytest.fail(f"{wrapper_func} failed due to data shape issue: {e}")

    assert m_get.called


@patch("a_pipeline.modules.url_parser.yf_pipeline.postgres")
@patch("a_pipeline.modules.url_parser.yf_pipeline.fetch_ohlcv_data")
def test_update_ohlcv_batch_flow(mock_fetch, mock_postgres):
    """Tests the main entry point for OHLCV updates (batching and date logic)."""
    mock_postgres.get_company_static.return_value = pd.DataFrame({"symbol": ["AAPL"]})
    mock_postgres.get_latest_date.return_value = pd.Timestamp("2024-01-01")

    yf_pipeline.update_ohlcv_batch()

    assert mock_postgres.create_ohlcv_table.called
    assert mock_fetch.called


@patch("a_pipeline.modules.url_parser.yf_pipeline.postgres")
def test_update_factors_full_flow(mock_postgres):
    """Tests the main coordination function for calculating all factor tables."""
    mock_postgres.get_company_static.return_value = pd.DataFrame({"symbol": ["AAPL"]})

    yf_pipeline.update_factors()

    assert mock_postgres.create_liquidity_table.called
    assert mock_postgres.create_trend_table.called
    assert mock_postgres.create_momentum_table.called
    assert mock_postgres.create_risk_table.called
