from __future__ import annotations

"""Automated scorecard for judging the CW2 strategy against relative goals."""

from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

_SCHEMA = "systematic_equity"


def compute_scorecard(
    conn: Engine,
    run_id: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    robustness_run_id_25bps: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Evaluate the five scorecard criteria for the analysed strategy."""
    cfg = (config or {}).get("backtest", {}).get("analysis", {})
    primary_benchmark = str(cfg.get("primary_benchmark", "SPY"))
    strategy_metrics = _load_metric_lookup(conn, run_id)
    relative_metrics = _load_relative_metric_lookup(conn, run_id)
    regime_rows = _load_regime_lookup(conn, run_id)

    baseline_stats = _compute_baseline_stats(conn, run_id, primary_benchmark)

    rows: List[Dict[str, Any]] = []
    excess_vs_uew = relative_metrics.get((primary_benchmark, "excess_return_annualized"))
    rows.append(
        _row(
            run_id,
            1,
            "Positive long-run excess return vs primary benchmark",
            None if excess_vs_uew is None else excess_vs_uew > 0,
            {
                "excess_return_annualized_vs_primary_pct": excess_vs_uew,
                "threshold": 0.0,
            },
        )
    )

    stress_static = regime_rows.get(("stress", "static_baseline"))
    criterion_2 = None
    evidence_2: Dict[str, Any] = {}
    if stress_static:
        strategy_dd = stress_static.get("strategy_max_dd")
        baseline_dd = stress_static.get("versus_max_dd")
        criterion_2 = (
            None if strategy_dd is None or baseline_dd is None else strategy_dd < baseline_dd
        )
        evidence_2 = {
            "strategy_max_dd_stress_pct": strategy_dd,
            "baseline_max_dd_stress_pct": baseline_dd,
        }
    rows.append(
        _row(
            run_id,
            2,
            "Lower stress max drawdown than static baseline",
            criterion_2,
            evidence_2,
        )
    )

    strategy_sharpe = strategy_metrics.get(("risk_adjusted", "sharpe_ratio"))
    strategy_sortino = strategy_metrics.get(("risk_adjusted", "sortino_ratio"))
    strategy_ir = relative_metrics.get((primary_benchmark, "information_ratio"))
    baseline_beats = 0
    if (
        strategy_sharpe is not None
        and baseline_stats["sharpe"] is not None
        and strategy_sharpe > baseline_stats["sharpe"]
    ):
        baseline_beats += 1
    if (
        strategy_sortino is not None
        and baseline_stats["sortino"] is not None
        and strategy_sortino > baseline_stats["sortino"]
    ):
        baseline_beats += 1
    if (
        strategy_ir is not None
        and baseline_stats["information_ratio_vs_primary"] is not None
        and strategy_ir > baseline_stats["information_ratio_vs_primary"]
    ):
        baseline_beats += 1
    rows.append(
        _row(
            run_id,
            3,
            "At least two of Sharpe, Sortino, IR beat static baseline",
            baseline_beats >= 2,
            {
                "strategy_sharpe": strategy_sharpe,
                "baseline_sharpe": baseline_stats["sharpe"],
                "strategy_sortino": strategy_sortino,
                "baseline_sortino": baseline_stats["sortino"],
                "strategy_ir_vs_primary": strategy_ir,
                "baseline_ir_vs_primary": baseline_stats["information_ratio_vs_primary"],
                "metrics_beating": baseline_beats,
                "threshold": 2,
            },
        )
    )

    if robustness_run_id_25bps:
        robustness_metrics = _load_relative_metric_lookup(conn, robustness_run_id_25bps)
        excess_25 = robustness_metrics.get((primary_benchmark, "excess_return_annualized"))
        criterion_4 = None if excess_25 is None else excess_25 > 0
        evidence_4 = {
            "robustness_run_id_25bps": robustness_run_id_25bps,
            "excess_return_annualized_vs_primary_pct": excess_25,
            "threshold": 0.0,
        }
    else:
        criterion_4 = None
        evidence_4 = {"robustness_run_id_25bps": None, "skipped": True}
    rows.append(
        _row(
            run_id,
            4,
            "Excess return survives 25 bps cost robustness",
            criterion_4,
            evidence_4,
        )
    )

    criterion_5 = None
    evidence_5: Dict[str, Any] = {}
    if stress_static:
        excess_ann = stress_static.get("excess_ann_return")
        criterion_5 = None if excess_ann is None else excess_ann > 0
        evidence_5 = {
            "stress_excess_ann_return_vs_static_pct": excess_ann,
            "threshold": 0.0,
        }
    rows.append(
        _row(
            run_id,
            5,
            "Positive stress-period excess return vs static baseline",
            criterion_5,
            evidence_5,
        )
    )
    return rows


def _compute_baseline_stats(
    conn: Engine, run_id: str, primary_benchmark: str
) -> Dict[str, Optional[float]]:
    strategy = _load_benchmark_returns(conn, run_id, "static_baseline")
    primary = _load_benchmark_returns(conn, run_id, primary_benchmark)
    if strategy.empty:
        return {"sharpe": None, "sortino": None, "information_ratio_vs_primary": None}

    strategy_rf = (
        pd.to_numeric(strategy.get("risk_free_return"), errors="coerce")
        if "risk_free_return" in strategy.columns
        else pd.Series(0.0, index=strategy.index, dtype=float)
    ).fillna(0.0)
    strategy_excess = (
        pd.to_numeric(strategy["period_return"], errors="coerce").fillna(0.0) - strategy_rf
    )
    sharpe = _safe_divide(
        _annualized_mean(strategy_excess),
        _annualized_std(strategy_excess),
    )
    sortino = _safe_divide(
        _annualized_mean(strategy_excess),
        _downside_deviation(strategy_excess),
    )
    joined = pd.concat(
        [
            strategy[["period_return"]].rename(columns={"period_return": "baseline"}),
            primary[["period_return"]].rename(columns={"period_return": "primary"}),
        ],
        axis=1,
    ).dropna()
    if joined.empty:
        ir = None
    else:
        excess = joined["baseline"] - joined["primary"]
        excess_ann_arithmetic = _annualized_mean(excess)
        ir = _safe_divide(
            excess_ann_arithmetic,
            _annualized_std(excess),
        )
    return {"sharpe": sharpe, "sortino": sortino, "information_ratio_vs_primary": ir}


def _load_metric_lookup(conn: Engine, run_id: str) -> Dict[tuple[str, str], float]:
    sql = text(f"""
        SELECT metric_group, metric_name, metric_value
        FROM {_SCHEMA}.backtest_metrics
        WHERE run_id = :run_id
        """)
    with conn.connect() as db:
        rows = db.execute(sql, {"run_id": run_id}).mappings().all()
    return {
        (str(row["metric_group"]), str(row["metric_name"])): _safe_float(row["metric_value"])
        for row in rows
    }


def _load_relative_metric_lookup(conn: Engine, run_id: str) -> Dict[tuple[str, str], float]:
    sql = text(f"""
        SELECT versus_series, metric_name, metric_value
        FROM {_SCHEMA}.backtest_relative_metrics
        WHERE run_id = :run_id
        """)
    with conn.connect() as db:
        rows = db.execute(sql, {"run_id": run_id}).mappings().all()
    return {
        (str(row["versus_series"]), str(row["metric_name"])): _safe_float(row["metric_value"])
        for row in rows
    }


def _load_regime_lookup(conn: Engine, run_id: str) -> Dict[tuple[str, str], Dict[str, float]]:
    sql = text(f"""
        SELECT regime, versus_series, strategy_max_dd, versus_max_dd, excess_ann_return
        FROM {_SCHEMA}.backtest_regime_attribution
        WHERE run_id = :run_id
        """)
    with conn.connect() as db:
        rows = db.execute(sql, {"run_id": run_id}).mappings().all()
    out: Dict[tuple[str, str], Dict[str, float]] = {}
    for row in rows:
        out[(str(row["regime"]), str(row["versus_series"]))] = {
            "strategy_max_dd": _safe_float(row["strategy_max_dd"]),
            "versus_max_dd": _safe_float(row["versus_max_dd"]),
            "excess_ann_return": _safe_float(row["excess_ann_return"]),
        }
    return out


def _load_benchmark_returns(conn: Engine, run_id: str, series_name: str) -> pd.DataFrame:
    sql = text(f"""
        SELECT period_end_date, period_return, risk_free_return
        FROM {_SCHEMA}.backtest_benchmark_nav
        WHERE run_id = :run_id
          AND series_name = :series_name
        ORDER BY period_end_date
        """)
    with conn.connect() as db:
        df = pd.DataFrame(
            db.execute(sql, {"run_id": run_id, "series_name": series_name}).mappings().all()
        )
    if df.empty:
        return pd.DataFrame(columns=["period_return", "risk_free_return"])
    df["period_end_date"] = pd.to_datetime(df["period_end_date"], errors="coerce")
    df["period_return"] = pd.to_numeric(df["period_return"], errors="coerce")
    df["risk_free_return"] = pd.to_numeric(df["risk_free_return"], errors="coerce")
    return df.set_index("period_end_date")[["period_return", "risk_free_return"]]


def _row(
    run_id: str,
    criterion_id: int,
    criterion_name: str,
    passed: Optional[bool],
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "criterion_id": int(criterion_id),
        "criterion_name": criterion_name,
        "passed": passed,
        "evidence": evidence,
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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
    return float(np.sqrt(np.mean(np.square(downside)))) * float(np.sqrt(12.0))


def _safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0 or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)
