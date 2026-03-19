"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Configuration reader and CLI argument parser
Project : CW1 - Value + News Sentiment Strategy

Reads pipeline configuration from config/conf.yaml using
ift_global.ReadConfig and parses CLI arguments for flexible
execution frequency (daily, weekly, monthly, quarterly).

Follows the teaching material pattern from
Scripts/Python/2_ETL_Mongodb_SQL/modules/utils/args_parser.py
"""

import argparse
import datetime


def arg_parse_cmd() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Supports:
      --env_type      : dev | docker (required)
      --frequency     : daily | weekly | monthly | quarterly
      --lookback_years: 2 | 5 | 6 | 10 (default: 5)
      --run_date      : override date in YYYY-MM-DD format
      --sources       : data sources to run
      --tickers       : specific tickers to process
      --batch_size    : override batch size from config
      --dry_run       : validate config without downloading
      --init_schema   : re-create database tables before run

    :return: Configured argparse.ArgumentParser
    :rtype: argparse.ArgumentParser

    Example::

        >>> parser = arg_parse_cmd()
        >>> args = parser.parse_args(['--env_type', 'dev'])
        >>> args.env_type
        'dev'
    """
    parser = argparse.ArgumentParser(description="CW1 Value + Sentiment Pipeline — UCL IFT Big Data")
    parser.add_argument(
        "--env_type",
        type=str,
        required=True,
        choices=["dev", "docker"],
        help="Environment: dev (local) or docker (container)",
    )
    parser.add_argument(
        "--frequency",
        type=str,
        required=False,
        default="weekly",
        choices=["daily", "weekly", "monthly", "quarterly"],
        help="Run frequency controlling lookback window",
    )
    parser.add_argument(
        "--lookback_years",
        type=int,
        required=False,
        default=None,
        choices=[2, 5, 6, 10],
        help="Historical data lookback period in years (default: 5). Overrides config value.",
    )
    parser.add_argument(
        "--run_date",
        required=False,
        default=None,
        help="Reference date in YYYY-MM-DD format (default: today)",
        type=lambda d: datetime.datetime.strptime(d, "%Y-%m-%d").date() if d else None,
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        required=False,
        default=["financials", "prices", "news", "fx"],
        help="Data sources to run: financials prices news fx",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        required=False,
        default=None,
        help="Specific tickers to process (default: full universe)",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        required=False,
        default=None,
        help="Override batch size from config",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        default=False,
        help="Validate configuration only — no downloads",
    )
    parser.add_argument(
        "--init_schema",
        action="store_true",
        default=False,
        help="Re-create database schema before running",
    )
    return parser


def compute_date_range(frequency: str, lookback_years: int = 5, run_date: datetime.date = None) -> tuple:
    """Compute start and end dates from frequency + lookback.

    For initial or quarterly runs, uses the full lookback window.
    For daily/weekly/monthly runs, uses a shorter window suitable
    for incremental updates.

    :param frequency: Run frequency (daily, weekly, monthly, quarterly)
    :type frequency: str
    :param lookback_years: Default lookback in years from config
    :type lookback_years: int
    :param run_date: Reference end date (default: today)
    :type run_date: datetime.date or None
    :return: (start_date, end_date) as strings in YYYY-MM-DD format
    :rtype: tuple[str, str]

    Example::

        >>> start, end = compute_date_range('weekly', 5)
        >>> len(start)
        10
    """
    end = run_date or datetime.date.today()
    # Quarterly uses the full lookback window (at least 5 years per spec).
    # Daily/weekly/monthly use shorter incremental windows.
    frequency_lookback = {
        "daily": datetime.timedelta(days=7),
        "weekly": datetime.timedelta(days=14),
        "monthly": datetime.timedelta(days=35),
    }
    if frequency in frequency_lookback:
        start = end - frequency_lookback[frequency]
    else:
        # quarterly and any other frequency → full lookback
        start = end.replace(year=end.year - lookback_years)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
