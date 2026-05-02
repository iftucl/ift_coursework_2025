"""Market-group factor computation: beta, momentum, volatility, liquidity, market cap.

Produces atomic factor records for the MARKET factor group.  All factors are
computed from price data stored in ``systematic_equity.factor_observations``
(``adjusted_close_price``, ``daily_return``, ``volume``, ``shares_outstanding``)
and fundamental data from
``systematic_equity.financial_observations`` (for cross-source factors).

Factors produced:

+--------------------+-------------------------------------------+-------------------+
| factor_name        | Description                               | CW2 use           |
+====================+===========================================+===================+
| momentum_3m        | 63-day cumulative return                  | Alpha             |
| momentum_6m        | 126-day cumulative return                 | Alpha             |
| momentum_12m       | 252-day return (skip last 21 days)        | Alpha             |
| volatility_60d     | 60-day daily return std dev               | Risk (covariance) |
| realized_vol_60d   | 60-day annualised realized volatility     | Risk (overlay)    |
| garch_vol_60d      | 60-day GARCH(1,1) conditional volatility  | Risk (overlay)    |
| beta_1y            | Cov(stock,benchmark)/Var(benchmark), 252d rolling | Risk (covariance) |
| liquidity_20d      | 20-day avg daily dollar volume (USD)      | Risk / constraint |
| log_market_cap     | ln(price × shares_outstanding)            | Risk (Size)       |
| ep_ratio           | EPS / Price (Earnings-to-Price)           | Alpha (Value)     |
| ebitda_to_ev       | EBITDA / Enterprise Value                 | Alpha (Value)     |
| payout_ratio       | DPS / EPS (payout sustainability input)  | Alpha (Dividend)  |
| dividend_stability | 5Y dividend-policy stability score        | Alpha (Dividend)  |
| vix_close          | CBOE Volatility Index daily close         | Risk (macro)      |
| us_treasury_10y    | US 10-Year Treasury Yield                 | Risk (macro)      |
| us_treasury_5y     | US 5-Year Treasury Yield                  | Risk (macro)      |
| us_treasury_3m     | US 3-Month Treasury Bill Rate             | Risk (macro)      |
+--------------------+-------------------------------------------+-------------------+

Macro indicators are stored with ``symbol = '_MACRO'`` to separate them from
stock-level factors while reusing the same ``factor_observations`` table.

``momentum_12m`` is a legacy database field name. Its implementation skips the
most recent 21 trading days, so CW2 maps it to the more precise sub-factor name
``momentum_12_1m``. ``momentum_1m`` and ``volatility_20d`` are already computed
in :mod:`factors`.

Example usage::

    from modules.transform.market_factors import build_market_factors

    records = build_market_factors(
        symbols=["AAPL", "MSFT"],
        end_date=date(2024, 12, 31),
        start_date=date(2024, 1, 1),
    )
"""

from __future__ import annotations

import logging
import math
import os
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from modules.transform.pit_semantics import financial_publish_value_expr

logger = logging.getLogger(__name__)
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_TRADING_DAYS_PER_YEAR = 252
_BETA_WINDOW = 252  # Rolling window in trading days
_MOM_3M_DAYS = 63  # 3-month momentum
_MOM_6M_DAYS = 126  # 6-month momentum
_MOM_12M_DAYS = 252  # 12-month momentum
_MOM_12M_SKIP = 21  # Skip most-recent month (standard momentum construction)
_VOL_60D_DAYS = 60
_LIQ_20D_DAYS = 20
_DEFAULT_BENCHMARK_TICKER = "SPY"
_DIV_STABILITY_HISTORY_YEARS = 5
_DIV_STABILITY_MIN_HISTORY = 3
_DIV_CUT_TOLERANCE = 0.05
_MAX_OBSERVATION_LAG_DAYS = 7

# Macro indicators fetched from yfinance as index-level time series.
# Each entry: (yfinance_ticker, factor_name_for_db)
_MACRO_TICKERS: List[tuple] = [
    ("^VIX", "vix_close"),  # CBOE Volatility Index
    ("^TNX", "us_treasury_10y"),  # 10-Year US Treasury Yield
    ("^FVX", "us_treasury_5y"),  # 5-Year US Treasury Yield
    ("^IRX", "us_treasury_3m"),  # 3-Month US Treasury Bill Rate
]


def _validated_identifier(value: str, *, label: str) -> str:
    candidate = str(value).strip()
    if not _VALID_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"Invalid {label}: {value!r}")
    return candidate


