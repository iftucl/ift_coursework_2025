from __future__ import annotations

"""Build final factors from atomic factors persisted in PostgreSQL."""

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text

from modules.db import get_db_engine
from modules.output import load_curated

logger = logging.getLogger(__name__)

FINANCIAL_SOFT_STALE_DAYS = 270
FINANCIAL_HARD_EXPIRE_DAYS = 365
MARKET_TRADING_DAYS_PER_YEAR = 252

MARKET_ATOMIC_FACTORS = {
    "adjusted_close_price",
    "daily_return",
    "dividend_per_share",
}

_QUALITY_EVENT_COUNTS: Dict[str, Any] = {
    "stale_count": 0,
    "expired_count": 0,
    "stale_by_factor": {},
    "expired_by_factor": {},
}


def _quality_verbose_events_enabled() -> bool:
    """Return whether per-event quality warnings should be logged verbosely."""
    return str(os.getenv("QUALITY_VERBOSE_EVENTS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _reset_quality_event_counts() -> None:
    """Reset in-memory quality event counters for one factor-build run."""
    _QUALITY_EVENT_COUNTS["stale_count"] = 0
    _QUALITY_EVENT_COUNTS["expired_count"] = 0
    _QUALITY_EVENT_COUNTS["stale_by_factor"] = {}
    _QUALITY_EVENT_COUNTS["expired_by_factor"] = {}


def _record_quality_event(kind: str, factor: str) -> None:
    """Increment stale/expired counters for a factor category."""
    if kind == "stale":
        _QUALITY_EVENT_COUNTS["stale_count"] = int(_QUALITY_EVENT_COUNTS["stale_count"]) + 1
        by_factor = dict(_QUALITY_EVENT_COUNTS["stale_by_factor"])
        by_factor[factor] = int(by_factor.get(factor, 0)) + 1
        _QUALITY_EVENT_COUNTS["stale_by_factor"] = by_factor
        return
    if kind == "expired":
        _QUALITY_EVENT_COUNTS["expired_count"] = int(_QUALITY_EVENT_COUNTS["expired_count"]) + 1
        by_factor = dict(_QUALITY_EVENT_COUNTS["expired_by_factor"])
        by_factor[factor] = int(by_factor.get(factor, 0)) + 1
        _QUALITY_EVENT_COUNTS["expired_by_factor"] = by_factor


def _flush_quality_event_summary() -> None:
    """Log aggregated staleness/expiry summary for the current run."""
    stale = int(_QUALITY_EVENT_COUNTS["stale_count"])
    expired = int(_QUALITY_EVENT_COUNTS["expired_count"])
    if stale == 0 and expired == 0:
        return
    logger.warning(
        "quality_event_summary stale_count=%s expired_count=%s "
        "stale_by_factor=%s expired_by_factor=%s",
        stale,
        expired,
        _QUALITY_EVENT_COUNTS["stale_by_factor"],
        _QUALITY_EVENT_COUNTS["expired_by_factor"],
    )


ALTERNATIVE_ATOMIC_FACTORS = {
    "news_sentiment_daily",
    "news_article_count_daily",
}

FINANCIAL_ATOMIC_FACTORS = {
    "total_debt",
    "total_shareholder_equity",
    "book_value",
    "shares_outstanding",
    "enterprise_ebitda",
    "enterprise_revenue",
}


def _parse_iso_date(value: Any) -> Optional[date]:
    """Parse date-like value as ``YYYY-MM-DD``; return None on failure."""
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _period_key(obs_date: date, output_frequency: str) -> tuple:
    """Map one observation date to sampling bucket key for target frequency."""
    if output_frequency == "daily":
        return (obs_date.year, obs_date.month, obs_date.day)
    if output_frequency == "weekly":
        iso = obs_date.isocalendar()
        return (int(iso[0]), int(iso[1]))
    if output_frequency == "monthly":
        return (obs_date.year, obs_date.month)
    if output_frequency == "quarterly":
        quarter = (obs_date.month - 1) // 3 + 1
        return (obs_date.year, quarter)
    if output_frequency == "annual":
        return (obs_date.year,)
    raise ValueError(f"Unsupported output_frequency: {output_frequency}")


def _sample_records_by_frequency(
    records: List[Dict[str, Any]],
    *,
    output_frequency: str,
) -> List[Dict[str, Any]]:
    """Sample records by output frequency using latest observation per period."""
    output_frequency = str(output_frequency).strip().lower()
    if output_frequency == "daily":
        return records

    sampled: Dict[tuple, Dict[str, Any]] = {}
    for rec in records:
        symbol = str(rec.get("symbol") or "")
        factor_name = str(rec.get("factor_name") or "")
        obs_date = _parse_iso_date(rec.get("observation_date"))
        if not symbol or not factor_name or obs_date is None:
            continue

        key = (symbol, factor_name, _period_key(obs_date, output_frequency))
        existing = sampled.get(key)
        if existing is None:
            sampled[key] = rec
            continue

        curr_obs = _parse_iso_date(existing.get("observation_date"))
        if curr_obs is None or obs_date > curr_obs:
            sampled[key] = rec
            continue
        if obs_date == curr_obs:
            # Tie-breaker: prefer newer source_report_date when available.
            curr_srd = _parse_iso_date(existing.get("source_report_date"))
            next_srd = _parse_iso_date(rec.get("source_report_date"))
            if curr_srd is None or (next_srd is not None and next_srd > curr_srd):
                sampled[key] = rec

    out = list(sampled.values())
    out.sort(
        key=lambda r: (
            str(r.get("symbol") or ""),
            str(r.get("observation_date") or ""),
            str(r.get("factor_name") or ""),
        )
    )
    return out


def _month_ends(start: date, end: date) -> List[date]:
    """Return month-end dates between ``start`` and ``end`` (inclusive)."""
    out: List[date] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        month_end = nxt - timedelta(days=1)
        if month_end <= end:
            out.append(month_end)
        cur = nxt
    return out


def _latest_financial_with_staleness_logging(
    frame,
    *,
    cutoff: date,
    factor: str,
    symbol: str,
    metric: str,
    soft_stale_days: int = FINANCIAL_SOFT_STALE_DAYS,
    hard_expire_days: int = FINANCIAL_HARD_EXPIRE_DAYS,
):
    """Return latest financial row on/before cutoff with soft/hard staleness handling."""
    subset = frame[frame["observation_date"] <= cutoff]
    if subset.empty:
        return None

    row = subset.iloc[-1]
    last_date = row["observation_date"]
    age_days = int((cutoff - last_date).days)

    if age_days > hard_expire_days:
        _record_quality_event("expired", factor)
        if _quality_verbose_events_enabled():
            logger.warning(
                "flag_data_expired=True factor=%s symbol=%s metric=%s cutoff=%s last_date=%s "
                "age_days=%s max_stale_days=%s",
                factor,
                symbol,
                metric,
                cutoff.isoformat(),
                last_date.isoformat(),
                age_days,
                hard_expire_days,
            )
        return None

    if age_days > soft_stale_days:
        _record_quality_event("stale", factor)
        if _quality_verbose_events_enabled():
            logger.warning(
                "flag_financial_stale=True factor=%s symbol=%s metric=%s cutoff=%s last_date=%s "
                "age_days=%s soft_stale_days=%s",
                factor,
                symbol,
                metric,
                cutoff.isoformat(),
                last_date.isoformat(),
                age_days,
                soft_stale_days,
            )

    return row


def _to_float_or_none(value: Any) -> Optional[float]:
    """Convert numeric-like value to finite float, otherwise None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def _find_price_row_with_trading_day_lookback(frame, cutoff: date, max_prior_trading_days: int = 3):
    """Find latest valid price row using strict backward-looking trading-day fallback.

    Rules:
    - Prefer exact cutoff date (trading_days_old=0).
    - If exact date missing, fallback to prior trading days only.
    - Maximum fallback is ``max_prior_trading_days``.
    - Rows with missing/non-positive prices are skipped within this lookback window.
    """
    subset = frame[frame["observation_date"] <= cutoff]
    if subset.empty:
        return None, None, None

    import pandas as pd

    # One row per trading date, keep latest record if duplicated.
    subset = (
        subset.sort_values("observation_date")
        .drop_duplicates(subset=["observation_date"], keep="last")
        .reset_index(drop=True)
    )

    dates = list(subset["observation_date"])
    if not dates:
        return None, None, None

    # Candidate lags (in trading-day *records*):
    # - If cutoff date exists, try lag=0..max_prior_trading_days.
    # - Otherwise, try lag=1..max_prior_trading_days.
    has_cutoff = dates[-1] == cutoff
    start_lag = 0 if has_cutoff else 1
    if start_lag > max_prior_trading_days:
        return None, None, None

    # Walk candidates from newest to oldest.
    for lag in range(start_lag, max_prior_trading_days + 1):
        idx = len(dates) - 1 - (lag - start_lag)
        if idx < 0:
            break
        cdate = dates[idx]
        row = subset.iloc[idx]
        px = _to_float_or_none(row.price)
        if px is None or px <= 0:
            continue

        # Additional safeguard for sparse/missing price histories:
        # enforce business-day gap from chosen price date to cutoff.
        bd_gap = int(len(pd.bdate_range(start=cdate, end=cutoff)) - 1)
        if bd_gap > max_prior_trading_days:
            continue

        return row, float(px), int(lag)

    return None, None, None


def _compute_dividend_yield_daily_asof(
    df, end_date: date, start_date: date
) -> List[Dict[str, Any]]:
    import pandas as pd

    price = (
        df[df["factor_name"] == "adjusted_close_price"][
            ["symbol", "observation_date", "factor_value"]
        ]
        .rename(columns={"factor_value": "price"})
        .copy()
    )
    dividend = (
        df[df["factor_name"] == "dividend_per_share"][
            ["symbol", "observation_date", "factor_value"]
        ]
        .rename(columns={"factor_value": "dps"})
        .copy()
    )
    if price.empty:
        return []

    price["price"] = pd.to_numeric(price["price"], errors="coerce")
    dividend["dps"] = pd.to_numeric(dividend["dps"], errors="coerce")

    records: List[Dict[str, Any]] = []
    for symbol in sorted(price["symbol"].dropna().unique()):
        ps = price[price["symbol"] == symbol].sort_values("observation_date").copy()
        ds = dividend[dividend["symbol"] == symbol].sort_values("observation_date").copy()
        if ps.empty:
            continue
        for obs_ts in pd.date_range(start=start_date, end=end_date, freq="D"):
            obs_date = obs_ts.date()
            p_row, px, trading_days_old = _find_price_row_with_trading_day_lookback(
                ps, obs_date, max_prior_trading_days=3
            )
            if p_row is None or px is None:
                continue

            px_date = p_row["observation_date"]
            if trading_days_old is not None and trading_days_old > 1:
                logger.warning(
                    "flag_stale_price=True factor=dividend_yield symbol=%s observation_date=%s "
                    "price_date=%s trading_days_old=%s",
                    symbol,
                    obs_date.isoformat(),
                    px_date.isoformat(),
                    trading_days_old,
                )
            ttm_start = px_date - timedelta(days=365)
            if ds.empty:
                ttm_dps = 0.0
            else:
                ttm_slice = ds[
                    (ds["observation_date"] > ttm_start) & (ds["observation_date"] <= px_date)
                ]
                ttm_dps = float(ttm_slice["dps"].fillna(0.0).sum())

            records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date.isoformat(),
                    "factor_name": "dividend_yield",
                    "factor_value": float(ttm_dps / px),
                    "source": "factor_transform",
                    "metric_frequency": "daily",
                    "source_report_date": px_date.isoformat(),
                }
            )
    return records


def _compute_pb_ratio_daily_asof(df, end_date: date, start_date: date) -> List[Dict[str, Any]]:
    import pandas as pd

    pb_min_sample_for_dynamic_cap = 50
    pb_fallback_cap = 100.0
    pb_winsor_lookback_bdays = int(os.getenv("PB_WINSOR_LOOKBACK_BDAYS", "252"))
    pb_winsor_lookback_bdays = max(1, pb_winsor_lookback_bdays)

    price = df[df["factor_name"] == "adjusted_close_price"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "price"})
    shares = df[df["factor_name"] == "shares_outstanding"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "shares"})
    equity = df[df["factor_name"] == "total_shareholder_equity"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "equity"})
    if price.empty or shares.empty or equity.empty:
        return []
    price["price"] = pd.to_numeric(price["price"], errors="coerce")
    shares["shares"] = pd.to_numeric(shares["shares"], errors="coerce")
    equity["equity"] = pd.to_numeric(equity["equity"], errors="coerce")

    raw_records: List[Dict[str, Any]] = []
    for symbol in sorted(price["symbol"].dropna().unique()):
        ps = price[price["symbol"] == symbol].sort_values("observation_date")
        ss = shares[shares["symbol"] == symbol].sort_values("observation_date")
        es = equity[equity["symbol"] == symbol].sort_values("observation_date")
        if ps.empty or ss.empty or es.empty:
            continue

        for obs_ts in pd.date_range(start=start_date, end=end_date, freq="D"):
            obs_date = obs_ts.date()
            p_row, p, trading_days_old = _find_price_row_with_trading_day_lookback(
                ps, obs_date, max_prior_trading_days=3
            )
            s_row = _latest_financial_with_staleness_logging(
                ss,
                cutoff=obs_date,
                factor="pb_ratio",
                symbol=symbol,
                metric="shares_outstanding",
            )
            e_row = _latest_financial_with_staleness_logging(
                es,
                cutoff=obs_date,
                factor="pb_ratio",
                symbol=symbol,
                metric="total_shareholder_equity",
            )
            if p_row is None or s_row is None or e_row is None:
                continue
            s = _to_float_or_none(s_row["shares"])
            e = _to_float_or_none(e_row["equity"])
            if p is None or s is None or e is None or p <= 0 or s <= 0 or e <= 0:
                continue
            if trading_days_old is not None and trading_days_old > 1:
                logger.warning(
                    "flag_stale_price=True factor=pb_ratio symbol=%s observation_date=%s "
                    "price_date=%s trading_days_old=%s",
                    symbol,
                    obs_date.isoformat(),
                    p_row["observation_date"].isoformat(),
                    trading_days_old,
                )
            pb = float((p * s) / e)
            raw_records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date.isoformat(),
                    "factor_name": "pb_ratio",
                    "factor_value": pb,
                    "source": "factor_transform",
                    "metric_frequency": "daily",
                    "source_report_date": p_row["observation_date"].isoformat(),
                }
            )
    if not raw_records:
        return []

    records: List[Dict[str, Any]] = []
    by_symbol: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for row in raw_records:
        symbol = str(row.get("symbol") or "")
        obs_date = str(row.get("observation_date") or "")
        if not symbol or not obs_date:
            continue
        by_symbol.setdefault(symbol, {}).setdefault(obs_date, []).append(row)

    for symbol in sorted(by_symbol.keys()):
        by_date = by_symbol[symbol]
        date_index = sorted(by_date.keys())
        if not date_index:
            continue

        bday_dates = [d for d in date_index if pd.Timestamp(d).weekday() < 5]
        if not bday_dates:
            bday_dates = date_index
        bday_pos = {d: i for i, d in enumerate(bday_dates)}

        values_by_date: Dict[str, List[float]] = {}
        for d in date_index:
            values_by_date[d] = [float(r["factor_value"]) for r in by_date[d]]

        def _window_values_for_date(current_date: str) -> List[float]:
            ref = current_date
            if ref not in bday_pos:
                ref = max((d for d in bday_dates if d <= current_date), default="")
            if not ref:
                return values_by_date.get(current_date, [])

            end_idx = bday_pos[ref]
            start_idx = max(0, end_idx - pb_winsor_lookback_bdays + 1)
            window_bdays = set(bday_dates[start_idx : end_idx + 1])

            out: List[float] = []
            for d in date_index:
                if d in window_bdays and d <= current_date:
                    out.extend(values_by_date.get(d, []))
            return out

        for obs_date in date_index:
            day_rows = by_date[obs_date]
            window_values = _window_values_for_date(obs_date)
            if len(window_values) >= pb_min_sample_for_dynamic_cap:
                cap_value = float(pd.Series(window_values).quantile(0.99))
            else:
                cap_value = pb_fallback_cap
            for row in day_rows:
                row["factor_value"] = float(min(float(row["factor_value"]), cap_value))
                records.append(row)

    return records


def _compute_debt_to_equity_daily_asof(
    df, end_date: date, start_date: date
) -> List[Dict[str, Any]]:
    import pandas as pd

    debt = df[df["factor_name"] == "total_debt"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "debt"})
    equity = df[df["factor_name"] == "total_shareholder_equity"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "equity"})
    if debt.empty or equity.empty:
        return []
    debt["debt"] = pd.to_numeric(debt["debt"], errors="coerce")
    equity["equity"] = pd.to_numeric(equity["equity"], errors="coerce")

    records: List[Dict[str, Any]] = []
    symbols = set(debt["symbol"].dropna().unique())
    symbols.update(equity["symbol"].dropna().unique())
    for symbol in sorted(symbols):
        ds = debt[debt["symbol"] == symbol].sort_values("observation_date")
        es = equity[equity["symbol"] == symbol].sort_values("observation_date")
        if ds.empty or es.empty:
            continue
        for obs_ts in pd.date_range(start=start_date, end=end_date, freq="D"):
            obs_date = obs_ts.date()
            d_row = _latest_financial_with_staleness_logging(
                ds,
                cutoff=obs_date,
                factor="debt_to_equity",
                symbol=symbol,
                metric="total_debt",
            )
            e_row = _latest_financial_with_staleness_logging(
                es,
                cutoff=obs_date,
                factor="debt_to_equity",
                symbol=symbol,
                metric="total_shareholder_equity",
            )
            if d_row is None or e_row is None:
                continue
            debt_v = _to_float_or_none(d_row["debt"])
            equity_v = _to_float_or_none(e_row["equity"])
            if debt_v is None or equity_v is None or equity_v <= 0:
                continue
            records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date.isoformat(),
                    "factor_name": "debt_to_equity",
                    "factor_value": float(debt_v / equity_v),
                    "source": "factor_transform",
                    "metric_frequency": "daily",
                    "source_report_date": max(
                        d_row["observation_date"], e_row["observation_date"]
                    ).isoformat(),
                }
            )
    return records


def _compute_ebitda_margin(df, end_date: date, start_date: date) -> List[Dict[str, Any]]:
    import pandas as pd

    ebitda = df[df["factor_name"] == "enterprise_ebitda"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "ebitda"})
    revenue = df[df["factor_name"] == "enterprise_revenue"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "revenue"})
    if ebitda.empty or revenue.empty:
        return []
    ebitda["ebitda"] = pd.to_numeric(ebitda["ebitda"], errors="coerce")
    revenue["revenue"] = pd.to_numeric(revenue["revenue"], errors="coerce")

    records: List[Dict[str, Any]] = []
    symbols = set(ebitda["symbol"].dropna().unique())
    symbols.update(revenue["symbol"].dropna().unique())
    for symbol in sorted(symbols):
        es = ebitda[ebitda["symbol"] == symbol].sort_values("observation_date")
        rs = revenue[revenue["symbol"] == symbol].sort_values("observation_date")
        if es.empty or rs.empty:
            continue
        for obs_ts in pd.date_range(start=start_date, end=end_date, freq="D"):
            obs_date = obs_ts.date()
            e_row = _latest_financial_with_staleness_logging(
                es,
                cutoff=obs_date,
                factor="ebitda_margin",
                symbol=symbol,
                metric="enterprise_ebitda",
            )
            r_row = _latest_financial_with_staleness_logging(
                rs,
                cutoff=obs_date,
                factor="ebitda_margin",
                symbol=symbol,
                metric="enterprise_revenue",
            )
            if e_row is None or r_row is None:
                continue
            ebitda_v = _to_float_or_none(e_row["ebitda"])
            rev_v = _to_float_or_none(r_row["revenue"])
            if ebitda_v is None or rev_v is None or rev_v <= 0:
                continue
            records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date.isoformat(),
                    "factor_name": "ebitda_margin",
                    "factor_value": float(ebitda_v / rev_v),
                    "source": "factor_transform",
                    "metric_frequency": "daily",
                    "source_report_date": max(
                        e_row["observation_date"], r_row["observation_date"]
                    ).isoformat(),
                }
            )
    return records


def _compute_technical_factors_daily(df, end_date: date, start_date: date) -> List[Dict[str, Any]]:
    """Compute daily technical factors ``momentum_1m`` and ``volatility_20d``."""
    import pandas as pd

    price = (
        df[df["factor_name"] == "adjusted_close_price"][
            ["symbol", "observation_date", "factor_value"]
        ]
        .rename(columns={"factor_value": "price"})
        .copy()
    )
    if price.empty:
        return []
    price["price"] = pd.to_numeric(price["price"], errors="coerce")

    records: List[Dict[str, Any]] = []
    for symbol in sorted(price["symbol"].dropna().unique()):
        ps = price[price["symbol"] == symbol].sort_values("observation_date").copy()
        if ps.empty:
            continue
        ps = ps[
            (ps["observation_date"] >= start_date) & (ps["observation_date"] <= end_date)
        ].copy()
        if ps.empty:
            continue
        ps = ps.dropna(subset=["price"])
        ps = ps[ps["price"] > 0]
        if len(ps) < 20:
            continue

        close_series = ps.set_index("observation_date")["price"]
        momentum = close_series / close_series.shift(20) - 1.0
        volatility = close_series.pct_change().rolling(window=20).std()

        for obs_date, value in momentum.dropna().items():
            v = _to_float_or_none(value)
            if v is None:
                continue
            records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date.isoformat(),
                    "factor_name": "momentum_1m",
                    "factor_value": float(v),
                    "source": "factor_transform",
                    "metric_frequency": "daily",
                    "source_report_date": obs_date.isoformat(),
                }
            )
        for obs_date, value in volatility.dropna().items():
            v = _to_float_or_none(value)
            if v is None:
                continue
            records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date.isoformat(),
                    "factor_name": "volatility_20d",
                    "factor_value": float(v),
                    "source": "factor_transform",
                    "metric_frequency": "daily",
                    "source_report_date": obs_date.isoformat(),
                }
            )
    return records


def _compute_sentiment_30d_avg(df, end_date: date, start_date: date) -> List[Dict[str, Any]]:
    """Compute daily ``sentiment_30d_avg`` and ``article_count_30d`` factors."""
    import pandas as pd

    sentiment_atomic = df[df["factor_name"] == "news_sentiment_daily"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "sentiment"})
    count_atomic = df[df["factor_name"] == "news_article_count_daily"][
        ["symbol", "observation_date", "factor_value"]
    ].rename(columns={"factor_value": "article_count"})
    if sentiment_atomic.empty and count_atomic.empty:
        return []

    records: List[Dict[str, Any]] = []
    symbols = set(sentiment_atomic["symbol"].dropna().unique())
    symbols.update(count_atomic["symbol"].dropna().unique())
    for symbol in sorted(symbols):
        ds = (
            sentiment_atomic[sentiment_atomic["symbol"] == symbol]
            .sort_values("observation_date")
            .copy()
        )
        ds["sentiment"] = pd.to_numeric(ds["sentiment"], errors="coerce")
        ds["observation_ts"] = pd.to_datetime(ds["observation_date"], errors="coerce")
        ds = ds.dropna(subset=["sentiment", "observation_ts"])
        # Step 1: daily sentiment (or multiple rows per day) -> daily mean.
        daily_sentiment = (
            ds.groupby(["symbol", "observation_ts"], as_index=False)["sentiment"]
            .mean()
            .sort_values("observation_ts")
        )
        # Step 1b: daily article count atomic.
        daily_count_rows = count_atomic[count_atomic["symbol"] == symbol].copy()
        daily_count_rows["observation_ts"] = pd.to_datetime(
            daily_count_rows["observation_date"], errors="coerce"
        )
        daily_count_rows["article_count"] = pd.to_numeric(
            daily_count_rows["article_count"], errors="coerce"
        )
        daily_count_rows = daily_count_rows.dropna(subset=["observation_ts"])
        if not daily_count_rows.empty:
            daily_count = (
                daily_count_rows.groupby(["symbol", "observation_ts"], as_index=False)[
                    "article_count"
                ]
                .sum()
                .sort_values("observation_ts")
            )
        else:
            daily_count = pd.DataFrame(columns=["symbol", "observation_ts", "article_count"])

        # Step 2: fill missing calendar days with 0.0 sentiment.
        full_dates = pd.date_range(start=start_date, end=end_date, freq="D")
        daily = daily_sentiment.set_index("observation_ts").reindex(full_dates)
        daily.index.name = "observation_ts"
        daily["symbol"] = symbol
        daily["sentiment"] = daily["sentiment"].fillna(0.0)

        daily_count_filled = daily_count.set_index("observation_ts").reindex(full_dates)
        daily["article_count"] = pd.to_numeric(
            daily_count_filled["article_count"], errors="coerce"
        ).fillna(0.0)

        daily = daily.reset_index()
        daily["observation_date"] = daily["observation_ts"].dt.date
        # Step 3: true 30-day rolling stats.
        daily["sentiment_30d"] = daily.rolling("30D", on="observation_ts", min_periods=1)[
            "sentiment"
        ].mean()
        daily["article_count_30d"] = daily.rolling("30D", on="observation_ts", min_periods=1)[
            "article_count"
        ].sum()

        for row in daily.itertuples(index=False):
            obs_date = row.observation_date
            v = max(-1.0, min(1.0, float(row.sentiment_30d)))
            records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date.isoformat(),
                    "factor_name": "sentiment_30d_avg",
                    "factor_value": float(v),
                    "source": "factor_transform",
                    "metric_frequency": "daily",
                    "source_report_date": obs_date.isoformat(),
                }
            )
            records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date.isoformat(),
                    "factor_name": "article_count_30d",
                    "factor_value": float(row.article_count_30d),
                    "source": "factor_transform",
                    "metric_frequency": "daily",
                    "source_report_date": obs_date.isoformat(),
                }
            )
    return records


def compute_final_factor_records(
    atomic_records: Iterable[Dict[str, Any]],
    run_date: str,
    backfill_years: int,
    output_frequency: str = "daily",
) -> List[Dict[str, Any]]:
    """Compute final factors from atomic records."""
    import pandas as pd

    _reset_quality_event_counts()
    records = list(atomic_records)
    if not records:
        return []

    df = pd.DataFrame.from_records(records)
    if df.empty:
        return []
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce").dt.date
    df = df.dropna(subset=["observation_date", "symbol", "factor_name"])
    if df.empty:
        return []

    end_date = datetime.strptime(run_date, "%Y-%m-%d").date()
    lookback_days = max(0, int(round(365.25 * max(int(backfill_years), 0))))
    start_date = end_date - timedelta(days=lookback_days)
    data_start_date = start_date - timedelta(days=370)
    df = df[
        (df["observation_date"] >= data_start_date) & (df["observation_date"] <= end_date)
    ].copy()
    if df.empty:
        return []

    out: List[Dict[str, Any]] = []
    out.extend(_compute_technical_factors_daily(df, end_date, start_date))
    out.extend(_compute_dividend_yield_daily_asof(df, end_date, start_date))
    out.extend(_compute_pb_ratio_daily_asof(df, end_date, start_date))
    out.extend(_compute_debt_to_equity_daily_asof(df, end_date, start_date))
    out.extend(_compute_ebitda_margin(df, end_date, start_date))
    out.extend(_compute_sentiment_30d_avg(df, end_date, start_date))
    _flush_quality_event_summary()
    return _sample_records_by_frequency(out, output_frequency=output_frequency)


def _load_atomic_records_from_postgres(
    run_date: str,
    backfill_years: int,
    symbols: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Load atomic market/financial/news factors needed for final-factor build."""
    end_date = datetime.strptime(run_date, "%Y-%m-%d").date()
    lookback_days = max(0, int(round(365.25 * max(int(backfill_years), 0))))
    start_date = end_date - timedelta(days=lookback_days)
    query_start_date = start_date - timedelta(days=370)
    params: Dict[str, Any] = {
        "start_date": query_start_date.isoformat(),
        "end_date": run_date,
    }

    has_symbols = False
    if symbols:
        params["symbols"] = [str(s).strip().upper() for s in symbols if str(s).strip()]
        has_symbols = bool(params["symbols"])

    market_sql = text(
        """
        SELECT symbol, observation_date, factor_name, factor_value, source,
               metric_frequency, source_report_date
        FROM systematic_equity.factor_observations
        WHERE observation_date BETWEEN :start_date AND :end_date
          AND factor_name = ANY(:factor_names)
        ORDER BY symbol, observation_date, factor_name
        """
    )
    market_sql_with_symbols = text(
        """
        SELECT symbol, observation_date, factor_name, factor_value, source,
               metric_frequency, source_report_date
        FROM systematic_equity.factor_observations
        WHERE observation_date BETWEEN :start_date AND :end_date
          AND factor_name = ANY(:factor_names)
          AND symbol = ANY(:symbols)
        ORDER BY symbol, observation_date, factor_name
        """
    )
    market_params = dict(params)
    market_params["factor_names"] = sorted(MARKET_ATOMIC_FACTORS.union(ALTERNATIVE_ATOMIC_FACTORS))

    financial_sql = text(
        """
        SELECT
            symbol,
            report_date AS observation_date,
            metric_name AS factor_name,
            metric_value AS factor_value,
            source,
            period_type AS metric_frequency,
            as_of AS source_report_date
        FROM systematic_equity.financial_observations
        WHERE report_date BETWEEN :start_date AND :end_date
          AND metric_name = ANY(:metric_names)
        ORDER BY symbol, report_date, metric_name
        """
    )
    financial_sql_with_symbols = text(
        """
        SELECT
            symbol,
            report_date AS observation_date,
            metric_name AS factor_name,
            metric_value AS factor_value,
            source,
            period_type AS metric_frequency,
            as_of AS source_report_date
        FROM systematic_equity.financial_observations
        WHERE report_date BETWEEN :start_date AND :end_date
          AND metric_name = ANY(:metric_names)
          AND symbol = ANY(:symbols)
        ORDER BY symbol, report_date, metric_name
        """
    )
    financial_params = dict(params)
    financial_params["metric_names"] = sorted(FINANCIAL_ATOMIC_FACTORS)

    fallback_financial_sql = text(
        """
        SELECT symbol, observation_date, factor_name, factor_value, source,
               metric_frequency, source_report_date
        FROM systematic_equity.factor_observations
        WHERE observation_date BETWEEN :start_date AND :end_date
          AND factor_name = ANY(:factor_names)
        ORDER BY symbol, observation_date, factor_name
        """
    )
    fallback_financial_sql_with_symbols = text(
        """
        SELECT symbol, observation_date, factor_name, factor_value, source,
               metric_frequency, source_report_date
        FROM systematic_equity.factor_observations
        WHERE observation_date BETWEEN :start_date AND :end_date
          AND factor_name = ANY(:factor_names)
          AND symbol = ANY(:symbols)
        ORDER BY symbol, observation_date, factor_name
        """
    )
    fallback_financial_params = dict(params)
    fallback_financial_params["factor_names"] = sorted(FINANCIAL_ATOMIC_FACTORS)

    engine = get_db_engine()
    with engine.connect() as conn:
        selected_market_sql = market_sql_with_symbols if has_symbols else market_sql
        selected_financial_sql = financial_sql_with_symbols if has_symbols else financial_sql
        selected_fallback_sql = (
            fallback_financial_sql_with_symbols if has_symbols else fallback_financial_sql
        )
        market_rows = conn.execute(selected_market_sql, market_params).mappings().all()
        try:
            financial_rows = conn.execute(selected_financial_sql, financial_params).mappings().all()
        except Exception as exc:
            logger.warning(
                "financial_source_fallback=True reason=%r "
                "source=financial_observations fallback=factor_observations",
                exc,
            )
            financial_rows = (
                conn.execute(selected_fallback_sql, fallback_financial_params).mappings().all()
            )

    rows = [dict(r) for r in market_rows]
    rows.extend(dict(r) for r in financial_rows)
    rows.sort(
        key=lambda r: (
            str(r.get("symbol") or ""),
            str(r.get("observation_date") or ""),
            str(r.get("factor_name") or ""),
        )
    )
    return rows


def build_and_load_final_factors(
    run_date: str,
    backfill_years: int,
    *,
    output_frequency: str = "daily",
    symbols: Optional[List[str]] = None,
    dry_run: bool = False,
) -> int:
    """Build final factors from atomic factors in Postgres and load them back."""
    atomic_records = _load_atomic_records_from_postgres(
        run_date=run_date, backfill_years=backfill_years, symbols=symbols
    )
    final_records = compute_final_factor_records(
        atomic_records=atomic_records,
        run_date=run_date,
        backfill_years=backfill_years,
        output_frequency=output_frequency,
    )
    if not final_records:
        return 0
    return load_curated(final_records, dry_run=dry_run)
