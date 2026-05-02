from __future__ import annotations

"""Proxy factor attribution for CW2 strategy analysis."""

from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from team_Pearson.coursework_two.modules.backtest.data_loader import (
    load_adjusted_close_prices,
    load_trading_calendar,
)
from team_Pearson.coursework_two.modules.backtest.execution import compute_period_simple_returns

_SCHEMA = "systematic_equity"
_FACTOR_COLUMNS = {
    "quality": "quality_score",
    "value": "value_score",
    "market_technical": "market_technical_score",
    "sentiment": "sentiment_score",
    "dividend": "dividend_score",
}


def compute_factor_attribution(
    run_context: Dict[str, Any],
    db_engine: Engine,
) -> List[Dict[str, Any]]:
    """Compute a factor-contribution proxy from sleeve exposures and factor spreads."""
    periods = list(run_context.get("periods") or [])
    if not periods:
        return []

    run_id = str(run_context["run_id"])
    rebalance_dates = [period["rebalance_date"] for period in periods]
    holdings_by_date = _load_strategy_holdings(run_id, db_engine)
    factor_scores_by_date = _load_factor_scores(rebalance_dates, db_engine)
    max_ffill = int(
        (run_context.get("config", {}).get("backtest", {}) or {}).get("max_forward_fill_days", 5)
    )
    calendar = load_trading_calendar(
        db_engine,
        min(period["execution_date"] for period in periods)
        - timedelta(days=max(10, max_ffill * 3)),
        max(period["period_end_date"] for period in periods),
        benchmark_ticker=str(run_context["run_row"]["benchmark_ticker"]),
    )

    rows: List[Dict[str, Any]] = []
    for period in periods:
        rebalance_date = period["rebalance_date"]
        holdings = holdings_by_date.get(rebalance_date) or {}
        if not holdings:
            continue
        factor_df = factor_scores_by_date.get(rebalance_date)
        if factor_df is None or factor_df.empty:
            continue

        symbols = sorted(
            str(symbol) for symbol in factor_df["symbol"].dropna().astype(str).unique()
        )
        if not symbols:
            continue
        prices = load_adjusted_close_prices(
            db_engine,
            symbols,
            period["execution_date"],
            period["period_end_date"],
            lookback_days=max(10, max_ffill * 3),
        )
        period_returns, _ = compute_period_simple_returns(
            prices,
            calendar,
            period["execution_date"],
            period["period_end_date"],
            max_forward_fill_days=max_ffill,
        )

        for factor_name, score_col in _FACTOR_COLUMNS.items():
            available = factor_df[["symbol", score_col]].copy()
            available[score_col] = pd.to_numeric(available[score_col], errors="coerce")
            available["symbol"] = available["symbol"].astype(str)
            available = available.dropna(subset=[score_col])
            available = available[available["symbol"].isin(period_returns.keys())]
            if len(available) < 6:
                continue

            top_symbols, bottom_symbols = _top_bottom_bucket_symbols(available, score_col)
            if not top_symbols or not bottom_symbols:
                continue

            strategy_exposure = _weighted_factor_exposure(available, holdings, score_col)
            universe_exposure = _average_factor_exposure(available[score_col])
            active_exposure = (
                None
                if strategy_exposure is None or universe_exposure is None
                else float(strategy_exposure) - float(universe_exposure)
            )
            top_bucket_return = _average_symbol_return(top_symbols, period_returns)
            bottom_bucket_return = _average_symbol_return(bottom_symbols, period_returns)
            factor_spread_return = (
                None
                if top_bucket_return is None or bottom_bucket_return is None
                else float(top_bucket_return) - float(bottom_bucket_return)
            )
            contribution_proxy = (
                None
                if active_exposure is None or factor_spread_return is None
                else float(active_exposure) * float(factor_spread_return)
            )
            rows.append(
                {
                    "run_id": run_id,
                    "rebalance_date": rebalance_date,
                    "period_end_date": period["period_end_date"],
                    "factor_name": factor_name,
                    "strategy_exposure": strategy_exposure,
                    "universe_exposure": universe_exposure,
                    "active_exposure": active_exposure,
                    "factor_spread_return": _percent(factor_spread_return),
                    "contribution_proxy": _percent(contribution_proxy),
                    "top_bucket_size": len(top_symbols),
                    "bottom_bucket_size": len(bottom_symbols),
                    "attribution_method": "exposure_x_factor_spread_proxy",
                }
            )
    return rows


