import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from a_pipeline.modules.db_loader import postgres


@patch("a_pipeline.modules.db_loader.postgres.pd.read_sql")
def test_get_latest_data_as_of_date_sql(mock_read_sql, mock_engine):
    """Verifies point-in-time SQL injection logic."""
    mock_read_sql.return_value = MagicMock()

    postgres.get_latest_data(
        table_name="test_table", as_of_date="2024-01-01", date_col="price_date"
    )

    called_sql = mock_read_sql.call_args[0][0].text
    assert ":as_of_date" in called_sql
    assert '"price_date" <= :as_of_date' in called_sql


@pytest.mark.parametrize(
    "func_name",
    [
        "create_ohlcv_table",
        "create_liquidity_table",
        "create_trend_table",
        "create_momentum_table",
        "create_risk_table",
        "create_mean_reversion_table",
        "create_eps_history_table",
        "create_eps_estimate_table",
    ],
)
@patch("a_pipeline.modules.db_loader.postgres.engine")
def test_create_tables_sweep(mock_engine, func_name):
    """Executes all schema creation functions."""
    func = getattr(postgres, func_name)
    func()
    assert mock_engine.connect.called


@pytest.mark.parametrize(
    "func_name, args",
    [
        ("get_all_sectors", []),
        ("get_all_industries", []),
        ("get_table", ["company_static"]),
        ("get_companies_by_industry", [["Semiconductors"]]),
        ("get_companies_by_sector", [["Technology"]]),
        ("get_latest_date", ["daily_ohlcv"]),
    ],
)
@patch("a_pipeline.modules.db_loader.postgres.engine")
@patch("a_pipeline.modules.db_loader.postgres.pd.read_sql")
def test_get_metadata_sweep(mock_read_sql, mock_engine, func_name, args):
    """Tests all metadata and table retrieval functions."""
    mock_read_sql.return_value = pd.DataFrame(
        {"symbol": ["AAPL"], "gics_sector": ["Tech"]}
    )

    func = getattr(postgres, func_name)
    func(*args)
    assert mock_read_sql.called or mock_engine.connect.called


@pytest.mark.parametrize(
    "update_func_name",
    [
        "update_ohlcv_data",
        "update_liquidity_data",
        "update_trend_data",
        "update_momentum_data",
        "update_risk_data",
        "update_mean_reversion_data",
        "update_eps_history",
        "update_eps_estimate",
    ],
)
@patch("a_pipeline.modules.db_loader.postgres.engine")
def test_postgres_update_sweep(
    mock_engine, update_func_name, sample_price_data, sample_eps_data
):
    """Tests all upsert/update functions in one loop."""

    df = (
        sample_eps_data.copy()
        if "eps" in update_func_name
        else sample_price_data.copy()
    )

    for col in ["dollar_volume", "ma200", "mom_12m", "vol_20d", "rsi_2d"]:
        if col not in df.columns:
            df[col] = 1.0

    func = getattr(postgres, update_func_name)
    with patch.object(pd.DataFrame, "to_sql") as mock_to_sql:
        func(df)
        assert mock_to_sql.called


@patch("a_pipeline.modules.db_loader.postgres.engine")
@patch("a_pipeline.modules.db_loader.postgres.pd.read_sql")
def test_postgres_utilities_and_maintenance(
    mock_read_sql, mock_engine, sample_price_data
):
    """Tests specialized functions: symbol fetch, column add/delete, and table drop."""

    mock_read_sql.return_value = sample_price_data
    postgres.get_symbol_data("AAPL", "daily_ohlcv")

    df_with_col = sample_price_data.copy()
    df_with_col["new_feat"] = 1.0
    postgres.add_new_column(df_with_col, "new_feat", "NUMERIC", "daily_ohlcv")

    postgres.del_column("new_feat", "daily_ohlcv")
    postgres.del_table("temp_table")

    assert mock_engine.begin.called or mock_engine.connect.called


@patch("a_pipeline.modules.db_loader.postgres.engine")
def test_get_table_database_error(mock_engine):
    """Triggers the 'except Exception' block in get_table for coverage."""
    from a_pipeline.modules.db_loader import postgres

    mock_engine.connect.side_effect = Exception("Mock DB Failure")

    result = postgres.get_table("any_table")

    assert result is None
