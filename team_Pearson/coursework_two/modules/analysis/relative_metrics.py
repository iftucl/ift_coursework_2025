from __future__ import annotations

"""Relative performance metrics for strategy vs benchmark/baseline series."""

from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

_SCHEMA = "systematic_equity"


def compute_relative_metrics(
    run_context: Dict[str, Any], db_engine: Engine
) -> List[Dict[str, Any]]:
    """Compute relative metrics versus all benchmark series available for the run."""
    run_id = str(run_context["run_id"])
    strategy = _load_strategy_series(run_id, db_engine)
    benchmarks = _load_benchmark_series(run_id, db_engine)
    if strategy.empty or not benchmarks:
        return []

    out: List[Dict[str, Any]] = []
    run_row = dict(run_context.get("run_row") or {})
    capture_series = {
        str(
            run_context["analysis_config"].get("primary_benchmark")
            or run_row.get("benchmark_ticker")
            or "SPY"
        ),
        str(run_row.get("benchmark_ticker") or ""),
    }
    for series_name, bench in benchmarks.items():
        joined = strategy.join(
            bench.rename(
                columns={
                    "period_return": "versus_return",
                    "nav": "versus_nav",
                    "risk_free_return": "versus_risk_free_return",
                }
            ),
            how="inner",
        )
        if joined.empty:
            continue

        excess = joined["strategy_return"] - joined["versus_return"]
        strategy_total = float(joined["strategy_nav"].iloc[-1]) - 1.0
        versus_total = float(joined["versus_nav"].iloc[-1]) - 1.0
        strategy_ann = _annualize_total_return(strategy_total, len(joined))
        versus_ann = _annualize_total_return(versus_total, len(joined))
        excess_ann = (
            None if strategy_ann is None or versus_ann is None else strategy_ann - versus_ann
        )
        excess_ann_arithmetic = _annualized_mean(excess)
        tracking_error = _annualized_std(excess)
        information_ratio = _safe_divide(excess_ann_arithmetic, tracking_error)
        hit_rate = float((joined["strategy_return"] > joined["versus_return"]).mean())
        strategy_max_dd = _max_drawdown(joined["strategy_nav"])
        versus_max_dd = _max_drawdown(joined["versus_nav"])

        metrics = [
            _metric(
                run_id,
                series_name,
                "excess_return_total",
                float(joined["strategy_nav"].iloc[-1]) / float(joined["versus_nav"].iloc[-1]) - 1.0,
                "%",
            ),
            _metric(run_id, series_name, "excess_return_annualized", excess_ann, "%"),
            _metric(run_id, series_name, "hit_rate", hit_rate, "%"),
            _metric(run_id, series_name, "tracking_error", tracking_error, "%"),
            _metric(run_id, series_name, "information_ratio", information_ratio, "x"),
            _metric(
                run_id,
                series_name,
                "max_drawdown_delta",
                (
                    None
                    if strategy_max_dd is None or versus_max_dd is None
                    else strategy_max_dd - versus_max_dd
                ),
                "%",
            ),
        ]
        out.extend(metric for metric in metrics if metric["metric_value"] is not None)

        if series_name in capture_series:
            out.extend(
                metric
                for metric in compute_capture_metrics(
                    strategy_returns=joined["strategy_return"],
                    benchmark_returns=joined["versus_return"],
                    run_id=run_id,
                    versus_series=series_name,
                )
                if metric["metric_value"] is not None
            )
    return out


def compute_capture_metrics(
    *,
    strategy_returns: Iterable[float],
    benchmark_returns: Iterable[float],
    run_id: str,
    versus_series: str,
) -> List[Dict[str, Any]]:
    """Compute up/down capture ratios for a strategy versus an external benchmark."""
    strat = pd.Series(strategy_returns, dtype=float).reset_index(drop=True)
    bench = pd.Series(benchmark_returns, dtype=float).reset_index(drop=True)
    joined = pd.concat([strat, bench], axis=1)
    joined.columns = ["strategy", "benchmark"]
    joined = joined.dropna()
    if joined.empty:
        return []

    up = joined[joined["benchmark"] > 0]
    down = joined[joined["benchmark"] < 0]
    up_capture = None
    down_capture = None
    if not up.empty:
        up_capture = _safe_divide(float(up["strategy"].mean()), float(up["benchmark"].mean()))
    if not down.empty:
        down_capture = _safe_divide(float(down["strategy"].mean()), float(down["benchmark"].mean()))

    return [
        _metric(run_id, versus_series, "up_capture_ratio", up_capture, "x"),
        _metric(run_id, versus_series, "down_capture_ratio", down_capture, "x"),
    ]