def _load_strategy_holdings(run_id: str, db_engine: Engine) -> Dict[date, Dict[str, float]]:
    sql = text(f"""
        SELECT rebalance_date, symbol, executed_weight
        FROM {_SCHEMA}.backtest_holdings
        WHERE run_id = :run_id
        """)
    with db_engine.connect() as conn:
        df = pd.DataFrame(conn.execute(sql, {"run_id": run_id}).mappings().all())
    if df.empty:
        return {}
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce").dt.date
    df["symbol"] = df["symbol"].astype(str)
    df["executed_weight"] = pd.to_numeric(df["executed_weight"], errors="coerce")
    out: Dict[date, Dict[str, float]] = {}
    for rebalance_date, group in df.groupby("rebalance_date"):
        weights = {
            str(row["symbol"]): float(row["executed_weight"])
            for _, row in group.iterrows()
            if pd.notna(row["executed_weight"]) and float(row["executed_weight"]) > 0.0
        }
        if weights:
            out[rebalance_date] = weights
    return out


def _load_factor_scores(
    rebalance_dates: Iterable[date],
    db_engine: Engine,
) -> Dict[date, pd.DataFrame]:
    dates = sorted({d for d in rebalance_dates if d is not None})
    if not dates:
        return {}
    sql = text(f"""
        SELECT as_of_date, symbol, quality_score, value_score, market_technical_score,
               sentiment_score, dividend_score
        FROM {_SCHEMA}.feature_factor_scores
        WHERE as_of_date = ANY(:dates)
        """)
    with db_engine.connect() as conn:
        df = pd.DataFrame(conn.execute(sql, {"dates": dates}).mappings().all())
    if df.empty:
        return {}
    df["as_of_date"] = pd.to_datetime(df["as_of_date"], errors="coerce").dt.date
    out: Dict[date, pd.DataFrame] = {}
    for as_of_date, group in df.groupby("as_of_date"):
        out[as_of_date] = group.copy()
    return out


def _top_bottom_bucket_symbols(df: pd.DataFrame, score_col: str) -> tuple[List[str], List[str]]:
    ordered = df.sort_values(score_col)
    bucket_size = max(1, len(ordered) // 5)
    bottom = ordered.head(bucket_size)["symbol"].astype(str).tolist()
    top = ordered.tail(bucket_size)["symbol"].astype(str).tolist()
    return top, bottom


def _weighted_factor_exposure(
    df: pd.DataFrame,
    holdings: Mapping[str, float],
    score_col: str,
) -> float | None:
    matched = df[df["symbol"].isin(holdings.keys())].copy()
    if matched.empty:
        return None
    matched["weight"] = matched["symbol"].map(lambda symbol: float(holdings.get(str(symbol), 0.0)))
    risky_total = float(matched["weight"].sum())
    if risky_total <= 0.0:
        return None
    return float((matched[score_col] * matched["weight"]).sum() / risky_total)


def _average_factor_exposure(values: Iterable[float]) -> float | None:
    series = pd.Series(list(values), dtype=float).dropna()
    if series.empty:
        return None
    return float(series.mean())


def _average_symbol_return(
    symbols: Iterable[str], period_returns: Mapping[str, float]
) -> float | None:
    values = [float(period_returns[symbol]) for symbol in symbols if symbol in period_returns]
    if not values:
        return None
    return float(pd.Series(values, dtype=float).mean())


def _percent(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value) * 100.0