def _db_schema() -> str:
    return _validated_identifier(
        os.getenv("POSTGRES_SCHEMA", "systematic_equity"),
        label="schema",
    )


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_price_data(
    symbols: List[str],
    start_date: date,
    end_date: date,
) -> Any:
    """Load price, return, and volume fields from ``factor_observations``.

    :param symbols: List of ticker symbols.
    :param start_date: Earliest observation date needed (with buffer).
    :param end_date: Latest observation date.
    :returns: Pandas DataFrame with columns [symbol, observation_date, factor_name, factor_value].
    :rtype: pandas.DataFrame
    """
    import pandas as pd
    from sqlalchemy import text

    from modules.db import get_db_engine

    engine = get_db_engine()
    schema = _db_schema()
    sql = text(f"""
        SELECT symbol, observation_date, factor_name, factor_value
        FROM {schema}.factor_observations
        WHERE symbol = ANY(:symbols)
          AND observation_date BETWEEN :start AND :end
          AND factor_name IN ('adjusted_close_price', 'daily_return', 'daily_volume', 'volume')
        ORDER BY symbol, observation_date
        """)  # nosec B608 - schema identifier is validated before interpolation

    with engine.connect() as conn:
        rows = conn.execute(sql, {"symbols": symbols, "start": start_date, "end": end_date})
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if not df.empty:
        df["observation_date"] = pd.to_datetime(df["observation_date"]).dt.date
        df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")
        df["factor_name"] = df["factor_name"].replace({"volume": "daily_volume"})

    return df


def _resolve_observation_dates(
    available_dates: List[date],
    *,
    start_date: date,
    end_date: date,
) -> List[date]:
    """Return target observation dates, with latest-available fallback.

    For daily runs it is common that ``end_date`` is a calendar date while the
    latest market data belongs to the prior trading session. In that case we
    emit a snapshot for the latest available trading date ``<= end_date``
    instead of returning nothing.
    """
    obs_dates = sorted(d for d in available_dates if start_date <= d <= end_date)
    if obs_dates:
        return obs_dates

    prior_dates = [d for d in available_dates if d <= end_date]
    if not prior_dates:
        return []

    fallback = max(prior_dates)
    if (end_date - fallback).days > _MAX_OBSERVATION_LAG_DAYS:
        return []
    return [fallback]


def _load_financial_data(
    symbols: List[str],
    start_date: date,
    end_date: date,
    metrics: List[str],
) -> Any:
    """Load fundamental metrics from ``financial_observations`` for cross-source factors.

    :param symbols: List of ticker symbols.
    :param start_date: Earliest report_date needed (with buffer).
    :param end_date: Latest report_date.
    :param metrics: List of metric_name values to fetch.
    :returns: Pandas DataFrame with columns
        [symbol, report_date, metric_name, metric_value, publish_date].
    :rtype: pandas.DataFrame
    """
    import pandas as pd
    from sqlalchemy import text

    from modules.db import get_db_engine

    engine = get_db_engine()
    schema = _db_schema()
    publish_expr = financial_publish_value_expr()
    sql = text(f"""
        SELECT
            symbol,
            report_date,
            metric_name,
            metric_value,
            source,
            {publish_expr} AS publish_date
        FROM {schema}.financial_observations
        WHERE symbol = ANY(:symbols)
          AND report_date BETWEEN :start AND :end
          AND metric_name = ANY(:metrics)
        ORDER BY symbol, report_date
        """)  # nosec B608 - schema identifier is validated before interpolation

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"symbols": symbols, "start": start_date, "end": end_date, "metrics": metrics},
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if not df.empty:
        df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
        df["metric_value"] = pd.to_numeric(df["metric_value"], errors="coerce")
        if "publish_date" in df.columns:
            df["publish_date"] = pd.to_datetime(df["publish_date"], errors="coerce").dt.date

    return df


def _load_benchmark_returns(
    start_date: date,
    end_date: date,
    benchmark_ticker: str = _DEFAULT_BENCHMARK_TICKER,
) -> Any:
    """Load benchmark daily log-returns from ``benchmark_prices``.

    :param start_date: Start date.
    :param end_date: End date.
    :param benchmark_ticker: Benchmark ticker stored in ``benchmark_prices``.
    :returns: Pandas Series indexed by ``price_date``.
    :rtype: pandas.Series
    """
    import pandas as pd
    from sqlalchemy import text

    from modules.db import get_db_engine

    engine = get_db_engine()
    schema = _db_schema()
    sql = text(f"""
        SELECT price_date, daily_return
        FROM {schema}.benchmark_prices
        WHERE ticker = :ticker
          AND price_date BETWEEN :start AND :end
        ORDER BY price_date
        """)  # nosec B608 - schema identifier is validated before interpolation

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"ticker": benchmark_ticker, "start": start_date, "end": end_date},
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if df.empty:
        return pd.Series(dtype=float)

    df["price_date"] = pd.to_datetime(df["price_date"]).dt.date
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")
    return df.set_index("price_date")["daily_return"]


