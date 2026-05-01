from __future__ import annotations

"""Summary performance metrics for the CW2 backtest engine."""

from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd


def compute_backtest_metrics(
    performance_records: Sequence[Dict[str, Any]],
    *,
    initial_nav: float = 1.0,
) -> List[Dict[str, Any]]:
    """Compute return, risk, risk-adjusted, and portfolio metrics from monthly performance rows."""
    if not performance_records:
        return []

    df = pd.DataFrame(performance_records).copy()
    if df.empty:
        return []

    df["period_end_date"] = pd.to_datetime(df["period_end_date"], errors="coerce")
    df = df.sort_values("period_end_date").reset_index(drop=True)

    for col in (
        "gross_return",
        "net_return",
        "benchmark_return",
        "risk_free_return",
        "excess_return",
        "portfolio_nav",
        "benchmark_nav",
        "turnover",
        "gross_turnover",
        "transaction_cost",
        "num_holdings",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    monthly_net = df["net_return"].fillna(0.0)
    monthly_gross = df["gross_return"].fillna(0.0)
    monthly_bench = df["benchmark_return"].fillna(0.0)
    monthly_rf = (
        df["risk_free_return"].fillna(0.0)
        if "risk_free_return" in df.columns
        else pd.Series(0.0, index=df.index, dtype=float)
    )
    monthly_excess = monthly_net - monthly_bench
    monthly_net_excess_over_rf = monthly_net - monthly_rf
    n_months = int(len(df))

    nav_end = float(df["portfolio_nav"].iloc[-1]) if n_months else float(initial_nav)
    bench_nav_end = float(df["benchmark_nav"].iloc[-1]) if n_months else float(initial_nav)
    total_return = nav_end / float(initial_nav) - 1.0
    benchmark_total_return = bench_nav_end / float(initial_nav) - 1.0
    annualized_return = _annualize_total_return(total_return, n_months)
    benchmark_annualized_return = _annualize_total_return(benchmark_total_return, n_months)
    excess_return_annualized = (
        annualized_return - benchmark_annualized_return
        if annualized_return is not None and benchmark_annualized_return is not None
        else None
    )
    excess_return_arithmetic_annualized = _annualized_mean(monthly_excess)

    annualized_volatility = _annualized_std(monthly_net)
    tracking_error = _annualized_std(monthly_excess)
    max_drawdown, max_drawdown_duration = _max_drawdown_stats(df["portfolio_nav"], initial_nav)
    beta_raw = _beta(monthly_net, monthly_bench)

    sharpe_ratio = _safe_divide(
        _annualized_mean(monthly_net_excess_over_rf),
        _annualized_std(monthly_net_excess_over_rf),
    )
    information_ratio = _safe_divide(
        excess_return_arithmetic_annualized,
        tracking_error,
    )
    sortino_ratio = _safe_divide(
        _annualized_mean(monthly_net_excess_over_rf),
        _downside_deviation(monthly_net_excess_over_rf),
    )
    mar_ratio = _safe_divide(
        annualized_return, abs(max_drawdown) if max_drawdown is not None else None
    )
    hit_rate_vs_benchmark_ticker = float((monthly_net > monthly_bench).mean()) if n_months else None

    gross_nav_end = float(initial_nav) * float((1.0 + monthly_gross).prod())
    gross_total_return = gross_nav_end / float(initial_nav) - 1.0
    gross_annualized_return = _annualize_total_return(gross_total_return, n_months)
    total_cost_drag = (
        gross_annualized_return - annualized_return
        if gross_annualized_return is not None and annualized_return is not None
        else None
    )
    annualized_turnover_ratio_one_way = (
        _series_or_none(df["turnover"].mean()) * 12.0 if "turnover" in df.columns else None
    )
    avg_monthly_turnover_two_way = (
        _series_or_none(df["gross_turnover"].mean()) if "gross_turnover" in df.columns else None
    )
    annualized_turnover_ratio_two_way = (
        avg_monthly_turnover_two_way * 12.0 if avg_monthly_turnover_two_way is not None else None
    )
    avg_monthly_turnover_one_way = _series_or_none(df["turnover"].mean())

    metrics = [
        _metric("return", "total_return", total_return, "%"),
        _metric("return", "annualized_return", annualized_return, "%"),
        _metric("return", "gross_annualized_return", gross_annualized_return, "%"),
        _metric("return", "benchmark_total_return", benchmark_total_return, "%"),
        _metric("return", "excess_return_annualized", excess_return_annualized, "%"),
        _metric("return", "best_month", _series_or_none(monthly_net.max()), "%"),
        _metric("return", "worst_month", _series_or_none(monthly_net.min()), "%"),
        _metric(
            "return",
            "pct_positive_months",
            float((monthly_net > 0).mean()) if n_months else None,
            "%",
        ),
        _metric("risk", "annualized_volatility", annualized_volatility, "%"),
        _metric("risk", "tracking_error", tracking_error, "%"),
        _metric("risk", "max_drawdown", max_drawdown, "%"),
        _metric("risk", "max_drawdown_duration", float(max_drawdown_duration), "months"),
        _metric("risk", "beta_raw", beta_raw, "-"),
        _metric("risk", "beta", beta_raw, "-"),
        _metric("risk_adjusted", "sharpe_ratio", sharpe_ratio, "x"),
        _metric("risk_adjusted", "information_ratio", information_ratio, "x"),
        _metric("risk_adjusted", "sortino_ratio", sortino_ratio, "x"),
        _metric("risk_adjusted", "mar_ratio", mar_ratio, "x"),
        _metric(
            "risk_adjusted",
            "hit_rate_vs_benchmark_ticker",
            hit_rate_vs_benchmark_ticker,
            "%",
        ),
        _metric("risk_adjusted", "hit_rate", hit_rate_vs_benchmark_ticker, "%"),
        _metric("portfolio", "avg_holdings", _series_or_none(df["num_holdings"].mean()), "-"),
        _metric(
            "portfolio",
            "avg_monthly_turnover_one_way",
            avg_monthly_turnover_one_way,
            "%",
        ),
        _metric(
            "portfolio",
            "avg_monthly_turnover",
            avg_monthly_turnover_one_way,
            "%",
        ),
        _metric(
            "portfolio",
            "annualized_turnover_ratio_one_way",
            annualized_turnover_ratio_one_way,
            "%",
        ),
        _metric(
            "portfolio",
            "annualized_turnover_ratio",
            annualized_turnover_ratio_one_way,
            "%",
        ),
        _metric(
            "portfolio",
            "avg_monthly_turnover_two_way",
            avg_monthly_turnover_two_way,
            "%",
        ),
        _metric(
            "portfolio",
            "avg_monthly_gross_turnover",
            avg_monthly_turnover_two_way,
            "%",
        ),
        _metric(
            "portfolio",
            "annualized_turnover_ratio_two_way",
            annualized_turnover_ratio_two_way,
            "%",
        ),
        _metric(
            "portfolio",
            "avg_transaction_cost_bps",
            _series_or_none(df["transaction_cost"].mean()),
            "bps",
        ),
        _metric("portfolio", "total_cost_drag", total_cost_drag, "%"),
    ]
    return [metric for metric in metrics if metric["metric_value"] is not None]


def _metric(group: str, name: str, value: Optional[float], unit: str) -> Dict[str, Any]:
    if value is None or pd.isna(value):
        metric_value = None
    elif unit == "%":
        metric_value = float(value) * 100.0
    elif unit == "bps":
        metric_value = float(value) * 10000.0
    else:
        metric_value = float(value)
    return {
        "metric_group": group,
        "metric_name": name,
        "metric_value": metric_value,
        "metric_unit": unit,
    }


def _annualize_total_return(total_return: float, n_months: int) -> Optional[float]:
    if n_months <= 0 or (1.0 + total_return) <= 0:
        return None
    return (1.0 + float(total_return)) ** (12.0 / float(n_months)) - 1.0


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


def _downside_deviation(series: Iterable[float]) -> Optional[float]:
    values = pd.Series(series, dtype=float).dropna()
    if values.empty:
        return None
    downside = np.minimum(values.to_numpy(), 0.0)
    if not len(downside):
        return None
    return float(np.sqrt(np.mean(np.square(downside)))) * float(np.sqrt(12.0))


def _max_drawdown_stats(
    nav_series: Iterable[float], initial_nav: float
) -> tuple[Optional[float], int]:
    nav = pd.Series(nav_series, dtype=float).dropna().reset_index(drop=True)
    if nav.empty:
        return None, 0

    nav_with_start = pd.concat([pd.Series([float(initial_nav)]), nav], ignore_index=True)
    running_peak = nav_with_start.cummax()
    drawdown = nav_with_start / running_peak - 1.0
    max_drawdown = abs(float(drawdown.min()))

    duration = 0
    max_duration = 0
    for value in drawdown.iloc[1:]:
        if value < 0:
            duration += 1
            max_duration = max(max_duration, duration)
        else:
            duration = 0
    return max_drawdown, max_duration


def _beta(strategy_returns: Iterable[float], benchmark_returns: Iterable[float]) -> Optional[float]:
    strat = pd.Series(strategy_returns, dtype=float).dropna()
    bench = pd.Series(benchmark_returns, dtype=float).dropna()
    joined = pd.concat([strat, bench], axis=1).dropna()
    if len(joined) < 2:
        return None
    strategy = joined.iloc[:, 0]
    benchmark = joined.iloc[:, 1]
    benchmark_var = float(benchmark.var(ddof=1))
    if benchmark_var <= 0:
        return None
    covariance = float(strategy.cov(benchmark))
    return covariance / benchmark_var


def _safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0 or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)


def _series_or_none(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return float(value)
