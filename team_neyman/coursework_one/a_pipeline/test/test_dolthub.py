from unittest.mock import MagicMock, patch

import pytest

from a_pipeline.modules.url_parser import dolthub_pipeline


@pytest.fixture
def super_csv_data():
    """Provides a CSV string containing all columns for History and Estimate processing."""
    headers = "date,act_symbol,period,period_end_date,reported,estimate,consensus,recent,count,high,low,year_ago"
    row = "2024-01-01,AAPL,Next Year,2024-12-31,2.5,2.4,2.4,2.3,10,2.6,2.2,2.1"
    return f"{headers}\n{row}"


@patch("a_pipeline.modules.url_parser.dolthub_pipeline.subprocess.run")
@patch("a_pipeline.modules.db_loader.postgres.update_eps_history")
def test_update_eps_history_data(mock_postgres_update, mock_run, super_csv_data):
    """Verifies parsing and column renaming for EPS history."""
    mock_run.return_value = MagicMock(returncode=0, stdout=super_csv_data)

    dolthub_pipeline.update_eps_history_data("/fake/path")

    passed_df = mock_postgres_update.call_args[0][0]
    assert "symbol" in passed_df.columns
    assert "reported_eps" in passed_df.columns
    assert passed_df.iloc[0]["symbol"] == "AAPL"


@patch("a_pipeline.modules.url_parser.dolthub_pipeline.postgres")
@patch("a_pipeline.modules.url_parser.dolthub_pipeline.subprocess.run")
@patch("a_pipeline.modules.url_parser.dolthub_pipeline.os.path.exists")
def test_setup_dolt_database_pull_flow(
    mock_exists, mock_run, mock_postgres, super_csv_data
):
    """Verifies the pipeline flow when the Dolt repo already exists (dolt pull)."""
    mock_exists.return_value = True
    mock_run.return_value = MagicMock(returncode=0, stdout=super_csv_data)

    dolthub_pipeline.setup_dolt_database()

    assert mock_postgres.update_eps_estimate.called
    # Check that 'dolt pull' was triggered
    assert any("pull" in str(args) for args in mock_run.call_args_list)


@patch("a_pipeline.modules.url_parser.dolthub_pipeline.postgres")
@patch("a_pipeline.modules.url_parser.dolthub_pipeline.subprocess.run")
@patch("a_pipeline.modules.url_parser.dolthub_pipeline.os.path.exists")
@patch("a_pipeline.modules.url_parser.dolthub_pipeline.os.makedirs")
def test_setup_dolt_database_clone_flow(
    mock_mkdir, mock_exists, mock_run, mock_postgres, super_csv_data
):
    """Verifies the pipeline flow when the Dolt repo is missing (dolt clone)."""
    mock_exists.return_value = False
    mock_run.return_value = MagicMock(returncode=0, stdout=super_csv_data)

    dolthub_pipeline.setup_dolt_database()

    assert mock_mkdir.called
    assert mock_postgres.update_eps_history.called
    assert mock_postgres.update_eps_estimate.called
    # Check that 'dolt clone' was triggered
    assert any("clone" in str(args) for args in mock_run.call_args_list)