def _load_and_store_benchmark_prices(
    start_date: date,
    end_date: date,
    benchmark_ticker: str = _DEFAULT_BENCHMARK_TICKER,
) -> None:
    """Fetch benchmark prices from yfinance and upsert into ``benchmark_prices``.

    Called once before factor computation to ensure benchmark data is fresh.

    :param start_date: First price date needed.
    :param end_date: Last price date needed.
    :param benchmark_ticker: Yahoo Finance ticker for the market benchmark.
    :rtype: None
    """
    import math

    import pandas as pd
    import yfinance as yf
    from sqlalchemy import text

    from modules.db import get_db_engine

    logger.info("market_factors: fetching benchmark prices ticker=%s", benchmark_ticker)
    ticker = yf.Ticker(benchmark_ticker)
    hist = ticker.history(start=start_date.isoformat(), end=end_date.isoformat(), auto_adjust=True)
    if hist is None or hist.empty:
        logger.warning("market_factors: no benchmark data returned from yfinance")
        return

    hist.index = pd.to_datetime(hist.index).date
    hist = hist[["Close"]].rename(columns={"Close": "close_price"})
    hist["daily_return"] = hist["close_price"].apply(math.log).diff()

    engine = get_db_engine()
    schema = _db_schema()

    rows = [
        {
            "ticker": benchmark_ticker,
            "price_date": d,
            "close_price": float(row["close_price"]),
            "daily_return": float(row["daily_return"]) if pd.notna(row["daily_return"]) else None,
            "source": "yfinance",
        }
        for d, row in hist.iterrows()
    ]

    upsert_sql = text(f"""
        INSERT INTO {schema}.benchmark_prices
            (ticker, price_date, close_price, daily_return, source)
        VALUES (:ticker, :price_date, :close_price, :daily_return, :source)
        ON CONFLICT (ticker, price_date)
        DO UPDATE SET
            close_price  = EXCLUDED.close_price,
            daily_return = EXCLUDED.daily_return,
            updated_at   = NOW()
        """)  # nosec B608 - schema identifier is validated before interpolation

    with engine.begin() as conn:
        conn.execute(upsert_sql, rows)

    logger.info(
        "market_factors: upserted %s benchmark price rows ticker=%s",
        len(rows),
        benchmark_ticker,
    )


def _load_and_store_macro_indicators(
    start_date: date,
    end_date: date,
) -> None:
    """Fetch macro indicators (VIX, Treasury yields) from yfinance and upsert into ``factor_observations``.

    Stored as market-level factors with ``symbol = '_MACRO'`` to distinguish
    from stock-level factors while reusing the same table and PIT infrastructure.

    :param start_date: First date needed.
    :param end_date: Last date needed.
    :rtype: None
    """
    import pandas as pd
    import yfinance as yf
    from sqlalchemy import text

    from modules.db import get_db_engine

    engine = get_db_engine()
    schema = os.getenv("POSTGRES_SCHEMA", "systematic_equity")
    total_rows = 0

    for yf_ticker, factor_name in _MACRO_TICKERS:
        try:
            ticker = yf.Ticker(yf_ticker)
            hist = ticker.history(
                start=start_date.isoformat(), end=end_date.isoformat(), auto_adjust=True
            )
        except Exception as exc:
            logger.warning(
                "market_factors: failed to fetch %s (%s): %s", yf_ticker, factor_name, exc
            )
            continue

        if hist is None or hist.empty:
            logger.warning("market_factors: no data for %s (%s)", yf_ticker, factor_name)
            continue

        hist.index = pd.to_datetime(hist.index).date

        rows = [
            {
                "symbol": "_MACRO",
                "observation_date": d,
                "factor_name": factor_name,
                "factor_value": float(row["Close"]),
                "source": "yfinance",
                "metric_frequency": "daily",
                "source_report_date": d,
                "publish_date": d,
            }
            for d, row in hist.iterrows()
            if pd.notna(row["Close"])
        ]

        if not rows:
            continue

        upsert_sql = text(f"""
            INSERT INTO {schema}.factor_observations
                (symbol, observation_date, factor_name, factor_value,
                 source, metric_frequency, source_report_date, publish_date)
            VALUES (:symbol, :observation_date, :factor_name, :factor_value,
                    :source, :metric_frequency, :source_report_date, :publish_date)
            ON CONFLICT (symbol, observation_date, factor_name)
            DO UPDATE SET
                factor_value  = EXCLUDED.factor_value,
                updated_at    = NOW()
            """)  # nosec B608 - schema identifier is validated before interpolation

        with engine.begin() as conn:
            conn.execute(upsert_sql, rows)
        total_rows += len(rows)
        logger.info(
            "market_factors: upserted %s rows for %s (%s)", len(rows), yf_ticker, factor_name
        )

    logger.info("market_factors: macro indicators total upserted = %s rows", total_rows)


# ---------------------------------------------------------------------------
# Factor computation helpers
# ---------------------------------------------------------------------------


def _compute_momentum(returns: Any, window: int, skip: int = 0) -> Optional[float]:
    """Compute cumulative return over *window* trading days, optionally skipping last *skip* days.

    :param returns: Pandas Series of daily returns, sorted ascending.
    :param window: Look-back window in trading days.
    :param skip: Number of most-recent trading days to exclude.
    :returns: Cumulative return or ``None`` if insufficient data.
    :rtype: float | None
    """
    if skip > 0:
        returns = returns.iloc[:-skip] if len(returns) > skip else returns.iloc[:0]
    tail = returns.iloc[-window:]
    if len(tail) < window // 2:  # Require at least half the window
        return None
    cum_return = float((1 + tail).prod() - 1)
    return cum_return if math.isfinite(cum_return) else None


