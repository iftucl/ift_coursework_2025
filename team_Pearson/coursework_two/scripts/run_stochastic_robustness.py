from __future__ import annotations

"""Run stochastic robustness diagnostics around a completed CW2 backtest."""

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"

for path in (str(REPO_ROOT), str(CW1_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.modules.backtest.data_loader import (  # noqa: E402
    load_adjusted_close_prices,
)
from team_Pearson.coursework_two.scripts.orchestration import load_env_layers  # noqa: E402

_SCHEMA = "systematic_equity"
_DEFAULT_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"
_DEFAULT_OUTPUT_ROOT = CW2_ROOT / "outputs" / "robustness" / "stochastic"


@dataclass(frozen=True)
class MonteCarloSpec:
    scenario_key: str
    description: str
    sigma_multiplier: float = 1.0
    classification: str = "core"


@dataclass(frozen=True)
class WeightPerturbationSpec:
    scenario_key: str
    description: str
    concentration: float
    classification: str = "auxiliary"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bootstrap / Monte Carlo / local weight perturbation robustness diagnostics for a completed CW2 run."
    )
    parser.add_argument("--run-id", default=_DEFAULT_RUN_ID)
    parser.add_argument("--output-root", default=str(_DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--bootstrap-paths", type=int, default=2000)
    parser.add_argument("--bootstrap-block-size", type=int, default=6)
    parser.add_argument(
        "--bootstrap-method",
        default="stationary_block",
        choices=["stationary_block", "moving_block"],
    )
    parser.add_argument("--monte-carlo-paths", type=int, default=2000)
    parser.add_argument("--dirichlet-paths", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260419)
    return parser


def _fetch_performance(run_id: str) -> pd.DataFrame:
    sql = text(f"""
        SELECT
            period_end_date,
            net_return,
            benchmark_return,
            excess_return,
            turnover,
            regime,
            vix_level,
            num_holdings,
            drawdown_brake_active
        FROM {_SCHEMA}.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    engine = get_db_engine()
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"run_id": run_id})
    if df.empty:
        raise ValueError(f"no backtest_performance rows found for run_id={run_id}")
    df["period_end_date"] = pd.to_datetime(df["period_end_date"]).dt.date
    numeric_cols = [
        "net_return",
        "benchmark_return",
        "excess_return",
        "turnover",
        "vix_level",
        "num_holdings",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    active = df[df["num_holdings"].fillna(0) > 0].copy()
    if active.empty:
        raise ValueError(f"run_id={run_id} has no active holding periods")
    return active.reset_index(drop=True)


def _fetch_holdings(run_id: str) -> pd.DataFrame:
    sql = text(f"""
        SELECT
            execution_date,
            symbol,
            target_weight,
            executed_weight,
            drifted_weight,
            regime
        FROM {_SCHEMA}.backtest_holdings
        WHERE run_id = :run_id
        ORDER BY execution_date, COALESCE(executed_weight, target_weight) DESC NULLS LAST, symbol
        """)
    engine = get_db_engine()
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"run_id": run_id})
    if df.empty:
        raise ValueError(f"no backtest_holdings rows found for run_id={run_id}")
    df["execution_date"] = pd.to_datetime(df["execution_date"]).dt.date
    for col in ("target_weight", "executed_weight", "drifted_weight"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["weight"] = df["executed_weight"].fillna(df["target_weight"]).fillna(0.0)
    df = df[df["weight"] > 0].copy()
    if df.empty:
        raise ValueError(f"run_id={run_id} holdings contain no positive weights")
    return df.reset_index(drop=True)


def _portfolio_name_for_run(run_id: str) -> str:
    sql = text(f"""
        SELECT COALESCE(run_name, run_id::text) AS run_name
        FROM {_SCHEMA}.backtest_runs
        WHERE run_id = :run_id
        """)
    engine = get_db_engine()
    with engine.connect() as conn:
        value = conn.execute(sql, {"run_id": run_id}).scalar()
    return str(value or run_id)


def _compound(returns: np.ndarray) -> float:
    clean = np.asarray(returns, dtype=float)
    if clean.size == 0:
        return 0.0
    return float(np.prod(1.0 + clean) - 1.0)


def _annualized_return(returns: np.ndarray, periods_per_year: int = 12) -> float:
    clean = np.asarray(returns, dtype=float)
    if clean.size == 0:
        return 0.0
    total = np.prod(1.0 + clean)
    if total <= 0.0:
        return -1.0
    return float(total ** (periods_per_year / clean.size) - 1.0)


def _annualized_volatility(returns: np.ndarray, periods_per_year: int = 12) -> float:
    clean = np.asarray(returns, dtype=float)
    if clean.size <= 1:
        return 0.0
    return float(np.std(clean, ddof=1) * math.sqrt(periods_per_year))


def _max_drawdown(returns: np.ndarray) -> float:
    clean = np.asarray(returns, dtype=float)
    if clean.size == 0:
        return 0.0
    nav = np.cumprod(1.0 + clean)
    peaks = np.maximum.accumulate(nav)
    drawdowns = nav / peaks - 1.0
    return float(drawdowns.min())


def _path_metrics(
    returns: np.ndarray,
    benchmark_returns: Optional[np.ndarray] = None,
) -> Dict[str, float]:
    ann_return = _annualized_return(returns)
    ann_vol = _annualized_volatility(returns)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0
    out = {
        "annualized_return": ann_return,
        "annualized_volatility": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": _max_drawdown(returns),
        "cumulative_return": _compound(returns),
    }
    if benchmark_returns is not None:
        bench = np.asarray(benchmark_returns, dtype=float)
        if bench.shape == np.asarray(returns).shape:
            out["annualized_excess_return"] = ann_return - _annualized_return(bench)
    return out


def _summarize_paths(
    method: str,
    scenario_key: str,
    description: str,
    path_metrics: pd.DataFrame,
    *,
    classification: str = "core",
) -> Dict[str, Any]:
    if path_metrics.empty:
        raise ValueError(f"{method}:{scenario_key} produced no path metrics")

    def _q(column: str, q: float) -> float:
        return float(path_metrics[column].quantile(q))

    summary = {
        "method": method,
        "scenario_key": scenario_key,
        "description": description,
        "classification": classification,
        "requirement_section": "Part 4 - Stochastic Robustness",
        "path_count": int(len(path_metrics)),
        "annualized_return_p05": _q("annualized_return", 0.05),
        "annualized_return_p50": _q("annualized_return", 0.50),
        "annualized_return_p95": _q("annualized_return", 0.95),
        "annualized_volatility_p50": _q("annualized_volatility", 0.50),
        "sharpe_p05": _q("sharpe", 0.05),
        "sharpe_p50": _q("sharpe", 0.50),
        "sharpe_p95": _q("sharpe", 0.95),
        "max_drawdown_p05": _q("max_drawdown", 0.05),
        "max_drawdown_p50": _q("max_drawdown", 0.50),
        "max_drawdown_p95": _q("max_drawdown", 0.95),
        "positive_return_probability": float((path_metrics["annualized_return"] > 0).mean()),
        "positive_sharpe_probability": float((path_metrics["sharpe"] > 0).mean()),
    }
    if "annualized_excess_return" in path_metrics.columns:
        summary["annualized_excess_return_p50"] = float(
            path_metrics["annualized_excess_return"].quantile(0.50)
        )
    return summary


def _moving_block_bootstrap(
    returns_df: pd.DataFrame,
    *,
    path_count: int,
    block_size: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    values = returns_df[["net_return", "benchmark_return"]].to_numpy(dtype=float)
    n_periods = values.shape[0]
    if n_periods == 0:
        raise ValueError("bootstrap input is empty")
    block_size = max(1, min(int(block_size), n_periods))

    rows: List[Dict[str, float]] = []
    max_start = n_periods - block_size
    for path_idx in range(path_count):
        collected: List[np.ndarray] = []
        while sum(chunk.shape[0] for chunk in collected) < n_periods:
            start = 0 if max_start <= 0 else int(rng.integers(0, max_start + 1))
            collected.append(values[start : start + block_size])
        path = np.vstack(collected)[:n_periods]
        metrics = _path_metrics(path[:, 0], path[:, 1])
        metrics["path_index"] = float(path_idx)
        rows.append(metrics)
    return pd.DataFrame(rows)


def _stationary_block_bootstrap(
    returns_df: pd.DataFrame,
    *,
    path_count: int,
    expected_block_size: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    values = returns_df[["net_return", "benchmark_return"]].to_numpy(dtype=float)
    n_periods = values.shape[0]
    if n_periods == 0:
        raise ValueError("stationary bootstrap input is empty")
    expected_block_size = max(1, int(expected_block_size))
    stop_probability = 1.0 / float(expected_block_size)

    rows: List[Dict[str, float]] = []
    for path_idx in range(path_count):
        indices: List[int] = []
        current = int(rng.integers(0, n_periods))
        while len(indices) < n_periods:
            indices.append(current)
            if rng.random() < stop_probability:
                current = int(rng.integers(0, n_periods))
            else:
                current = (current + 1) % n_periods
        path = values[np.asarray(indices[:n_periods], dtype=int)]
        metrics = _path_metrics(path[:, 0], path[:, 1])
        metrics["path_index"] = float(path_idx)
        rows.append(metrics)
    return pd.DataFrame(rows)


def _fit_garch11(period_returns: np.ndarray) -> Tuple[float, float, float, float]:
    series = np.asarray(period_returns, dtype=float)
    mu = float(series.mean())
    residuals = series - mu
    variance = float(np.var(residuals, ddof=1)) if residuals.size > 1 else 1e-6
    variance = max(variance, 1e-6)

    alpha_grid = (0.03, 0.05, 0.08, 0.10, 0.12)
    beta_grid = (0.75, 0.80, 0.85, 0.88, 0.90, 0.93)

    best = None
    best_ll = float("-inf")
    for alpha in alpha_grid:
        for beta in beta_grid:
            if alpha + beta >= 0.985:
                continue
            omega = variance * (1.0 - alpha - beta)
            sigma2 = np.full_like(residuals, variance)
            ll = 0.0
            for idx, eps in enumerate(residuals):
                if idx > 0:
                    sigma2[idx] = omega + alpha * residuals[idx - 1] ** 2 + beta * sigma2[idx - 1]
                sigma2[idx] = max(float(sigma2[idx]), 1e-8)
                ll += -0.5 * (
                    math.log(2.0 * math.pi) + math.log(sigma2[idx]) + (eps**2) / sigma2[idx]
                )
            if ll > best_ll:
                best_ll = ll
                best = (mu, omega, alpha, beta)
    if best is None:
        return mu, variance * 0.05, 0.05, 0.90
    return best


def _simulate_garch_paths(
    period_returns: np.ndarray,
    *,
    path_count: int,
    rng: np.random.Generator,
    sigma_multiplier: float,
) -> pd.DataFrame:
    mu, omega, alpha, beta = _fit_garch11(period_returns)
    residuals = period_returns - mu
    base_variance = float(np.var(residuals, ddof=1)) if residuals.size > 1 else 1e-6
    base_variance = max(base_variance, 1e-6)
    horizon = len(period_returns)
    rows: List[Dict[str, float]] = []

    for path_idx in range(path_count):
        sigma2_prev = base_variance
        eps_prev = float(residuals[-1]) if residuals.size else 0.0
        path = np.zeros(horizon, dtype=float)
        for t in range(horizon):
            sigma2_t = omega + alpha * (eps_prev**2) + beta * sigma2_prev
            sigma2_t = max(float(sigma2_t), 1e-8)
            shock = float(rng.normal())
            eps_t = math.sqrt(sigma2_t) * float(sigma_multiplier) * shock
            path[t] = max(mu + eps_t, -0.95)
            sigma2_prev = sigma2_t
            eps_prev = eps_t
        metrics = _path_metrics(path)
        metrics["path_index"] = float(path_idx)
        rows.append(metrics)
    return pd.DataFrame(rows)


def _first_valid_price_on_or_after(
    panel: pd.DataFrame,
    symbol: str,
    boundary: date,
) -> Optional[float]:
    if symbol not in panel.columns:
        return None
    subset = panel.loc[panel.index >= boundary, symbol].dropna()
    if subset.empty:
        return None
    return float(subset.iloc[0])


def _build_dirichlet_return_matrix(
    run_id: str,
    performance_df: pd.DataFrame,
    holdings_df: pd.DataFrame,
) -> Tuple[List[date], List[np.ndarray], List[np.ndarray]]:
    perf_dates = sorted(pd.to_datetime(performance_df["period_end_date"]).dt.date.tolist())
    active_dates = perf_dates

    holdings_groups: Dict[date, pd.DataFrame] = {
        exec_date: group.copy()
        for exec_date, group in holdings_df.groupby("execution_date", sort=True)
    }
    usable_dates = [dt for dt in active_dates if dt in holdings_groups]
    if len(usable_dates) < 2:
        raise ValueError(
            f"run_id={run_id} does not have enough aligned holdings dates for local weight perturbation robustness"
        )

    symbols = sorted(holdings_df["symbol"].dropna().astype(str).unique().tolist())
    engine = get_db_engine()
    price_panel = load_adjusted_close_prices(
        engine,
        symbols,
        usable_dates[0],
        usable_dates[-1],
        lookback_days=10,
    )
    if price_panel.empty:
        raise ValueError(
            "adjusted close price panel is empty for local weight perturbation robustness"
        )
    price_panel.index = pd.to_datetime(price_panel.index).date

    period_dates: List[date] = []
    weight_vectors: List[np.ndarray] = []
    asset_return_vectors: List[np.ndarray] = []

    for start_date, end_date in zip(usable_dates[:-1], usable_dates[1:]):
        group = holdings_groups[start_date]
        symbols_for_period = group["symbol"].astype(str).tolist()
        weights = group["weight"].astype(float).to_numpy()
        weights_sum = float(weights.sum())
        if weights_sum <= 0:
            continue
        weights = weights / weights_sum

        asset_returns: List[float] = []
        final_weights: List[float] = []
        for symbol, weight in zip(symbols_for_period, weights):
            start_price = _first_valid_price_on_or_after(price_panel, symbol, start_date)
            end_price = _first_valid_price_on_or_after(price_panel, symbol, end_date)
            if start_price is None or end_price is None or start_price <= 0:
                continue
            asset_returns.append((end_price / start_price) - 1.0)
            final_weights.append(weight)

        if not asset_returns:
            continue

        period_dates.append(start_date)
        normalized = np.asarray(final_weights, dtype=float)
        normalized = normalized / normalized.sum()
        weight_vectors.append(normalized)
        asset_return_vectors.append(np.asarray(asset_returns, dtype=float))

    if not period_dates:
        raise ValueError("failed to construct any Dirichlet weight-return periods")
    return period_dates, weight_vectors, asset_return_vectors


def _simulate_dirichlet_paths(
    weight_vectors: Sequence[np.ndarray],
    asset_return_vectors: Sequence[np.ndarray],
    *,
    path_count: int,
    concentration: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    rows: List[Dict[str, float]] = []
    eps = 1e-6
    for path_idx in range(path_count):
        period_returns: List[float] = []
        for base_weights, asset_returns in zip(weight_vectors, asset_return_vectors):
            alpha = np.maximum(base_weights * concentration, eps)
            sampled = rng.dirichlet(alpha)
            period_returns.append(float(np.dot(sampled, asset_returns)))
        metrics = _path_metrics(np.asarray(period_returns, dtype=float))
        metrics["path_index"] = float(path_idx)
        rows.append(metrics)
    return pd.DataFrame(rows)


def _summaries_to_markdown(summaries: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Stochastic Robustness Summary",
        "",
        "| Method | Scenario | Class | P50 Ann Return | P50 Sharpe | P50 Max DD | Positive Return Prob |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        lines.append(
            "| {method} | {scenario_key} | {classification} | {annualized_return_p50:.2%} | {sharpe_p50:.3f} | {max_drawdown_p50:.2%} | {positive_return_probability:.1%} |".format(
                **item
            )
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- `bootstrap` (requirement-style Test 9 output) and `monte_carlo:garch_base` / `garch_stress_1_5xvol` are the main stochastic robustness references.",
            "- `monte_carlo:garch_stress_2xvol` should be interpreted as an extreme stress test, not the central robustness case.",
            "- `local_weight_perturbation` tests only nearby portfolio-weight perturbations around realized holdings, so it is intentionally narrower than a full strategy rerun.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_outputs(
    output_root: Path,
    summaries: List[Dict[str, Any]],
    path_metrics_map: Mapping[str, pd.DataFrame],
    metadata: Mapping[str, Any],
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    summary_dir = output_root / "summaries"
    path_dir = output_root / "path_metrics"
    summary_dir.mkdir(parents=True, exist_ok=True)
    path_dir.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame(summaries).sort_values(["method", "scenario_key"])
    summary_df.to_csv(summary_dir / "stochastic_robustness_summary.csv", index=False)
    (summary_dir / "stochastic_robustness_summary.json").write_text(
        json.dumps(
            {
                "metadata": dict(metadata),
                "summaries": summary_df.to_dict(orient="records"),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (summary_dir / "stochastic_robustness_summary.md").write_text(
        _summaries_to_markdown(summary_df.to_dict(orient="records")),
        encoding="utf-8",
    )

    for key, df in path_metrics_map.items():
        df.to_csv(path_dir / f"{key}.csv", index=False)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    load_env_layers()
    output_root = Path(str(args.output_root)).resolve()
    run_id = str(args.run_id)
    rng = np.random.default_rng(int(args.seed))

    performance_df = _fetch_performance(run_id)
    holdings_df = _fetch_holdings(run_id)
    run_name = _portfolio_name_for_run(run_id)

    summaries: List[Dict[str, Any]] = []
    path_metrics_map: Dict[str, pd.DataFrame] = {}

    bootstrap_df = (
        _moving_block_bootstrap(
            performance_df,
            path_count=int(args.bootstrap_paths),
            block_size=int(args.bootstrap_block_size),
            rng=rng,
        )
        if str(args.bootstrap_method) == "moving_block"
        else _stationary_block_bootstrap(
            performance_df,
            path_count=int(args.bootstrap_paths),
            expected_block_size=int(args.bootstrap_block_size),
            rng=rng,
        )
    )
    path_metrics_map["bootstrap_block"] = bootstrap_df
    summaries.append(
        _summarize_paths(
            method="bootstrap",
            scenario_key=(
                f"moving_block_{int(args.bootstrap_block_size)}m"
                if str(args.bootstrap_method) == "moving_block"
                else f"stationary_block_e{int(args.bootstrap_block_size)}m"
            ),
            description=(
                f"Moving-block bootstrap on monthly return records from the quarterly-rebalanced strategy and benchmark (block={int(args.bootstrap_block_size)} periods)."
                if str(args.bootstrap_method) == "moving_block"
                else f"Stationary block bootstrap on monthly return records from the quarterly-rebalanced strategy and benchmark with expected block length {int(args.bootstrap_block_size)} periods."
            ),
            path_metrics=bootstrap_df,
            classification="core",
        )
    )

    monte_carlo_specs = [
        MonteCarloSpec(
            scenario_key="garch_base",
            description="Univariate GARCH(1,1) Monte Carlo calibrated on monthly net returns from the quarterly-rebalanced strategy.",
            sigma_multiplier=1.0,
            classification="core",
        ),
        MonteCarloSpec(
            scenario_key="garch_stress_1_5xvol",
            description="Moderate stress Monte Carlo with 1.5x conditional volatility on top of the calibrated GARCH path.",
            sigma_multiplier=1.5,
            classification="core",
        ),
        MonteCarloSpec(
            scenario_key="garch_stress_2xvol",
            description="Severe stress Monte Carlo with 2x conditional volatility on top of the calibrated GARCH path.",
            sigma_multiplier=2.0,
            classification="stress_only",
        ),
    ]
    period_returns = performance_df["net_return"].to_numpy(dtype=float)
    for spec in monte_carlo_specs:
        mc_df = _simulate_garch_paths(
            period_returns,
            path_count=int(args.monte_carlo_paths),
            rng=rng,
            sigma_multiplier=float(spec.sigma_multiplier),
        )
        key = f"monte_carlo_{spec.scenario_key}"
        path_metrics_map[key] = mc_df
        summaries.append(
            _summarize_paths(
                method="monte_carlo",
                scenario_key=spec.scenario_key,
                description=spec.description,
                path_metrics=mc_df,
                classification=spec.classification,
            )
        )

    _, weight_vectors, asset_return_vectors = _build_dirichlet_return_matrix(
        run_id,
        performance_df,
        holdings_df,
    )
    perturbation_specs = [
        WeightPerturbationSpec(
            scenario_key="tight_alpha_500",
            description="Tight local weight perturbation around realised quarterly-rebalanced portfolio weights.",
            concentration=500.0,
            classification="auxiliary",
        ),
        WeightPerturbationSpec(
            scenario_key="medium_alpha_250",
            description="Medium local weight perturbation around realised quarterly-rebalanced portfolio weights.",
            concentration=250.0,
            classification="auxiliary",
        ),
        WeightPerturbationSpec(
            scenario_key="loose_alpha_100",
            description="Loose local weight perturbation around realised quarterly-rebalanced portfolio weights.",
            concentration=100.0,
            classification="auxiliary",
        ),
    ]
    for spec in perturbation_specs:
        dir_df = _simulate_dirichlet_paths(
            weight_vectors,
            asset_return_vectors,
            path_count=int(args.dirichlet_paths),
            concentration=float(spec.concentration),
            rng=rng,
        )
        key = f"local_weight_perturbation_{spec.scenario_key}"
        path_metrics_map[key] = dir_df
        summaries.append(
            _summarize_paths(
                method="local_weight_perturbation",
                scenario_key=spec.scenario_key,
                description=spec.description,
                path_metrics=dir_df,
                classification=spec.classification,
            )
        )

    metadata = {
        "run_id": run_id,
        "run_name": run_name,
        "period_count": int(len(performance_df)),
        "bootstrap_paths": int(args.bootstrap_paths),
        "bootstrap_block_size": int(args.bootstrap_block_size),
        "monte_carlo_paths": int(args.monte_carlo_paths),
        "dirichlet_paths": int(args.dirichlet_paths),
        "seed": int(args.seed),
    }
    _write_outputs(output_root, summaries, path_metrics_map, metadata)

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "output_root": str(output_root),
                "summary_count": len(summaries),
                "methods": sorted({item["method"] for item in summaries}),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
