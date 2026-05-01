from __future__ import annotations

"""Absolute performance and risk metrics for stored benchmark series."""

from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd


def compute_benchmark_absolute_metrics(
    benchmark_rows: Sequence[Dict[str, Any]] | pd.DataFrame,
    *,
    run_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Compute absolute benchmark metrics from stored NAV/return rows."""
    if isinstance(benchmark_rows, pd.DataFrame):
        df = benchmark_rows.copy()
    else:
        df = pd.DataFrame(list(benchmark_rows))
    if df.empty:
        return []

    if "series_name" not in df.columns:
        return []

    if "period_end_date" in df.columns:
        df["period_end_date"] = pd.to_datetime(df["period_end_date"], errors="coerce")
        df = df.sort_values(["series_name", "period_end_date"], kind="stable")
    if "nav" in df.columns:
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    if "period_return" in df.columns:
        df["period_return"] = pd.to_numeric(df["period_return"], errors="coerce")
    if "gross_return" in df.columns:
        df["gross_return"] = pd.to_numeric(df["gross_return"], errors="coerce")
    if "risk_free_return" in df.columns:
        df["risk_free_return"] = pd.to_numeric(df["risk_free_return"], errors="coerce")
    if "turnover" in df.columns:
        df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce")
    if "gross_turnover" in df.columns:
        df["gross_turnover"] = pd.to_numeric(df["gross_turnover"], errors="coerce")
    if "transaction_cost" in df.columns:
        df["transaction_cost"] = pd.to_numeric(df["transaction_cost"], errors="coerce")

    derived_run_id = run_id
    if derived_run_id is None and "run_id" in df.columns:
        first_value = next(
            (
                str(value)
                for value in df["run_id"].tolist()
                if value is not None and not pd.isna(value)
            ),
            None,
        )
        derived_run_id = first_value

    out: List[Dict[str, Any]] = []
    for series_name, group in df.groupby("series_name", sort=True):
        nav_source = group["nav"] if "nav" in group.columns else pd.Series(dtype=float)
        return_source = (
            group["period_return"] if "period_return" in group.columns else pd.Series(dtype=float)
        )
        risk_free_source = (
            group["risk_free_return"]
            if "risk_free_return" in group.columns
            else pd.Series(0.0, index=group.index, dtype=float)
        )
        gross_return_source = (
            group["gross_return"] if "gross_return" in group.columns else pd.Series(dtype=float)
        )
        turnover_source = (
            group["turnover"] if "turnover" in group.columns else pd.Series(dtype=float)
        )
        gross_turnover_source = (
            group["gross_turnover"] if "gross_turnover" in group.columns else pd.Series(dtype=float)
        )
        transaction_cost_source = (
            group["transaction_cost"]
            if "transaction_cost" in group.columns
            else pd.Series(dtype=float)
        )
        nav = pd.to_numeric(nav_source, errors="coerce").dropna()
        return_frame = pd.DataFrame(
            {
                "period_return": pd.to_numeric(return_source, errors="coerce"),
                "risk_free_return": pd.to_numeric(risk_free_source, errors="coerce").fillna(0.0),
            }
        ).dropna(subset=["period_return"])
        returns = return_frame["period_return"]
        risk_free = return_frame["risk_free_return"]
        if nav.empty:
            continue

        n_periods = int(len(group))
        total_return = float(nav.iloc[-1]) - 1.0
        annualized_return = _annualize_total_return(total_return, n_periods)
        annualized_volatility = _annualized_std(returns)
        max_drawdown = _max_drawdown(nav, initial_nav=1.0)
        gross_returns = pd.to_numeric(gross_return_source, errors="coerce").dropna()
        gross_annualized_return = None
        total_cost_drag = None
        if not gross_returns.empty:
            gross_total_return = float((1.0 + gross_returns).prod() - 1.0)
            gross_annualized_return = _annualize_total_return(
                gross_total_return, len(gross_returns)
            )
            total_cost_drag = (
                gross_annualized_return - annualized_return
                if gross_annualized_return is not None and annualized_return is not None
                else None
            )
        avg_monthly_turnover_one_way = _series_or_none(turnover_source)
        annualized_turnover_ratio_one_way = (
            avg_monthly_turnover_one_way * 12.0
            if avg_monthly_turnover_one_way is not None
            else None
        )
        avg_monthly_turnover_two_way = _series_or_none(gross_turnover_source)
        annualized_turnover_ratio_two_way = (
            avg_monthly_turnover_two_way * 12.0
            if avg_monthly_turnover_two_way is not None
            else None
        )
        avg_transaction_cost_bps = _series_or_none(transaction_cost_source)
        excess_returns = returns.reset_index(drop=True) - risk_free.reset_index(drop=True)
        sharpe_ratio = _safe_divide(
            _annualized_mean(excess_returns),
            _annualized_std(excess_returns),
        )
        sortino_ratio = _safe_divide(
            _annualized_mean(excess_returns),
            _downside_deviation(excess_returns),
        )
        mar_ratio = _safe_divide(
            annualized_return, abs(max_drawdown) if max_drawdown is not None else None
        )
        hit_rate_positive_periods = float((returns > 0).mean()) if not returns.empty else None

        metrics = [
            _metric(derived_run_id, str(series_name), "total_return", total_return, "%"),
            _metric(
                derived_run_id,
                str(series_name),
                "annualized_return",
                annualized_return,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "gross_annualized_return",
                gross_annualized_return,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "annualized_volatility",
                annualized_volatility,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "max_drawdown",
                max_drawdown,
                "%",
            ),
            _metric(derived_run_id, str(series_name), "sharpe_ratio", sharpe_ratio, "x"),
            _metric(derived_run_id, str(series_name), "sortino_ratio", sortino_ratio, "x"),
            _metric(derived_run_id, str(series_name), "mar_ratio", mar_ratio, "x"),
            _metric(
                derived_run_id,
                str(series_name),
                "hit_rate_positive_periods",
                hit_rate_positive_periods,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "hit_rate",
                hit_rate_positive_periods,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "avg_monthly_turnover_one_way",
                avg_monthly_turnover_one_way,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "annualized_turnover_ratio_one_way",
                annualized_turnover_ratio_one_way,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "avg_monthly_turnover_two_way",
                avg_monthly_turnover_two_way,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "annualized_turnover_ratio_two_way",
                annualized_turnover_ratio_two_way,
                "%",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "avg_transaction_cost_bps",
                avg_transaction_cost_bps,
                "bps",
            ),
            _metric(
                derived_run_id,
                str(series_name),
                "total_cost_drag",
                total_cost_drag,
                "%",
            ),
        ]
        out.extend(metric for metric in metrics if metric.get("metric_value") is not None)
    return out


def _metric(
    run_id: Optional[str],
    series_name: str,
    metric_name: str,
    value: Optional[float],
    unit: str,
) -> Dict[str, Any]:
    if value is None or pd.isna(value):
        metric_value = None
    elif unit == "%":
        metric_value = float(value) * 100.0
    elif unit == "bps":
        metric_value = float(value) * 10000.0
    else:
        metric_value = float(value)

    row = {
        "series_name": series_name,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "metric_unit": unit,
    }
    if run_id is not None:
        row["run_id"] = str(run_id)
    return row


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


def _downside_deviation(series: Iterable[float]) -> Optional[float]:
    values = pd.Series(series, dtype=float).dropna()
    if values.empty:
        return None
    downside = np.minimum(values.to_numpy(), 0.0)
    if not len(downside):
        return None
    return float(np.sqrt(np.mean(np.square(downside)))) * float(np.sqrt(12.0))


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


def _series_or_none(series: Iterable[float]) -> Optional[float]:
    values = pd.Series(series, dtype=float).dropna()
    if values.empty:
        return None
    return float(values.mean())


def _safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0 or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)