def _compute_rolling_vol(returns: Any, window: int) -> Optional[float]:
    """Compute annualised return volatility over *window* trading days.

    :param returns: Pandas Series of daily returns, sorted ascending.
    :param window: Look-back window in trading days.
    :returns: Annualised volatility or ``None`` if insufficient data.
    :rtype: float | None
    """
    tail = returns.iloc[-window:]
    if len(tail) < window // 2:
        return None
    vol = float(tail.std(ddof=1)) * math.sqrt(_TRADING_DAYS_PER_YEAR)
    return vol if math.isfinite(vol) else None


def _compute_realized_vol(returns: Any, window: int) -> Optional[float]:
    """Compute annualised realized volatility over *window* trading days.

    Realized volatility uses the root mean square of daily returns rather than
    de-meaned sample standard deviation. This is a common risk-overlay metric
    because it reacts directly to absolute return shocks.

    :param returns: Pandas Series of daily returns, sorted ascending.
    :param window: Look-back window in trading days.
    :returns: Annualised realized volatility or ``None`` if insufficient data.
    :rtype: float | None
    """
    tail = returns.iloc[-window:]
    if len(tail) < window // 2:
        return None
    realized_var = float((tail.pow(2).sum()) * (_TRADING_DAYS_PER_YEAR / len(tail)))
    if realized_var < 0 or not math.isfinite(realized_var):
        return None
    realized_vol = math.sqrt(realized_var)
    return realized_vol if math.isfinite(realized_vol) else None


def _compute_garch_vol(returns: Any, window: int) -> Optional[float]:
    """Estimate annualised conditional volatility from a GARCH(1,1) model.

    This implementation avoids external optimizer dependencies by using a
    bounded grid search over admissible ``alpha`` and ``beta`` pairs and
    Gaussian quasi-maximum likelihood. ``omega`` is backed out from the sample
    unconditional variance so the selected parameter triplet remains stationary.

    :param returns: Pandas Series of daily returns, sorted ascending.
    :param window: Look-back window in trading days.
    :returns: Annualised conditional volatility or ``None`` if insufficient data.
    :rtype: float | None
    """
    import numpy as np

    tail = returns.iloc[-window:]
    if len(tail) < window // 2:
        return None

    eps = np.asarray(tail.dropna(), dtype=float)
    if eps.size < window // 2:
        return None

    eps = eps - float(np.mean(eps))
    sample_var = float(np.var(eps, ddof=1)) if eps.size > 1 else float(np.var(eps))
    if not math.isfinite(sample_var):
        return None
    if sample_var <= 0:
        return 0.0

    best_ll = -math.inf
    best_h_last: Optional[float] = None

    alpha_grid = [0.03, 0.05, 0.07, 0.10, 0.12, 0.15, 0.18]
    beta_grid = [0.70, 0.78, 0.84, 0.88, 0.91, 0.94, 0.96]

    for alpha in alpha_grid:
        for beta in beta_grid:
            persistence = alpha + beta
            if persistence >= 0.995:
                continue

            omega = sample_var * (1.0 - persistence)
            if omega <= 0 or not math.isfinite(omega):
                continue

            h_prev = sample_var
            loglik = 0.0
            valid = True

            for e in eps:
                h_t = omega + alpha * (e * e) + beta * h_prev
                if h_t <= 0 or not math.isfinite(h_t):
                    valid = False
                    break
                loglik += -0.5 * (math.log(h_t) + (e * e) / h_t)
                h_prev = h_t

            if valid and loglik > best_ll:
                best_ll = loglik
                best_h_last = h_prev

    if best_h_last is None or best_h_last <= 0:
        return None

    annualized = math.sqrt(best_h_last * _TRADING_DAYS_PER_YEAR)
    return annualized if math.isfinite(annualized) else None


def _compute_beta(
    stock_returns: Any, market_returns: Any, window: int = _BETA_WINDOW
) -> Optional[float]:
    """Compute rolling beta over *window* trading days.

    Beta = Cov(stock, market) / Var(market).

    :param stock_returns: Pandas Series of stock daily returns, indexed by date.
    :param market_returns: Pandas Series of benchmark daily returns, indexed by date.
    :param window: Look-back window in trading days.
    :returns: Beta or ``None`` if insufficient aligned data.
    :rtype: float | None
    """
    import pandas as pd

    aligned = pd.concat([stock_returns, market_returns], axis=1).dropna()
    aligned.columns = ["stock", "market"]
    aligned = aligned.iloc[-window:]

    if len(aligned) < window // 2:
        return None

    cov_matrix = aligned.cov()
    cov_sm = cov_matrix.at["stock", "market"]
    var_m = cov_matrix.at["market", "market"]

    if var_m == 0 or not math.isfinite(var_m):
        return None

    beta = cov_sm / var_m
    return float(beta) if math.isfinite(beta) else None


