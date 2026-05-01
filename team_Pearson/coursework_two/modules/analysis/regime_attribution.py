from __future__ import annotations

"""Regime-aware performance attribution for CW2 strategy analysis."""
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

_SCHEMA = "systematic_equity"


def classify_period_regimes(
    db_engine: Engine,
    periods: List[Dict[str, Any]],
    stress_vix_threshold: float,
) -> Dict[date, Dict[str, Any]]:
    """Classify each holding period using average VIX over the period window."""
    if not periods:
        return {}

    start_date = min(period["execution_date"] for period in periods)
    end_date = max(period["period_end_date"] for period in periods)
    sql = text(f"""
        SELECT observation_date, factor_value
        FROM {_SCHEMA}.factor_observations
        WHERE symbol = '_MACRO'
          AND factor_name = 'vix_close'
          AND observation_date BETWEEN :start_date AND :end_date
        ORDER BY observation_date
        """)
    with db_engine.connect() as conn:
        df = pd.DataFrame(
            conn.execute(sql, {"start_date": start_date, "end_date": end_date}).mappings().all()
        )
    if df.empty:
        return {
            period["period_end_date"]: {"regime": "normal", "vix_mean": None} for period in periods
        }
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce").dt.date
    df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")

    out: Dict[date, Dict[str, Any]] = {}
    threshold = float(stress_vix_threshold)
    for period in periods:
        window = df[
            (df["observation_date"] >= period["execution_date"])
            & (df["observation_date"] <= period["period_end_date"])
        ]
        vix_mean = float(window["factor_value"].mean()) if not window.empty else None
        regime = "stress" if vix_mean is not None and vix_mean >= threshold else "normal"
        out[period["period_end_date"]] = {"regime": regime, "vix_mean": vix_mean}
    return out


def compute_regime_attribution(
    run_context: Dict[str, Any],
    db_engine: Engine,
    *,
    period_regimes: Dict[date, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compute strategy vs benchmark/baseline attribution across regimes."""
    run_id = str(run_context["run_id"])
    strategy = _load_strategy_series(run_id, db_engine)
    analysis_cfg = dict(run_context.get("analysis_config") or {})
    run_row = dict(run_context.get("run_row") or {})
    primary_benchmark = str(
        analysis_cfg.get("primary_benchmark") or run_row.get("benchmark_ticker") or "SPY"
    )
    benchmark_ticker = str(run_row.get("benchmark_ticker") or primary_benchmark)
    allowed_series = list(
        dict.fromkeys(
            [
                primary_benchmark,
                benchmark_ticker,
                "universe_ew",
                "static_baseline",
            ]
        )
    )
    benchmarks = _load_benchmark_series(run_id, db_engine, allowed_series=allowed_series)
    if strategy.empty or not benchmarks:
        return []

    regime_map = {
        pd.Timestamp(period_end): regime_info.get("regime", "normal")
        for period_end, regime_info in period_regimes.items()
    }
    strategy["regime_bucket"] = strategy.index.map(lambda idx: regime_map.get(idx, "normal"))

    out: List[Dict[str, Any]] = []
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
        for regime_name in ("normal", "stress", "all"):
            subset = (
                joined if regime_name == "all" else joined[joined["regime_bucket"] == regime_name]
            )
            if subset.empty:
                continue
            strategy_ann_return = _annualize_total_return(
                float((1.0 + subset["strategy_return"]).prod() - 1.0), len(subset)
            )
            versus_ann_return = _annualize_total_return(
                float((1.0 + subset["versus_return"]).prod() - 1.0), len(subset)
            )
            strategy_ann_vol = _annualized_std(subset["strategy_return"])
            versus_ann_vol = _annualized_std(subset["versus_return"])
            risk_free = pd.to_numeric(
                subset.get(
                    "risk_free_return",
                    subset.get(
                        "versus_risk_free_return",
                        pd.Series(0.0, index=subset.index, dtype=float),
                    ),
                ),
                errors="coerce",
            ).fillna(0.0)
            strategy_excess = pd.to_numeric(subset["strategy_return"], errors="coerce").reset_index(
                drop=True
            ) - risk_free.reset_index(drop=True)
            versus_excess = pd.to_numeric(subset["versus_return"], errors="coerce").reset_index(
                drop=True
            ) - risk_free.reset_index(drop=True)
            strategy_sharpe = _safe_divide(
                _annualized_mean(strategy_excess),
                _annualized_std(strategy_excess),
            )
            versus_sharpe = _safe_divide(
                _annualized_mean(versus_excess),
                _annualized_std(versus_excess),
            )
            strategy_nav = _nav_from_returns(subset["strategy_return"])
            versus_nav = _nav_from_returns(subset["versus_return"])
            out.append(
                {
                    "run_id": run_id,
                    "regime": regime_name,
                    "versus_series": series_name,
                    "n_periods": int(len(subset)),
                    "strategy_ann_return": _percent(strategy_ann_return),
                    "versus_ann_return": _percent(versus_ann_return),
                    "excess_ann_return": _percent(
                        None
                        if strategy_ann_return is None or versus_ann_return is None
                        else strategy_ann_return - versus_ann_return
                    ),
                    "strategy_ann_vol": _percent(strategy_ann_vol),
                    "versus_ann_vol": _percent(versus_ann_vol),
                    "strategy_sharpe": strategy_sharpe,
                    "versus_sharpe": versus_sharpe,
                    "strategy_max_dd": _percent(_max_drawdown(strategy_nav)),
                    "versus_max_dd": _percent(_max_drawdown(versus_nav)),
                    "hit_rate": _percent(
                        float((subset["strategy_return"] > subset["versus_return"]).mean())
                    ),
                }
            )
    return out


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


def _load_benchmark_series(
    run_id: str, db_engine: Engine, *, allowed_series: List[str]
) -> Dict[str, pd.DataFrame]:
    sql = text(f"""
        SELECT period_end_date, series_name, nav, period_return, risk_free_return
        FROM {_SCHEMA}.backtest_benchmark_nav
        WHERE run_id = :run_id
          AND series_name = ANY(:series_names)
        ORDER BY period_end_date
        """)
    with db_engine.connect() as conn:
        df = pd.DataFrame(
            conn.execute(sql, {"run_id": run_id, "series_names": allowed_series}).mappings().all()
        )
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


def _nav_from_returns(series: Iterable[float]) -> pd.Series:
    returns = pd.Series(series, dtype=float).fillna(0.0)
    return (1.0 + returns).cumprod()


def _max_drawdown(nav_series: Iterable[float], *, initial_nav: float = 1.0) -> Optional[float]:
    nav = pd.Series(nav_series, dtype=float).dropna()
    if nav.empty:
        return None
    nav_with_start = pd.concat(
        [pd.Series([float(initial_nav)]), nav.reset_index(drop=True)], ignore_index=True
    )
    peak = nav_with_start.cummax()
    dd = nav_with_start / peak - 1.0
    return abs(float(dd.min()))


def _percent(value: Optional[float]) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return float(value) * 100.0
