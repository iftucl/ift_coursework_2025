"""
Tests for configuration, argument parsing, and utility modules.
"""

from datetime import date
from unittest.mock import patch

import pytest


class TestArgParser:
    """Tests for CLI argument parsing."""

    def test_required_env_type_dev(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev"])
        assert args.env_type == "dev"

    def test_required_env_type_docker(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "docker"])
        assert args.env_type == "docker"

    def test_default_frequency(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev"])
        assert args.frequency == "weekly"

    def test_custom_frequency_daily(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--frequency", "daily"])
        assert args.frequency == "daily"

    def test_custom_frequency_monthly(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--frequency", "monthly"])
        assert args.frequency == "monthly"

    def test_custom_frequency_quarterly(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--frequency", "quarterly"])
        assert args.frequency == "quarterly"

    def test_default_sources(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev"])
        assert args.sources == ["financials", "prices", "news", "fx"]

    def test_custom_sources(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--sources", "prices", "news"])
        assert args.sources == ["prices", "news"]

    def test_tickers_override(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--tickers", "AAPL", "MSFT"])
        assert args.tickers == ["AAPL", "MSFT"]

    def test_batch_size_override(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--batch_size", "25"])
        assert args.batch_size == 25

    def test_dry_run_flag(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--dry_run"])
        assert args.dry_run is True

    def test_init_schema_flag(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--init_schema"])
        assert args.init_schema is True

    def test_run_date_override(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--run_date", "2024-06-15"])
        assert args.run_date == date(2024, 6, 15)

    def test_default_lookback_years_is_none(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev"])
        assert args.lookback_years is None

    def test_lookback_years_5(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--lookback_years", "5"])
        assert args.lookback_years == 5

    def test_lookback_years_2(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--lookback_years", "2"])
        assert args.lookback_years == 2

    def test_lookback_years_6(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--lookback_years", "6"])
        assert args.lookback_years == 6

    def test_lookback_years_10(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        args = parser.parse_args(["--env_type", "dev", "--lookback_years", "10"])
        assert args.lookback_years == 10

    def test_invalid_lookback_years_rejected(self):
        from modules.utils.config_reader import arg_parse_cmd

        parser = arg_parse_cmd()
        with pytest.raises(SystemExit):
            parser.parse_args(["--env_type", "dev", "--lookback_years", "3"])


class TestDateRange:
    """Tests for date range computation."""

    def test_daily_lookback(self):
        from modules.utils.config_reader import compute_date_range

        start, end = compute_date_range("daily", 5, date(2025, 1, 15))
        assert end == "2025-01-15"
        assert start == "2025-01-08"

    def test_weekly_lookback(self):
        from modules.utils.config_reader import compute_date_range

        start, end = compute_date_range("weekly", 5, date(2025, 1, 15))
        assert end == "2025-01-15"
        assert start == "2025-01-01"

    def test_monthly_lookback(self):
        from modules.utils.config_reader import compute_date_range

        start, end = compute_date_range("monthly", 5, date(2025, 3, 1))
        assert end == "2025-03-01"
        assert start == "2025-01-25"

    def test_quarterly_lookback(self):
        from modules.utils.config_reader import compute_date_range

        start, end = compute_date_range("quarterly", 5, date(2025, 6, 1))
        assert end == "2025-06-01"
        assert start == "2020-06-01"  # Full 5-year lookback

    def test_default_run_date_is_today(self):
        from modules.utils.config_reader import compute_date_range

        _, end = compute_date_range("weekly", 5)
        assert end == date.today().strftime("%Y-%m-%d")

    def test_quarterly_2year_lookback(self):
        from modules.utils.config_reader import compute_date_range

        start, end = compute_date_range("quarterly", 2, date(2025, 6, 1))
        assert end == "2025-06-01"
        assert start == "2023-06-01"

    def test_quarterly_6year_lookback(self):
        from modules.utils.config_reader import compute_date_range

        start, end = compute_date_range("quarterly", 6, date(2025, 6, 1))
        assert end == "2025-06-01"
        assert start == "2019-06-01"

    def test_quarterly_10year_lookback(self):
        from modules.utils.config_reader import compute_date_range

        start, end = compute_date_range("quarterly", 10, date(2025, 6, 1))
        assert end == "2025-06-01"
        assert start == "2015-06-01"

    def test_date_format(self):
        from modules.utils.config_reader import compute_date_range

        start, end = compute_date_range("daily", 5, date(2025, 1, 1))
        assert len(start) == 10
        assert "-" in start


class TestRunIdGeneration:
    """Tests for pipeline run ID generation."""

    def test_run_id_is_string(self):
        from modules.utils.logger import generate_run_id

        rid = generate_run_id()
        assert isinstance(rid, str)

    def test_run_id_is_uuid_format(self):
        from modules.utils.logger import generate_run_id

        rid = generate_run_id()
        parts = rid.split("-")
        assert len(parts) == 5

    def test_run_ids_are_unique(self):
        from modules.utils.logger import generate_run_id

        ids = {generate_run_id() for _ in range(100)}
        assert len(ids) == 100


class TestPostgresConfig:
    """Tests for PostgresConfig Pydantic model."""

    def test_direct_values(self):
        from modules.db.postgres_connection import PostgresConfig

        cfg = PostgresConfig(username="user", password="pass", host="h", port="5432", database="db")
        assert cfg.username == "user"
        assert cfg.password == "pass"

    def test_env_fallback(self):
        from modules.db.postgres_connection import PostgresConfig

        with patch.dict("os.environ", {"POSTGRES_USERNAME": "envuser", "POSTGRES_PASSWORD": "envpass"}):
            cfg = PostgresConfig()
            assert cfg.username == "envuser"
            assert cfg.password == "envpass"

    def test_default_database(self):
        from modules.db.postgres_connection import PostgresConfig

        with patch.dict("os.environ", {}, clear=True):
            cfg = PostgresConfig(username="u", password="p", host="h", port="5432")
            assert cfg.database == "fift"