def _compute_liquidity(prices: Any, volumes: Any, window: int = _LIQ_20D_DAYS) -> Optional[float]:
    """Compute average daily dollar trading volume over *window* days.

    :param prices: Pandas Series of closing prices, indexed by date.
    :param volumes: Pandas Series of share volumes, indexed by date.
    :param window: Look-back window in trading days.
    :returns: Average daily dollar volume or ``None`` if insufficient data.
    :rtype: float | None
    """
    dollar_vol = prices * volumes
    tail = dollar_vol.iloc[-window:]
    if len(tail) < window // 2:
        return None
    result = float(tail.mean())
    return result if math.isfinite(result) else None


def _compute_log_market_cap(price: Optional[float], shares: Optional[float]) -> Optional[float]:
    """Compute ln(market_cap) = ln(price × shares).

    :param price: Adjusted closing price.
    :param shares: Shares outstanding.
    :returns: Natural log of market cap, or ``None``.
    :rtype: float | None
    """
    if price is None or shares is None or price <= 0 or shares <= 0:
        return None
    mktcap = price * shares
    if mktcap <= 0:
        return None
    return math.log(mktcap)


# ---------------------------------------------------------------------------
# Cross-source factor helpers (price × financial data)
# ---------------------------------------------------------------------------


def _latest_financial_value(
    fin_df: Any,
    symbol: str,
    metric: str,
    cutoff: date,
) -> Optional[float]:
    """Return latest metric_value on/before *cutoff* for a symbol from financial_observations.

    :param fin_df: DataFrame from :func:`_load_financial_data`.
    :param symbol: Ticker symbol.
    :param metric: Metric name (e.g. ``'eps_basic'``).
    :param cutoff: Latest as-of date to consider, with PIT enforced via publish_date.
    :returns: Most recent value or ``None``.
    :rtype: float | None
    """
    subset = fin_df[
        (fin_df["symbol"] == symbol)
        & (fin_df["metric_name"] == metric)
        & (fin_df["report_date"] <= cutoff)
    ].copy()
    if "publish_date" in subset.columns:
        subset["publish_date"] = subset["publish_date"].where(
            subset["publish_date"].notna(), subset["report_date"]
        )
        subset = subset[subset["publish_date"] <= cutoff]
    if subset.empty:
        return None
    sort_cols = ["report_date"]
    if "publish_date" in subset.columns:
        sort_cols.append("publish_date")
    val = subset.sort_values(sort_cols).iloc[-1]["metric_value"]
    return _to_float_or_none(val)


