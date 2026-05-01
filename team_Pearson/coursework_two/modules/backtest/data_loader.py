from __future__ import annotations

"""Database-backed data access helpers for the CW2 backtest engine."""

import logging
import re
from copy import deepcopy
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from team_Pearson.coursework_two.modules.feature.composite_alpha import compute_composite_alpha
from team_Pearson.coursework_two.modules.feature.factor_engine import (
    aggregate_factor_scores_from_sub_records,
)
from team_Pearson.coursework_two.modules.portfolio.construction import build_portfolio_targets
from team_Pearson.coursework_two.modules.risk.covariance import (
    build_return_panel,
    covariance_method_label,
    covariance_quality,
    estimate_fundamental_factor_covariance,
    estimate_shrunk_covariance,
    is_factor_covariance_method,
    is_fundamental_covariance_method,
    lookback_start,
)

logger = logging.getLogger(__name__)

_SCHEMA = "systematic_equity"
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PRICE_FACTOR_NAME = "adjusted_close_price"
_VIX_FACTOR_NAME = "vix_close"
_UST10Y_FACTOR_NAME = "us_treasury_10y"
_UST3M_FACTOR_NAME = "us_treasury_3m"
_RAW_CLOSE_FACTOR_NAME = "close_price"
_DAILY_VOLUME_FACTOR_NAME = "daily_volume"
_FUNDAMENTAL_EXPOSURE_FACTOR_NAMES = [
    "beta_1y",
    "log_market_cap",
    "liquidity_20d",
    "volatility_20d",
    "volatility_60d",
    "pb_ratio",
    "book_to_price",
    "ep_ratio",
    "earnings_to_price",
    "ebitda_to_ev",
    "momentum_1m",
    "momentum_3m",
    "momentum_6m",
    "momentum_12m",
    "momentum_12_1m",
    "ebitda_margin",
    "roe",
    "debt_to_equity",
    "debt_to_equity_inv",
    "dividend_yield",
    "dividend_stability",
    "payout_ratio",
    "payout_sustainability",
]


def _validated_identifier(value: str) -> str:
    candidate = str(value).strip()
    if not _VALID_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return candidate


_SAFE_SCHEMA = _validated_identifier(_SCHEMA)


def _pit_publish_cutoff_predicate(
    cutoff_param: str, *, observation_column: str = "observation_date"
) -> str:
    cutoff_param = str(cutoff_param).strip()
    observation_column = str(observation_column).strip()
    if not cutoff_param or not observation_column:
        raise ValueError("publish cutoff predicate requires cutoff_param and observation_column")
    return f"COALESCE(publish_date, {observation_column}) <= :{cutoff_param}"


def load_signals(engine: Engine, as_of_date: date, portfolio_name: str) -> List[Dict[str, Any]]:
    """Load the latest PIT-clean signal snapshot on or before ``as_of_date``."""
    sql = text(f"""
        WITH latest_snapshot AS (
            SELECT MAX(as_of_date) AS snapshot_as_of_date
            FROM {_SAFE_SCHEMA}.portfolio_target_positions
            WHERE portfolio_name = :portfolio_name
              AND as_of_date <= :as_of_date
              AND COALESCE(target_weight, 0) > 0
        )
        SELECT
            symbol,
            as_of_date,
            target_weight,
            composite_alpha,
            regime,
            gics_sector,
            selection_rank,
            weighting_scheme
        FROM {_SAFE_SCHEMA}.portfolio_target_positions
        WHERE as_of_date = (SELECT snapshot_as_of_date FROM latest_snapshot)
          AND portfolio_name = :portfolio_name
          AND COALESCE(target_weight, 0) > 0
        ORDER BY selection_rank NULLS LAST, symbol
        """)  # nosec B608
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sql,
                {"as_of_date": as_of_date, "portfolio_name": portfolio_name},
            )
            .mappings()
            .all()
        )

    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "symbol": str(row["symbol"]),
                "as_of_date": row.get("as_of_date"),
                "target_weight": _safe_float(row["target_weight"]),
                "composite_alpha": _safe_float(row["composite_alpha"]),
                "regime": row.get("regime"),
                "gics_sector": row.get("gics_sector"),
                "selection_rank": row.get("selection_rank"),
                "weighting_scheme": row.get("weighting_scheme"),
            }
        )
    return [row for row in out if row["target_weight"] is not None]


def load_signal_snapshot_counts(
    engine: Engine,
    *,
    portfolio_name: str,
    start_date: date,
    end_date: date,
) -> Dict[date, int]:
    """Return per-date signal row counts for a portfolio within a date window."""
    sql = text(f"""
        SELECT as_of_date, COUNT(*) AS row_count
        FROM {_SAFE_SCHEMA}.portfolio_target_positions
        WHERE portfolio_name = :portfolio_name
          AND as_of_date BETWEEN :start_date AND :end_date
          AND COALESCE(target_weight, 0) > 0
        GROUP BY as_of_date
        ORDER BY as_of_date
        """)  # nosec B608
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sql,
                {
                    "portfolio_name": portfolio_name,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            .mappings()
            .all()
        )
    return {row["as_of_date"]: int(row["row_count"]) for row in rows}