def _load_strategy_series(run_id: str, db_engine: Engine) -> pd.DataFrame:
    sql = text(f"""
        SELECT period_end_date, net_return, risk_free_return, portfolio_nav
        FROM {_SCHEMA}.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    with db_engine.connect() as conn:
        df = pd.DataFrame(conn.execute(sql, {"run_id": run_id}).mappings().all())
    if df.empty:
        return pd.DataFrame(columns=["strategy_return", "risk_free_return", "strategy_nav"])
    df["period_end_date"] = pd.to_datetime(df["period_end_date"], errors="coerce")
    df["strategy_return"] = pd.to_numeric(df["net_return"], errors="coerce")
    df["risk_free_return"] = pd.to_numeric(df["risk_free_return"], errors="coerce")
    df["strategy_nav"] = pd.to_numeric(df["portfolio_nav"], errors="coerce")
    return df.set_index("period_end_date")[["strategy_return", "risk_free_return", "strategy_nav"]]


def _load_benchmark_series(run_id: str, db_engine: Engine) -> Dict[str, pd.DataFrame]:
    sql = text(f"""
        SELECT period_end_date, series_name, nav, period_return, risk_free_return
        FROM {_SCHEMA}.backtest_benchmark_nav
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    with db_engine.connect() as conn:
        df = pd.DataFrame(conn.execute(sql, {"run_id": run_id}).mappings().all())
    if df.empty:
        return {}
    df["period_end_date"] = pd.to_datetime(df["period_end_date"], errors="coerce")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    df["period_return"] = pd.to_numeric(df["period_return"], errors="coerce")
    df["risk_free_return"] = pd.to_numeric(df["risk_free_return"], errors="coerce")
    out: Dict[str, pd.DataFrame] = {}
    for series_name, group in df.groupby("series_name"):
        out[str(series_name)] = group.set_index("period_end_date")[
            ["nav", "period_return", "risk_free_return"]
        ].sort_index()
    return out


def _metric(
    run_id: str, versus_series: str, name: str, value: Optional[float], unit: str
) -> Dict[str, Any]:
    if value is None or pd.isna(value):
        metric_value = None
    elif unit == "%":
        metric_value = float(value) * 100.0
    else:
        metric_value = float(value)
    return {
        "run_id": run_id,
        "versus_series": versus_series,
        "metric_name": name,
        "metric_value": metric_value,
        "metric_unit": unit,
    }


def _annualize_total_return(total_return: float, n_periods: int) -> Optional[float]:
    if n_periods <= 0 or (1.0 + total_return) <= 0:
        return None
    return (1.0 + float(total_return)) ** (12.0 / float(n_periods)) - 1.0


def _annualized_std(series: Iterable[float]) -> Optional[float]:
    values = pd.Series(series, dtype=float).dropna()
    if len(values) < 2:
        return None
    return float(values.std(ddof=1)) * float(np.sqrt(12.0))


def _annualized_mean(series: Iterable[float]) -> Optional[float]:
    values = pd.Series(series, dtype=float).dropna()
    if values.empty:
        return None
    return float(values.mean()) * 12.0


def _safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0 or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)


def _max_drawdown(nav_series: Iterable[float], *, initial_nav: float = 1.0) -> Optional[float]:
    nav = pd.Series(nav_series, dtype=float).dropna()
    if nav.empty:
        return None
    nav_with_start = pd.concat(
        [pd.Series([float(initial_nav)]), nav.reset_index(drop=True)], ignore_index=True
    )
    running_peak = nav_with_start.cummax()
    drawdown = nav_with_start / running_peak - 1.0
    return abs(float(drawdown.min()))
