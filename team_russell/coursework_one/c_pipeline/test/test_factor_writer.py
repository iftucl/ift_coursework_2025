"""Unit tests for Pipeline C factor writer module."""

from unittest.mock import MagicMock, patch

import pandas as pd
from modules.db_writer.factor_writer import FactorWriter


def _sample_df():
    """Minimal DataFrame with all columns expected by FactorWriter."""
    return pd.DataFrame(
        {
            "symbol": ["AAPL"],
            "market_cap": [100e6],
            "book_value": [300e6],
            "bp": [3.0],
            "ey": [0.1],
            "cfy": [0.08],
            "dy": [0.0096],
            "gpa": [0.12],
            "wca": [2.0],
            "ltde": [-0.167],
            "roa": [0.02],
            "z_bp": [0.5],
            "z_ey": [0.3],
            "z_cfy": [0.2],
            "z_dy": [0.1],
            "z_gpa": [0.4],
            "z_wca": [0.3],
            "z_ltde": [0.2],
            "z_roa": [0.1],
            "value_score": [0.8],
            "quality_score": [0.6],
            "composite_score": [0.7],
            "composite_percentile": [0.9],
            "quintile": [1],
        }
    )


def _cfg():
    return {"user": "u", "password": "p", "host": "h", "port": 5432, "database": "db"}


def _make_writer(mock_engine_cls, quarter="2024-12-31", run_id="run_001"):
    mock_engine = MagicMock()
    mock_engine_cls.return_value = mock_engine
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__ = lambda s: mock_conn
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    writer = FactorWriter(_cfg(), quarter, run_id)
    return writer, mock_conn


class TestFactorWriterWrite:
    @patch("modules.db_writer.factor_writer.create_engine")
    def test_write_executes_upsert_sql(self, mock_engine_cls):
        writer, mock_conn = _make_writer(mock_engine_cls)
        writer.write(_sample_df())
        mock_conn.execute.assert_called_once()

    @patch("modules.db_writer.factor_writer.create_engine")
    def test_write_sets_period_date_on_records(self, mock_engine_cls):
        writer, mock_conn = _make_writer(mock_engine_cls, quarter="2023-12-31")
        writer.write(_sample_df())
        records = mock_conn.execute.call_args[0][1]
        assert records[0]["period_date"] == "2023-12-31"

    @patch("modules.db_writer.factor_writer.create_engine")
    def test_write_sets_run_id_on_records(self, mock_engine_cls):
        writer, mock_conn = _make_writer(mock_engine_cls, run_id="my_run")
        writer.write(_sample_df())
        records = mock_conn.execute.call_args[0][1]
        assert records[0]["run_id"] == "my_run"

    @patch("modules.db_writer.factor_writer.create_engine")
    def test_write_converts_nan_to_none(self, mock_engine_cls):
        writer, mock_conn = _make_writer(mock_engine_cls)
        df = _sample_df()
        df.loc[0, "z_dy"] = float("nan")
        writer.write(df)
        records = mock_conn.execute.call_args[0][1]
        assert records[0]["z_dy"] is None

    @patch("modules.db_writer.factor_writer.create_engine")
    def test_write_converts_inf_to_none(self, mock_engine_cls):
        writer, mock_conn = _make_writer(mock_engine_cls)
        df = _sample_df()
        df.loc[0, "bp"] = float("inf")
        writer.write(df)
        records = mock_conn.execute.call_args[0][1]
        assert records[0]["bp"] is None

    @patch("modules.db_writer.factor_writer.create_engine")
    def test_write_does_not_mutate_input_dataframe(self, mock_engine_cls):
        writer, _ = _make_writer(mock_engine_cls)
        df = _sample_df()
        original_cols = set(df.columns)
        writer.write(df)
        assert set(df.columns) == original_cols
        assert "period_date" not in df.columns

    @patch("modules.db_writer.factor_writer.create_engine")
    def test_write_passes_correct_number_of_records(self, mock_engine_cls):
        writer, mock_conn = _make_writer(mock_engine_cls)
        df = pd.concat([_sample_df(), _sample_df()], ignore_index=True)
        df.loc[1, "symbol"] = "MSFT"
        writer.write(df)
        records = mock_conn.execute.call_args[0][1]
        assert len(records) == 2