def align_signal_snapshot_counts(
    signal_counts: Dict[date, int],
    rebalance_dates: Sequence[date],
) -> Dict[date, Dict[str, Any]]:
    """Map each rebalance date to the latest available signal snapshot on or before it."""
    available_dates = sorted(signal_counts)
    aligned: Dict[date, Dict[str, Any]] = {}
    latest_idx = -1

    for rebalance_date in sorted({dt for dt in rebalance_dates if dt is not None}):
        while (
            latest_idx + 1 < len(available_dates)
            and available_dates[latest_idx + 1] <= rebalance_date
        ):
            latest_idx += 1
        if latest_idx >= 0:
            snapshot_date = available_dates[latest_idx]
            aligned[rebalance_date] = {
                "snapshot_as_of_date": snapshot_date,
                "count": int(signal_counts[snapshot_date]),
            }
        else:
            aligned[rebalance_date] = {
                "snapshot_as_of_date": None,
                "count": 0,
            }
    return aligned


def load_adjusted_close_prices(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    lookback_days: int = 7,
) -> pd.DataFrame:
    """Load adjusted close prices from ``factor_observations`` as a date-symbol panel."""
    clean_symbols = sorted({str(sym).strip() for sym in symbols if str(sym).strip()})
    if not clean_symbols:
        return pd.DataFrame()

    lookback_start = start_date - timedelta(days=max(10, lookback_days * 3))
    sql = text(f"""
        SELECT symbol, observation_date, factor_value
        FROM {_SAFE_SCHEMA}.factor_observations
        WHERE factor_name = :factor_name
          AND symbol = ANY(:symbols)
          AND observation_date BETWEEN :lookback_start AND :end_date
          AND {_pit_publish_cutoff_predicate("end_date")}
        ORDER BY observation_date, symbol
        """)  # nosec B608
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "factor_name": _PRICE_FACTOR_NAME,
                "symbols": clean_symbols,
                "lookback_start": lookback_start,
                "end_date": end_date,
            },
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if df.empty:
        return pd.DataFrame(columns=clean_symbols)

    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce").dt.date
    df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")
    panel = df.pivot_table(
        index="observation_date",
        columns="symbol",
        values="factor_value",
        aggfunc="last",
    ).sort_index()
    return panel