def _resolve_same_source_financial_bundle(
    fin_df: Any,
    symbol: str,
    required_metrics: List[str],
    cutoff: date,
    *,
    optional_metrics: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Return latest financial bundle with same-source preference.

    Falls back to latest PIT-valid per-metric values when no same-source bundle
    exists, while preserving an explicit ``pair_mode`` marker.
    """
    metrics = list(required_metrics) + list(optional_metrics or [])
    subset = fin_df[
        (fin_df["symbol"] == symbol)
        & (fin_df["metric_name"].isin(metrics))
        & (fin_df["report_date"] <= cutoff)
    ].copy()
    if subset.empty or "source" not in subset.columns:
        return None

    subset["source"] = subset["source"].astype(str).str.strip()
    subset = subset[subset["source"] != ""]
    if subset.empty:
        return None

    if "publish_date" in subset.columns:
        subset["publish_date"] = subset["publish_date"].where(
            subset["publish_date"].notna(), subset["report_date"]
        )
        subset = subset[subset["publish_date"] <= cutoff]
    else:
        subset["publish_date"] = subset["report_date"]
    if subset.empty:
        return None

    candidates = []
    for (source, report_date), grp in subset.groupby(["source", "report_date"], dropna=False):
        available_metrics = set(grp["metric_name"].dropna())
        if not set(required_metrics).issubset(available_metrics):
            continue
        latest_rows = grp.sort_values(["metric_name", "publish_date"]).drop_duplicates(
            subset=["metric_name"], keep="last"
        )
        metrics_map = {
            str(row["metric_name"]): _to_float_or_none(row["metric_value"])
            for _, row in latest_rows.iterrows()
        }
        candidates.append(
            {
                "source": source,
                "report_date": report_date,
                "publish_date": max(latest_rows["publish_date"]),
                "metrics": metrics_map,
            }
        )

    if candidates:
        candidates.sort(key=lambda item: (item["report_date"], item["publish_date"]))
        bundle = candidates[-1]
        bundle["pair_mode"] = "same_source_bundle"
        return bundle

    latest_rows = {}
    for metric in metrics:
        metric_subset = subset[subset["metric_name"] == metric].sort_values(
            ["report_date", "publish_date"]
        )
        if metric_subset.empty:
            continue
        latest_rows[metric] = metric_subset.iloc[-1]

    if not set(required_metrics).issubset(set(latest_rows)):
        return None

    metrics_map = {
        metric: _to_float_or_none(row["metric_value"]) for metric, row in latest_rows.items()
    }
    logger.info(
        "pair_integrity_relaxed=True factor=ebitda_to_ev symbol=%s cutoff=%s pair_mode=%s metric_sources=%s",
        symbol,
        cutoff.isoformat(),
        "mixed_source_bundle",
        {
            metric: str(row.get("source") or "").strip() or "unknown"
            for metric, row in latest_rows.items()
        },
    )
    return {
        "source": None,
        "report_date": max(row["report_date"] for row in latest_rows.values()),
        "publish_date": max(row["publish_date"] for row in latest_rows.values()),
        "metrics": metrics_map,
        "pair_mode": "mixed_source_bundle",
    }


def _compute_ep_ratio(eps: Optional[float], price: Optional[float]) -> Optional[float]:
    """Compute Earnings-to-Price ratio (E/P = EPS / Price).

    :param eps: Earnings per share (basic).
    :param price: Adjusted closing price.
    :returns: E/P ratio or ``None``.
    :rtype: float | None
    """
    if eps is None or price is None or price <= 0:
        return None
    result = eps / price
    return result if math.isfinite(result) else None


def _compute_ebitda_to_ev(
    ebitda: Optional[float],
    market_cap: Optional[float],
    total_debt: Optional[float],
    cash: Optional[float],
) -> Optional[float]:
    """Compute EBITDA / Enterprise Value.

    EV = market_cap + total_debt - cash_and_equivalents.

    :param ebitda: EBITDA value.
    :param market_cap: price × shares_outstanding.
    :param total_debt: Total debt (long-term + short-term).
    :param cash: Cash and cash equivalents.
    :returns: EBITDA/EV ratio or ``None``.
    :rtype: float | None
    """
    if ebitda is None or market_cap is None or market_cap <= 0:
        return None
    debt = total_debt or 0.0
    cash_val = cash or 0.0
    ev = market_cap + debt - cash_val
    if ev <= 0:
        return None
    result = ebitda / ev
    return result if math.isfinite(result) else None


def _compute_payout_ratio(dps: Optional[float], eps: Optional[float]) -> Optional[float]:
    """Compute payout ratio = DPS / EPS.

    High payout (> 1.0) is unsustainable and penalised in CW2.

    :param dps: Trailing 12-month dividends per share.
    :param eps: Basic earnings per share.
    :returns: Payout ratio or ``None``.
    :rtype: float | None
    """
    if dps is None or eps is None or eps == 0:
        return None
    result = dps / eps
    return result if math.isfinite(result) else None


def _compute_dividend_stability(
    dps_series: Any,
    cutoff: date,
    history_years: int = _DIV_STABILITY_HISTORY_YEARS,
    min_history_years: int = _DIV_STABILITY_MIN_HISTORY,
    cut_tolerance: float = _DIV_CUT_TOLERANCE,
) -> Optional[float]:
    """Compute a dividend-policy stability score from trailing TTM payouts.

    The score is designed for a defensive/dividend factor rather than a pure
    growth factor. It rewards:
    - long observable history,
    - low variability in trailing 12-month dividend cash flows,
    - few or no dividend cuts,
    - no dividend omissions.

    The implementation uses annual anchors of trailing 12-month DPS totals over
    the last ``history_years`` years. This is a practical proxy for the
    "stable and predictable dividend policy" concept commonly used in
    professional equity factor research when richer dividend-policy metadata is
    unavailable.

    :param dps_series: Pandas Series of ex-date DPS amounts indexed by date.
    :param cutoff: Current observation date.
    :param history_years: Number of annual anchors to evaluate.
    :param min_history_years: Minimum valid anchors required.
    :param cut_tolerance: Minimum annual decline treated as a dividend cut.
    :returns: Stability score in ``[0, 1]`` where higher is better, or ``None``.
    :rtype: float | None
    """
    from datetime import timedelta

    if dps_series is None or dps_series.empty:
        return None

    series = dps_series.dropna().sort_index()
    if series.empty:
        return None

    earliest = min(ts.date() for ts in series.index)

    def _ttm_dividend(end_date: date) -> Optional[float]:
        start_date = end_date - timedelta(days=365)
        if earliest > start_date:
            return None
        mask = (series.index.date > start_date) & (series.index.date <= end_date)
        vals = series[mask]
        if vals.empty:
            return 0.0
        return float(vals.sum())

    anchor_dates = [
        cutoff - timedelta(days=365 * years_ago) for years_ago in reversed(range(history_years))
    ]
    ttm_values = [v for v in (_ttm_dividend(anchor) for anchor in anchor_dates) if v is not None]

    if len(ttm_values) < min_history_years:
        return None

    mean_ttm = float(sum(ttm_values) / len(ttm_values))
    if mean_ttm <= 0 or not math.isfinite(mean_ttm):
        return None

    if len(ttm_values) > 1:
        variance = sum((v - mean_ttm) ** 2 for v in ttm_values) / (len(ttm_values) - 1)
        coeff_var = math.sqrt(variance) / mean_ttm if variance >= 0 else None
    else:
        coeff_var = 0.0
    if coeff_var is None or not math.isfinite(coeff_var):
        return None

    cuts = sum(
        1
        for prev, curr in zip(ttm_values[:-1], ttm_values[1:])
        if curr < prev * (1.0 - cut_tolerance)
    )
    cut_ratio = cuts / max(len(ttm_values) - 1, 1)
    omission_ratio = sum(1 for v in ttm_values if v <= 0.0) / len(ttm_values)
    coverage_ratio = len(ttm_values) / float(history_years)

    stability = coverage_ratio * (1.0 - cut_ratio) * (1.0 - omission_ratio) / (1.0 + coeff_var)
    return stability if math.isfinite(stability) else None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_market_factors(
    symbols: List[str],
    *,
    end_date: date,
    start_date: date,
    output_frequency: str = "daily",
    refresh_benchmark: bool = True,
    benchmark_ticker: str = _DEFAULT_BENCHMARK_TICKER,
) -> List[Dict[str, Any]]:
    """Compute all MARKET-group factors for *symbols* over [start_date, end_date].

    Factors produced include ``momentum_3m``, ``momentum_6m``,
    legacy-named ``momentum_12m`` for 12-1M momentum, volatility and beta risk
    measures, liquidity and size fields, price-fundamental value factors,
    dividend inputs, and macro regime inputs.

    :param symbols: List of ticker symbols.
    :type symbols: list[str]
    :param end_date: Last observation date (inclusive).
    :type end_date: date
    :param start_date: First observation date (inclusive).
    :type start_date: date
    :param output_frequency: Metric frequency label for DB records.
    :type output_frequency: str
    :param refresh_benchmark: If ``True``, fetch fresh benchmark prices before computing.
    :type refresh_benchmark: bool
    :param benchmark_ticker: Yahoo Finance ticker used as the market benchmark.
    :type benchmark_ticker: str
    :returns: List of factor_observations dicts ready for :func:`~modules.output.load.load_curated`.
    :rtype: list[dict]
    """
    import pandas as pd

    # Buffer: technical factors need ~2 years; dividend stability needs a
    # multi-year DPS history before the first scored date.
    data_start = start_date - timedelta(
        days=max(_TRADING_DAYS_PER_YEAR * 2, 365 * (_DIV_STABILITY_HISTORY_YEARS + 1))
    )

    if refresh_benchmark:
        try:
            _load_and_store_benchmark_prices(data_start, end_date, benchmark_ticker)
        except Exception as exc:
            logger.warning("market_factors: benchmark refresh failed: %s", exc)
        try:
            _load_and_store_macro_indicators(data_start, end_date)
        except Exception as exc:
            logger.warning("market_factors: macro indicator refresh failed: %s", exc)

    df = _load_price_data(symbols, data_start, end_date)
    if df.empty:
        logger.warning("market_factors: no price data found for %s symbols", len(symbols))
        return []

    market_returns = _load_benchmark_returns(data_start, end_date, benchmark_ticker)

    # Load financial data needed for cross-source factors
    _CROSS_SOURCE_METRICS = [
        "eps_basic",
        "ebitda",
        "total_debt",
        "cash_and_equivalents",
        "shares_outstanding",
    ]
    try:
        fin_df = _load_financial_data(symbols, data_start, end_date, _CROSS_SOURCE_METRICS)
    except Exception as exc:
        logger.warning(
            "market_factors: financial data load failed (%s). Cross-source factors skipped.", exc
        )
        fin_df = None

    records: List[Dict[str, Any]] = []

    for symbol in symbols:
        sym_df = df[df["symbol"] == symbol]
        if sym_df.empty:
            continue

        # Extract per-factor series
        def _series(factor_name: str) -> Any:
            sub = sym_df[sym_df["factor_name"] == factor_name].set_index("observation_date")
            sub.index = pd.to_datetime(sub.index)
            return sub["factor_value"].astype(float)

        price_series = _series("adjusted_close_price")
        return_series = _series("daily_return")
        volume_series = _series("daily_volume")
        shares_series = _series("shares_outstanding")
        dps_series = _series("dividend_per_share")

        if price_series.empty or return_series.empty:
            logger.debug("market_factors: insufficient data for symbol=%s", symbol)
            continue

        # Observation dates in target window
        obs_dates = _resolve_observation_dates(
            list(price_series.index.date),
            start_date=start_date,
            end_date=end_date,
        )
        if obs_dates and (obs_dates[-1] < start_date or obs_dates[-1] < end_date):
            logger.info(
                "market_factors: symbol=%s using latest available trading date %s for requested window [%s..%s]",
                symbol,
                obs_dates[-1],
                start_date,
                end_date,
            )

        for obs_date in obs_dates:
            obs_ts = pd.Timestamp(obs_date)
            ret_slice = return_series[return_series.index <= obs_ts]
            px_slice = price_series[price_series.index <= obs_ts]
            vol_slice = volume_series[volume_series.index <= obs_ts]

            # Market return slice aligned to stock dates
            mkt_slice = (
                market_returns[market_returns.index <= obs_date]
                if not market_returns.empty
                else pd.Series(dtype=float)
            )

            base = {
                "symbol": symbol,
                "observation_date": obs_date.isoformat(),
                "source": "factor_transform_market",
                "metric_frequency": output_frequency,
                "source_report_date": obs_date.isoformat(),
                "publish_date": obs_date.isoformat(),
            }

            def _add(name: str, value: Optional[float]) -> None:
                if value is None:
                    return
                records.append({**base, "factor_name": name, "factor_value": value})

            # momentum_3m
            _add("momentum_3m", _compute_momentum(ret_slice, _MOM_3M_DAYS))

            # momentum_6m
            _add("momentum_6m", _compute_momentum(ret_slice, _MOM_6M_DAYS))

            # Legacy DB name: momentum_12m. Calculation is standard 12-1M
            # momentum because it skips the most recent 21 trading days; CW2
            # exposes this as momentum_12_1m at the feature layer.
            _add("momentum_12m", _compute_momentum(ret_slice, _MOM_12M_DAYS, skip=_MOM_12M_SKIP))

            # volatility_60d
            _add("volatility_60d", _compute_rolling_vol(ret_slice, _VOL_60D_DAYS))

            # realized_vol_60d
            _add("realized_vol_60d", _compute_realized_vol(ret_slice, _VOL_60D_DAYS))

            # garch_vol_60d
            _add("garch_vol_60d", _compute_garch_vol(ret_slice, _VOL_60D_DAYS))

            # beta_1y
            if not mkt_slice.empty:
                _add("beta_1y", _compute_beta(ret_slice, mkt_slice, _BETA_WINDOW))

            # liquidity_20d
            if not vol_slice.empty:
                _add("liquidity_20d", _compute_liquidity(px_slice, vol_slice, _LIQ_20D_DAYS))

            # Price and shares for market-cap-dependent factors. Shares are
            # primarily sourced from financial_observations because they are a
            # slower-moving fundamental, not a true daily atomic market field.
            px_val = _to_float_or_none(px_slice.iloc[-1] if not px_slice.empty else None)
            sh_val = None
            if fin_df is not None and not fin_df.empty:
                sh_val = _latest_financial_value(fin_df, symbol, "shares_outstanding", obs_date)
            if sh_val is None:
                sh_slice = shares_series[shares_series.index <= obs_ts]
                sh_val = _to_float_or_none(sh_slice.iloc[-1] if not sh_slice.empty else None)

            # log_market_cap
            _add("log_market_cap", _compute_log_market_cap(px_val, sh_val))

            # ----------------------------------------------------------------
            # Cross-source factors (price + financial_observations)
            # ----------------------------------------------------------------
            if fin_df is not None and not fin_df.empty:
                eps = _latest_financial_value(fin_df, symbol, "eps_basic", obs_date)
                ebitda_bundle = _resolve_same_source_financial_bundle(
                    fin_df,
                    symbol,
                    ["ebitda", "shares_outstanding"],
                    obs_date,
                    optional_metrics=["total_debt", "cash_and_equivalents"],
                )
                ebitda = None
                total_debt = None
                cash = None
                paired_shares = None
                if ebitda_bundle is not None:
                    metrics_map = ebitda_bundle["metrics"]
                    ebitda = metrics_map.get("ebitda")
                    total_debt = metrics_map.get("total_debt")
                    cash = metrics_map.get("cash_and_equivalents")
                    paired_shares = metrics_map.get("shares_outstanding")
                # ep_ratio: E/P = EPS / Price
                _add("ep_ratio", _compute_ep_ratio(eps, px_val))

                # ebitda_to_ev: EBITDA / (market_cap + debt - cash)
                mktcap_shares = paired_shares if paired_shares is not None else sh_val
                mktcap = (px_val * mktcap_shares) if (px_val and mktcap_shares) else None
                _add("ebitda_to_ev", _compute_ebitda_to_ev(ebitda, mktcap, total_debt, cash))

                # payout_ratio: DPS_TTM / EPS
                dps_slice = dps_series[dps_series.index <= obs_ts]
                if not dps_slice.empty and eps is not None:
                    ttm_start = obs_ts - pd.Timedelta(days=365)
                    dps_ttm = float(dps_slice[dps_slice.index > ttm_start].sum())
                    _add("payout_ratio", _compute_payout_ratio(dps_ttm, eps))

                # dividend_stability: multi-year stability of TTM dividends
                if not dps_series.empty:
                    _add("dividend_stability", _compute_dividend_stability(dps_series, obs_date))

    logger.info(
        "market_factors: computed %s records for %s symbols [%s..%s]",
        len(records),
        len(symbols),
        start_date,
        end_date,
    )
    return records


def _to_float_or_none(value: Any) -> Optional[float]:
    """Convert numeric-like value to finite float, otherwise ``None``.

    :param value: Any numeric-like value.
    :returns: Finite float or ``None``.
    :rtype: float | None
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