def load_fundamental_exposure_observations(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    max_staleness_days: int = 540,
    factor_names: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Load PIT-available raw descriptors for a fundamental factor risk model."""
    clean_symbols = sorted({str(sym).strip() for sym in symbols if str(sym).strip()})
    if not clean_symbols:
        return pd.DataFrame()

    requested_factors = sorted(
        {
            str(name).strip()
            for name in (factor_names or _FUNDAMENTAL_EXPOSURE_FACTOR_NAMES)
            if str(name).strip()
        }
    )
    if not requested_factors:
        return pd.DataFrame()

    lookback_start = start_date - timedelta(days=max(0, int(max_staleness_days)))
    factor_sql = text(f"""
        SELECT
            symbol,
            GREATEST(observation_date, COALESCE(publish_date, observation_date)) AS as_of_date,
            observation_date,
            factor_name,
            factor_value
        FROM {_SAFE_SCHEMA}.factor_observations
        WHERE symbol = ANY(:symbols)
          AND factor_name = ANY(:factor_names)
          AND observation_date BETWEEN :lookback_start AND :end_date
          AND {_pit_publish_cutoff_predicate("end_date")}
        ORDER BY symbol, as_of_date, factor_name
        """)  # nosec B608
    sector_sql = text(f"""
        SELECT symbol, COALESCE(gics_sector, 'Unknown') AS gics_sector
        FROM {_SAFE_SCHEMA}.company_static
        WHERE symbol = ANY(:symbols)
        """)  # nosec B608
    with engine.connect() as conn:
        factor_rows = conn.execute(
            factor_sql,
            {
                "symbols": clean_symbols,
                "factor_names": requested_factors,
                "lookback_start": lookback_start,
                "end_date": end_date,
            },
        )
        factor_df = pd.DataFrame(factor_rows.fetchall(), columns=factor_rows.keys())
        try:
            sector_rows = conn.execute(sector_sql, {"symbols": clean_symbols})
            sector_df = pd.DataFrame(sector_rows.fetchall(), columns=sector_rows.keys())
        except Exception as exc:  # pragma: no cover - depends on runtime schema state
            logger.debug("fundamental exposure sector lookup skipped: %s", exc)
            sector_df = pd.DataFrame(columns=["symbol", "gics_sector"])

    if factor_df.empty:
        return pd.DataFrame()

    factor_df["symbol"] = factor_df["symbol"].astype(str)
    factor_df["as_of_date"] = pd.to_datetime(factor_df["as_of_date"], errors="coerce").dt.date
    factor_df["observation_date"] = pd.to_datetime(
        factor_df["observation_date"], errors="coerce"
    ).dt.date
    factor_df["factor_value"] = pd.to_numeric(factor_df["factor_value"], errors="coerce")
    factor_df = factor_df.dropna(subset=["as_of_date", "factor_value"])
    if factor_df.empty:
        return pd.DataFrame()

    sector_map = (
        {
            str(row["symbol"]): str(row.get("gics_sector") or "Unknown")
            for row in sector_df.to_dict(orient="records")
        }
        if not sector_df.empty
        else {}
    )
    factor_df["gics_sector"] = factor_df["symbol"].map(sector_map).fillna("Unknown")
    return factor_df


def load_sector_map(engine: Engine) -> Dict[str, str]:
    """Load static GICS sectors for risk modelling."""
    sql = text(f"""
        SELECT symbol, COALESCE(gics_sector, 'Unknown') AS gics_sector
        FROM {_SAFE_SCHEMA}.company_static
        """)  # nosec B608
    with engine.connect() as conn:
        try:
            rows = conn.execute(sql).mappings().all()
        except Exception as exc:  # pragma: no cover - depends on runtime schema state
            logger.debug("sector map lookup failed: %s", exc)
            return {}
    return {str(row["symbol"]): str(row["gics_sector"]) for row in rows}


def load_open_prices(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    lookback_days: int = 7,
) -> pd.DataFrame:
    """Load adjusted-open prices aligned with adjusted close total-return semantics."""
    return _load_adjusted_derived_price_panel(
        engine,
        symbols,
        start_date,
        end_date,
        raw_factor_name="open_price",
        lookback_days=lookback_days,
    )


def load_daily_volumes(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    lookback_days: int = 20,
) -> pd.DataFrame:
    """Load daily share volume history for capacity and slippage estimation."""
    return _load_factor_panel(
        engine,
        symbols,
        start_date,
        end_date,
        factor_name=_DAILY_VOLUME_FACTOR_NAME,
        lookback_days=lookback_days,
    )


def load_factor_panel(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    factor_name: str,
    lookback_days: int = 0,
) -> pd.DataFrame:
    """Load an arbitrary factor_observations panel for symbol-level daily signals."""
    return _load_factor_panel(
        engine,
        symbols,
        start_date,
        end_date,
        factor_name=factor_name,
        lookback_days=lookback_days,
    )


def load_high_prices(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    lookback_days: int = 7,
) -> pd.DataFrame:
    """Load adjusted-high prices aligned with adjusted close total-return semantics."""
    return _load_adjusted_derived_price_panel(
        engine,
        symbols,
        start_date,
        end_date,
        raw_factor_name="high_price",
        lookback_days=lookback_days,
    )


def load_low_prices(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    lookback_days: int = 7,
) -> pd.DataFrame:
    """Load adjusted-low prices aligned with adjusted close total-return semantics."""
    return _load_adjusted_derived_price_panel(
        engine,
        symbols,
        start_date,
        end_date,
        raw_factor_name="low_price",
        lookback_days=lookback_days,
    )


def load_benchmark_prices(
    engine: Engine,
    ticker: str,
    start_date: date,
    end_date: date,
    *,
    lookback_days: int = 7,
) -> pd.Series:
    """Load benchmark adjusted-close-equivalent prices from ``benchmark_prices``.

    The CW1 benchmark loader stores yfinance ``history(auto_adjust=True)`` under
    ``close_price``, so this table is the canonical benchmark total-return proxy.
    """
    lookback_start = start_date - timedelta(days=max(10, lookback_days * 3))
    sql = text(f"""
        SELECT price_date, close_price
        FROM {_SAFE_SCHEMA}.benchmark_prices
        WHERE ticker = :ticker
          AND price_date BETWEEN :lookback_start AND :end_date
        ORDER BY price_date
        """)  # nosec B608
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"ticker": ticker, "lookback_start": lookback_start, "end_date": end_date},
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if df.empty:
        logger.warning(
            "backtest_loader: benchmark_prices missing for ticker=%s; trying factor_observations fallback",
            ticker,
        )
        fallback_sql = text(f"""
            SELECT observation_date AS price_date, factor_value AS close_price
            FROM {_SAFE_SCHEMA}.factor_observations
            WHERE symbol = :ticker
              AND factor_name = :factor_name
              AND observation_date BETWEEN :lookback_start AND :end_date
              AND {_pit_publish_cutoff_predicate("end_date")}
            ORDER BY observation_date
            """)  # nosec B608
        with engine.connect() as conn:
            rows = conn.execute(
                fallback_sql,
                {
                    "ticker": ticker,
                    "factor_name": _PRICE_FACTOR_NAME,
                    "lookback_start": lookback_start,
                    "end_date": end_date,
                },
            )
            df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if df.empty:
        return pd.Series(dtype=float)

    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce").dt.date
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    return df.dropna(subset=["price_date"]).set_index("price_date")["close_price"].sort_index()


def load_trading_calendar(
    engine: Engine,
    start_date: date,
    end_date: date,
    *,
    benchmark_ticker: Optional[str] = None,
) -> List[date]:
    """Load an observed US trading calendar from independent reference datasets.

    The benchmark series is intentionally used only as a fallback. Otherwise a
    sparse benchmark could silently define the calendar and hide benchmark-date
    gaps that should instead be surfaced by pre-flight validation.
    """
    primary_queries = [
        (
            text(f"""
                SELECT observation_date AS trading_date
                FROM {_SAFE_SCHEMA}.factor_observations
                WHERE symbol = '_MACRO'
                  AND factor_name = :factor_name
                  AND observation_date BETWEEN :start_date AND :end_date
                  AND {_pit_publish_cutoff_predicate("end_date")}
                ORDER BY observation_date
                """),  # nosec B608
            {
                "factor_name": _VIX_FACTOR_NAME,
                "start_date": start_date,
                "end_date": end_date,
            },
        ),
        (
            text(f"""
                SELECT DISTINCT observation_date AS trading_date
                FROM {_SAFE_SCHEMA}.factor_observations
                WHERE factor_name = :factor_name
                  AND observation_date BETWEEN :start_date AND :end_date
                  AND {_pit_publish_cutoff_predicate("end_date")}
                ORDER BY trading_date
                """),  # nosec B608
            {
                "factor_name": _PRICE_FACTOR_NAME,
                "start_date": start_date,
                "end_date": end_date,
            },
        ),
    ]
    benchmark_query = None
    if benchmark_ticker:
        benchmark_query = (
            text(f"""
                SELECT price_date AS trading_date
                FROM {_SAFE_SCHEMA}.benchmark_prices
                WHERE ticker = :ticker
                  AND price_date BETWEEN :start_date AND :end_date
                ORDER BY price_date
                """),  # nosec B608
            {
                "ticker": benchmark_ticker,
                "start_date": start_date,
                "end_date": end_date,
            },
        )

    with engine.connect() as conn:
        observed_days: set[date] = set()
        for sql, params in primary_queries:
            rows = conn.execute(sql, params).mappings().all()
            if rows:
                observed_days.update(
                    {
                        pd.to_datetime(row["trading_date"], errors="coerce").date()
                        for row in rows
                        if row.get("trading_date") is not None
                    }
                )
        if observed_days:
            return sorted(observed_days)

        if benchmark_query is not None:
            sql, params = benchmark_query
            rows = conn.execute(sql, params).mappings().all()
            if rows:
                return sorted(
                    {
                        pd.to_datetime(row["trading_date"], errors="coerce").date()
                        for row in rows
                        if row.get("trading_date") is not None
                    }
                )
    return []


def get_month_end_trading_days(trading_days: Sequence[date]) -> List[date]:
    """Return the last observed trading day of each calendar month."""
    month_end: Dict[tuple[int, int], date] = {}
    for dt in sorted({d for d in trading_days if d is not None}):
        month_end[(dt.year, dt.month)] = dt
    return [month_end[key] for key in sorted(month_end)]


def shift_trading_day(trading_days: Sequence[date], anchor_date: date, offset: int) -> date:
    """Shift forward by ``offset`` observed trading days from ``anchor_date``."""
    ordered = sorted({d for d in trading_days if d is not None})
    if anchor_date not in ordered:
        raise ValueError(f"Anchor date {anchor_date} is not present in the trading calendar")
    idx = ordered.index(anchor_date) + int(offset)
    if idx >= len(ordered):
        raise ValueError(f"Cannot shift trading date {anchor_date} by {offset}: calendar exhausted")
    return ordered[idx]


def load_vix_level(engine: Engine, as_of_date: date) -> Optional[float]:
    """Load the latest available VIX close on or before ``as_of_date``."""
    sql = text(f"""
        SELECT factor_value
        FROM {_SAFE_SCHEMA}.factor_observations
        WHERE symbol = '_MACRO'
          AND factor_name = :factor_name
          AND observation_date <= :as_of_date
        ORDER BY observation_date DESC
        LIMIT 1
        """)  # nosec B608
    with engine.connect() as conn:
        row = (
            conn.execute(
                sql,
                {"factor_name": _VIX_FACTOR_NAME, "as_of_date": as_of_date},
            )
            .mappings()
            .first()
        )
    return _safe_float(row["factor_value"]) if row else None


def load_vix_series(
    engine: Engine,
    start_date: date,
    end_date: date,
) -> pd.Series:
    """Load a daily VIX close series for trigger monitoring."""
    sql = text(f"""
        SELECT observation_date, factor_value
        FROM {_SAFE_SCHEMA}.factor_observations
        WHERE symbol = '_MACRO'
          AND factor_name = :factor_name
          AND observation_date BETWEEN :start_date AND :end_date
          AND {_pit_publish_cutoff_predicate("end_date")}
        ORDER BY observation_date
        """)  # nosec B608
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "factor_name": _VIX_FACTOR_NAME,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())
    if df.empty:
        return pd.Series(dtype=float)
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce").dt.date
    df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")
    return (
        df.dropna(subset=["observation_date"])
        .set_index("observation_date")["factor_value"]
        .sort_index()
    )


def load_macro_series(
    engine: Engine,
    factor_name: str,
    start_date: date,
    end_date: date,
) -> pd.Series:
    """Load a daily macro factor series from ``factor_observations``."""
    sql = text(f"""
        SELECT observation_date, factor_value
        FROM {_SAFE_SCHEMA}.factor_observations
        WHERE symbol = '_MACRO'
          AND factor_name = :factor_name
          AND observation_date BETWEEN :start_date AND :end_date
          AND {_pit_publish_cutoff_predicate("end_date")}
        ORDER BY observation_date
        """)  # nosec B608
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "factor_name": factor_name,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())
    if df.empty:
        return pd.Series(dtype=float)
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce").dt.date
    df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")
    return (
        df.dropna(subset=["observation_date"])
        .set_index("observation_date")["factor_value"]
        .sort_index()
    )


def load_term_spread_series(
    engine: Engine,
    start_date: date,
    end_date: date,
) -> pd.Series:
    """Load a daily 10Y-3M Treasury term-spread series for regime confirmation."""
    ten_year = load_macro_series(engine, _UST10Y_FACTOR_NAME, start_date, end_date)
    three_month = load_macro_series(engine, _UST3M_FACTOR_NAME, start_date, end_date)
    if ten_year.empty or three_month.empty:
        return pd.Series(dtype=float)
    aligned = pd.concat(
        [
            pd.to_numeric(ten_year, errors="coerce").rename("ten_year"),
            pd.to_numeric(three_month, errors="coerce").rename("three_month"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    return (aligned["ten_year"] - aligned["three_month"]).sort_index()


def load_risk_free_period_returns(
    engine: Engine,
    periods: Sequence[Dict[str, Any]],
) -> Dict[date, float]:
    """Return period-aligned risk-free returns from the daily ``us_treasury_3m`` yield.

    The stored macro factor is the annualized percentage yield. For each holding
    window ``(execution_date, period_end_date]`` we forward-fill the latest available
    yield across calendar days and convert it into a compounded period return.
    """
    clean_periods = [
        {
            "execution_date": period.get("execution_date"),
            "period_end_date": period.get("period_end_date"),
        }
        for period in periods
        if period.get("execution_date") is not None and period.get("period_end_date") is not None
    ]
    if not clean_periods:
        return {}

    start_date = min(period["execution_date"] for period in clean_periods) - timedelta(days=14)
    end_date = max(period["period_end_date"] for period in clean_periods)
    raw_yield = load_macro_series(engine, _UST3M_FACTOR_NAME, start_date, end_date)
    if raw_yield.empty:
        return {
            period["period_end_date"]: 0.0
            for period in clean_periods
            if period["period_end_date"] is not None
        }

    annualized_yield = pd.to_numeric(raw_yield, errors="coerce").dropna() / 100.0
    if annualized_yield.empty:
        return {
            period["period_end_date"]: 0.0
            for period in clean_periods
            if period["period_end_date"] is not None
        }

    calendar_index = [
        ts.date()
        for ts in pd.date_range(
            min(period["execution_date"] for period in clean_periods),
            end_date,
            freq="D",
        )
    ]
    daily_yield = annualized_yield.reindex(calendar_index).ffill().bfill()

    out: Dict[date, float] = {}
    for period in clean_periods:
        execution_date = period["execution_date"]
        period_end_date = period["period_end_date"]
        accrual_days = [
            ts.date()
            for ts in pd.date_range(
                execution_date,
                period_end_date,
                freq="D",
                inclusive="right",
            )
        ]
        if not accrual_days:
            out[period_end_date] = 0.0
            continue
        period_yield = daily_yield.reindex(accrual_days).ffill().bfill()
        if period_yield.empty or period_yield.isna().all():
            out[period_end_date] = 0.0
            continue
        daily_rf = np.power(1.0 + period_yield.to_numpy(dtype=float), 1.0 / 365.25) - 1.0
        out[period_end_date] = float(np.prod(1.0 + daily_rf) - 1.0)
    return out


def load_regime_target_maps(
    engine: Engine,
    as_of_date: date,
    portfolio_name: str,
    *,
    config: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, float], Dict[str, float]]:
    """Rebuild same-snapshot normal/stress target weights for intraperiod regime switching."""
    cfg = deepcopy(config or _load_cw2_config())
    bundle = _load_feature_bundle_for_date(engine, as_of_date)
    factor_scores = bundle["factor_scores"]
    if not factor_scores:
        return {}, {}
    sub_scores = bundle.get("sub_scores") or []

    company_info = bundle["company_info"]
    risk_overlay = bundle["risk_overlay"]
    universe_screen = bundle["universe_screen"]
    covariance_matrix, covariance_meta = _build_portfolio_covariance_context(
        engine,
        as_of_date,
        [str(row.get("symbol")) for row in factor_scores],
        cfg,
    )

    normal_cfg = _forced_regime_config(cfg, portfolio_name=portfolio_name, forced_regime="normal")
    stress_cfg = _forced_regime_config(cfg, portfolio_name=portfolio_name, forced_regime="stress")

    if sub_scores:
        normal_base_scores = aggregate_factor_scores_from_sub_records(
            [dict(row) for row in sub_scores],
            config=normal_cfg,
            regime="normal",
        )
        stress_base_scores = aggregate_factor_scores_from_sub_records(
            [dict(row) for row in sub_scores],
            config=stress_cfg,
            regime="stress",
        )
    else:
        normal_base_scores = [dict(row) for row in factor_scores]
        stress_base_scores = [dict(row) for row in factor_scores]

    for row in normal_base_scores:
        if not row.get("as_of_date"):
            row["as_of_date"] = as_of_date
    for row in stress_base_scores:
        if not row.get("as_of_date"):
            row["as_of_date"] = as_of_date

    normal_scores = compute_composite_alpha(
        normal_base_scores,
        vix_level=0.0,
        config=normal_cfg,
        forced_regime="normal",
    )
    stress_scores = compute_composite_alpha(
        stress_base_scores,
        vix_level=999.0,
        config=stress_cfg,
        forced_regime="stress",
    )

    normal_targets = build_portfolio_targets(
        normal_scores,
        risk_overlay,
        universe_screen,
        company_info,
        covariance_matrix=covariance_matrix,
        covariance_meta=covariance_meta,
        previous_positions=None,
        config=normal_cfg,
    )
    stress_targets = build_portfolio_targets(
        stress_scores,
        risk_overlay,
        universe_screen,
        company_info,
        covariance_matrix=covariance_matrix,
        covariance_meta=covariance_meta,
        previous_positions=None,
        config=stress_cfg,
    )

    return (
        {
            str(row["symbol"]): float(row["target_weight"])
            for row in normal_targets
            if row.get("target_weight") is not None
        },
        {
            str(row["symbol"]): float(row["target_weight"])
            for row in stress_targets
            if row.get("target_weight") is not None
        },
    )


def _load_adjusted_derived_price_panel(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    raw_factor_name: str,
    lookback_days: int,
) -> pd.DataFrame:
    raw_panel = _load_factor_panel(
        engine,
        symbols,
        start_date,
        end_date,
        factor_name=raw_factor_name,
        lookback_days=lookback_days,
    )
    close_panel = _load_factor_panel(
        engine,
        symbols,
        start_date,
        end_date,
        factor_name=_RAW_CLOSE_FACTOR_NAME,
        lookback_days=lookback_days,
    )
    adj_close_panel = load_adjusted_close_prices(
        engine,
        symbols,
        start_date,
        end_date,
        lookback_days=lookback_days,
    )
    if raw_panel.empty or adj_close_panel.empty:
        return pd.DataFrame(
            columns=sorted({*raw_panel.columns, *close_panel.columns, *adj_close_panel.columns})
        )

    panel = raw_panel.reindex_like(adj_close_panel)
    if close_panel.empty:
        # CW1 Source A stores OHLC from ``yfinance.history(auto_adjust=True)``, so
        # open/high/low are already on the adjusted-close total-return basis even
        # when raw ``close_price`` is not persisted in ``factor_observations``.
        return panel

    close_aligned = close_panel.reindex_like(adj_close_panel)
    if close_aligned.dropna(how="all").empty:
        return panel
    adj_factor = adj_close_panel.divide(close_aligned.where(close_aligned != 0))
    adj_factor = adj_factor.replace([float("inf"), float("-inf")], np.nan)
    adjusted = panel.multiply(adj_factor)
    if adjusted.dropna(how="all").empty and not panel.dropna(how="all").empty:
        logger.warning(
            "backtest_loader: derived adjusted price panel fell back to raw %s because close_price history was unusable",
            raw_factor_name,
        )
        return panel
    return adjusted


def _load_factor_panel(
    engine: Engine,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    *,
    factor_name: str,
    lookback_days: int,
) -> pd.DataFrame:
    clean_symbols = sorted(
        {str(sym).strip() for sym in symbols if str(sym).strip() and str(sym).strip() != "_CASH"}
    )
    if not clean_symbols:
        return pd.DataFrame()

    lookback_start = start_date - timedelta(days=max(10, lookback_days * 3))
    sql = text(f"""
        SELECT symbol, observation_date, factor_value
        FROM {_SAFE_SCHEMA}.factor_observations
        WHERE factor_name = :factor_name
          AND symbol = ANY(:symbols)
          AND observation_date BETWEEN :lookback_start AND :end_date
          AND {_pit_publish_cutoff_predicate("end_date")}
        ORDER BY observation_date, symbol
        """)  # nosec B608
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "factor_name": factor_name,
                "symbols": clean_symbols,
                "lookback_start": lookback_start,
                "end_date": end_date,
            },
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if df.empty:
        return pd.DataFrame(columns=clean_symbols)
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce").dt.date
    df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")
    return df.pivot_table(
        index="observation_date",
        columns="symbol",
        values="factor_value",
        aggfunc="last",
    ).sort_index()


def _load_feature_bundle_for_date(engine: Engine, as_of_date: date) -> Dict[str, Any]:
    sub_sql = text(f"""
        SELECT as_of_date, symbol, factor_group, sub_variable, z_score
        FROM {_SAFE_SCHEMA}.feature_sub_scores
        WHERE as_of_date = :as_of_date
        """)  # nosec B608
    factor_sql = text(f"""
        SELECT as_of_date, symbol, quality_score, value_score, market_technical_score,
               sentiment_score, dividend_score, composite_alpha, regime
        FROM {_SAFE_SCHEMA}.feature_factor_scores
        WHERE as_of_date = :as_of_date
        """)  # nosec B608
    risk_sql = text(f"""
        SELECT as_of_date, symbol, pass_all, volatility_60d, missing_factor_pct, factor_groups_present
        FROM {_SAFE_SCHEMA}.feature_risk_overlay
        WHERE as_of_date = :as_of_date
        """)  # nosec B608
    universe_sql = text(f"""
        SELECT as_of_date, symbol, pass_all, country, gics_sector, log_market_cap, liquidity_20d
        FROM {_SAFE_SCHEMA}.feature_universe_screen
        WHERE as_of_date = :as_of_date
        """)  # nosec B608
    company_sql = text(f"""
        SELECT symbol,
               NULLIF(TRIM(security), '') AS security,
               COALESCE(gics_sector, 'Unknown') AS gics_sector,
               country
        FROM {_SAFE_SCHEMA}.company_static
        """)  # nosec B608
    with engine.connect() as conn:
        sub_df = pd.DataFrame(conn.execute(sub_sql, {"as_of_date": as_of_date}).mappings().all())
        factor_df = pd.DataFrame(
            conn.execute(factor_sql, {"as_of_date": as_of_date}).mappings().all()
        )
        risk_df = pd.DataFrame(conn.execute(risk_sql, {"as_of_date": as_of_date}).mappings().all())
        universe_df = pd.DataFrame(
            conn.execute(universe_sql, {"as_of_date": as_of_date}).mappings().all()
        )
        company_df = pd.DataFrame(conn.execute(company_sql).mappings().all())

    company_map = (
        {
            str(row["symbol"]): {
                "security": row.get("security"),
                "gics_sector": row.get("gics_sector"),
                "country": row.get("country"),
            }
            for row in company_df.to_dict(orient="records")
        }
        if not company_df.empty
        else {}
    )

    return {
        "sub_scores": (
            sub_df.drop(columns=["as_of_date"], errors="ignore").to_dict(orient="records")
            if not sub_df.empty
            else []
        ),
        "factor_scores": (
            factor_df.drop(columns=["as_of_date"], errors="ignore").to_dict(orient="records")
            if not factor_df.empty
            else []
        ),
        "risk_overlay": (
            risk_df.drop(columns=["as_of_date"], errors="ignore").to_dict(orient="records")
            if not risk_df.empty
            else []
        ),
        "universe_screen": (
            universe_df.drop(columns=["as_of_date"], errors="ignore").to_dict(orient="records")
            if not universe_df.empty
            else []
        ),
        "company_info": company_map,
    }


def _forced_regime_config(
    config: Dict[str, Any],
    *,
    portfolio_name: str,
    forced_regime: str,
) -> Dict[str, Any]:
    cfg = deepcopy(config)
    regime_cfg = cfg.setdefault("regime", {})
    regime_cfg["mode"] = "threshold"
    regime_cfg["vix_stress_threshold"] = 25.0
    portfolio_cfg = cfg.setdefault("portfolio_construction", {})
    portfolio_cfg["portfolio_name"] = portfolio_name
    portfolio_cfg["turnover_cap"] = None
    if forced_regime == "normal":
        regime_cfg["stress"] = deepcopy(regime_cfg.get("normal", {}))
    elif forced_regime == "stress":
        regime_cfg["normal"] = deepcopy(regime_cfg.get("stress", {}))
    else:
        raise ValueError(f"Unsupported forced regime: {forced_regime}")
    return cfg


def _build_portfolio_covariance_context(
    engine: Engine,
    as_of_date: date,
    symbols: Sequence[str],
    config: Dict[str, Any],
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    portfolio_cfg = (config.get("portfolio_construction") or {}).get("covariance") or {}
    weighting_name = (
        str((config.get("portfolio_construction") or {}).get("weighting") or "equal")
        .strip()
        .lower()
    )
    if weighting_name != "mean_variance" and not bool(portfolio_cfg.get("always_build", False)):
        return pd.DataFrame(), {}

    clean_symbols = sorted(
        {str(sym).strip() for sym in symbols if str(sym).strip() and str(sym).strip() != "_CASH"}
    )
    if not clean_symbols:
        return pd.DataFrame(), {}

    lookback_days = max(60, int(portfolio_cfg.get("lookback_days", 252)))
    min_history_days = max(40, int(portfolio_cfg.get("min_history_days", 126)))
    shrinkage_intensity = float(portfolio_cfg.get("shrinkage_intensity", 0.25))
    covariance_method = str(portfolio_cfg.get("method", "diagonal_shrinkage"))
    covariance_method_key = covariance_method.strip().lower()
    factor_count = portfolio_cfg.get("factor_count", portfolio_cfg.get("n_factors"))
    max_factor_count = max(1, int(portfolio_cfg.get("max_factor_count", 5)))
    factor_variance_target_raw = portfolio_cfg.get("factor_variance_target")
    factor_variance_target = (
        None if factor_variance_target_raw is None else float(factor_variance_target_raw)
    )
    specific_variance_floor_ratio = float(portfolio_cfg.get("specific_variance_floor_ratio", 0.05))
    style_factors = portfolio_cfg.get("style_factors")
    include_sector_factors = bool(portfolio_cfg.get("include_sector_factors", True))
    exposure_lag_days = max(0, int(portfolio_cfg.get("exposure_lag_days", 1)))
    max_exposure_staleness_days = max(0, int(portfolio_cfg.get("max_exposure_staleness_days", 540)))
    min_factor_return_days = max(5, int(portfolio_cfg.get("min_factor_return_days", 40)))
    min_cross_section = max(3, int(portfolio_cfg.get("min_cross_section", 8)))
    min_sector_members = max(1, int(portfolio_cfg.get("min_sector_members", 2)))
    factor_ridge = float(portfolio_cfg.get("factor_ridge", 1.0e-4))
    factor_cov_shrinkage = float(portfolio_cfg.get("factor_cov_shrinkage", 0.10))
    fallback_to_statistical = bool(portfolio_cfg.get("fallback_to_statistical_factor", True))
    fallback_to_diagonal = bool(portfolio_cfg.get("fallback_to_diagonal_shrinkage", True))
    max_forward_fill_days = max(0, int(portfolio_cfg.get("max_forward_fill_days", 5)))
    benchmark_ticker = str((config.get("backtest") or {}).get("benchmark_ticker") or "SPY")

    trading_calendar = load_trading_calendar(
        engine,
        as_of_date - timedelta(days=max(lookback_days * 2, 550)),
        as_of_date,
        benchmark_ticker=benchmark_ticker,
    )
    if not trading_calendar:
        return pd.DataFrame(), {}

    start = lookback_start(trading_calendar, as_of_date, lookback_days, max_forward_fill_days)
    prices = load_adjusted_close_prices(
        engine,
        clean_symbols,
        start,
        as_of_date,
        lookback_days=max_forward_fill_days,
    )
    returns = build_return_panel(
        prices,
        trading_calendar=trading_calendar,
        start_date=start,
        end_date=as_of_date,
        lookback_days=lookback_days,
        min_history_days=min_history_days,
        max_forward_fill_days=max_forward_fill_days,
    )
    fundamental_meta: Dict[str, Any] = {}
    if is_fundamental_covariance_method(covariance_method_key):
        exposure_observations = load_fundamental_exposure_observations(
            engine,
            clean_symbols,
            start,
            as_of_date,
            max_staleness_days=max_exposure_staleness_days,
        )
        covariance, fundamental_meta = estimate_fundamental_factor_covariance(
            returns,
            exposure_observations,
            sector_map=load_sector_map(engine),
            style_factors=style_factors,
            include_sector_factors=include_sector_factors,
            exposure_lag_days=exposure_lag_days,
            max_exposure_staleness_days=max_exposure_staleness_days,
            min_cross_section=min_cross_section,
            min_factor_return_days=min_factor_return_days,
            min_sector_members=min_sector_members,
            factor_ridge=factor_ridge,
            factor_cov_shrinkage=factor_cov_shrinkage,
            specific_variance_floor_ratio=specific_variance_floor_ratio,
            return_metadata=True,
        )
    else:
        covariance = estimate_shrunk_covariance(
            returns,
            shrinkage_intensity=shrinkage_intensity,
            method=covariance_method,
            factor_count=None if factor_count is None else int(factor_count),
            max_factor_count=max_factor_count,
            factor_variance_target=factor_variance_target,
            specific_variance_floor_ratio=specific_variance_floor_ratio,
        )
    quality = covariance_quality(covariance)
    primary_quality = quality
    requested_method_label = covariance_method_label(covariance_method_key, shrinkage_intensity)
    meta = {
        "covariance_method": requested_method_label,
        "requested_covariance_method": requested_method_label,
        "lookback_days": lookback_days,
        "history_days": int(len(returns)),
        "covariance_is_usable": bool(quality.get("is_usable")),
        "covariance_reason": quality.get("reason"),
        "covariance_condition_number": quality.get("condition_number"),
        "covariance_fallback_used": False,
    }
    if is_factor_covariance_method(covariance_method_key):
        meta.update(
            {
                "factor_count": None if factor_count is None else int(factor_count),
                "max_factor_count": max_factor_count,
                "factor_variance_target": factor_variance_target,
                "specific_variance_floor_ratio": specific_variance_floor_ratio,
            }
        )
        if is_fundamental_covariance_method(covariance_method_key):
            meta.update(
                {
                    "style_factors": list(style_factors or []),
                    "include_sector_factors": include_sector_factors,
                    "exposure_lag_days": exposure_lag_days,
                    "max_exposure_staleness_days": max_exposure_staleness_days,
                    "min_factor_return_days": min_factor_return_days,
                    "min_cross_section": min_cross_section,
                    "min_sector_members": min_sector_members,
                    "factor_ridge": factor_ridge,
                    "factor_cov_shrinkage": factor_cov_shrinkage,
                    "fallback_to_statistical_factor": fallback_to_statistical,
                    **fundamental_meta,
                }
            )
        if (
            (covariance.empty or not bool(quality.get("is_usable")))
            and is_fundamental_covariance_method(covariance_method_key)
            and fallback_to_statistical
        ):
            fallback_covariance = estimate_shrunk_covariance(
                returns,
                shrinkage_intensity=shrinkage_intensity,
                method="statistical_factor",
                factor_count=None if factor_count is None else int(factor_count),
                max_factor_count=max_factor_count,
                factor_variance_target=factor_variance_target,
                specific_variance_floor_ratio=specific_variance_floor_ratio,
            )
            fallback_quality = covariance_quality(fallback_covariance)
            if not fallback_covariance.empty and bool(fallback_quality.get("is_usable")):
                covariance = fallback_covariance
                quality = fallback_quality
                fallback_label = covariance_method_label("statistical_factor", shrinkage_intensity)
                meta.update(
                    {
                        "covariance_method": fallback_label,
                        "covariance_is_usable": True,
                        "covariance_reason": fallback_quality.get("reason"),
                        "covariance_condition_number": fallback_quality.get("condition_number"),
                        "covariance_fallback_used": True,
                        "covariance_fallback_reason": primary_quality.get("reason"),
                        "covariance_fallback_method": fallback_label,
                    }
                )
        if (covariance.empty or not bool(quality.get("is_usable"))) and fallback_to_diagonal:
            fallback_covariance = estimate_shrunk_covariance(
                returns,
                shrinkage_intensity=shrinkage_intensity,
                method="diagonal_shrinkage",
            )
            fallback_quality = covariance_quality(fallback_covariance)
            if not fallback_covariance.empty and bool(fallback_quality.get("is_usable")):
                covariance = fallback_covariance
                quality = fallback_quality
                fallback_label = covariance_method_label("diagonal_shrinkage", shrinkage_intensity)
                meta.update(
                    {
                        "covariance_method": fallback_label,
                        "covariance_is_usable": True,
                        "covariance_reason": fallback_quality.get("reason"),
                        "covariance_condition_number": fallback_quality.get("condition_number"),
                        "covariance_fallback_used": True,
                        "covariance_fallback_reason": primary_quality.get("reason"),
                        "covariance_fallback_method": fallback_label,
                    }
                )
    if covariance.empty or not bool(quality.get("is_usable")):
        return pd.DataFrame(), meta
    return covariance, meta


def _load_cw2_config(config_path: str | None = None) -> Dict[str, Any]:
    from team_Pearson.coursework_two.modules.utils.config_validation import load_cw2_config

    return load_cw2_config(config_path)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
