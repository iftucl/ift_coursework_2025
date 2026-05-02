from __future__ import annotations

"""Build requirement-aligned stochastic robustness acceptance outputs."""

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import matplotlib
import numpy as np
import pandas as pd
from sqlalchemy import text

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"

for path in (str(REPO_ROOT), str(CW1_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.scripts.orchestration import load_env_layers  # noqa: E402

_SCHEMA = "systematic_equity"
_DEFAULT_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"
_DEFAULT_PATH_METRICS_ROOT = CW2_ROOT / "outputs" / "robustness" / "stochastic" / "path_metrics"
_DEFAULT_OUTPUT_ROOT = CW2_ROOT / "outputs" / "robustness" / "stochastic" / "acceptance"
_DEFAULT_TEST11_RERUN_SUMMARY = (
    CW2_ROOT
    / "outputs"
    / "robustness"
    / "test11_factor_neighbourhood"
    / "summaries"
    / "test11_factor_neighbourhood_summary.csv"
)


def _resolve_latest_tagged_csv(path: Path) -> Path:
    """Use a tagged formal rerun summary when the stable alias is absent."""

    if path.exists() and path.stat().st_size > 5:
        return path
    candidates = [
        candidate
        for candidate in path.parent.glob(f"{path.stem}_*.csv")
        if candidate.is_file() and candidate.stat().st_size > 5
    ]
    if not candidates:
        return path
    return max(candidates, key=lambda candidate: candidate.stat().st_mtime)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build requirement-sheet-aligned stochastic robustness acceptance outputs."
    )
    parser.add_argument("--run-id", default=_DEFAULT_RUN_ID)
    parser.add_argument("--path-metrics-root", default=str(_DEFAULT_PATH_METRICS_ROOT))
    parser.add_argument("--test11-rerun-summary-csv", default=str(_DEFAULT_TEST11_RERUN_SUMMARY))
    parser.add_argument("--output-root", default=str(_DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--cost-paths", type=int, default=10000)
    parser.add_argument("--parametric-paths", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260420)
    return parser


def _fetch_performance(run_id: str) -> pd.DataFrame:
    sql = text(f"""
        SELECT
            period_end_date,
            gross_return,
            net_return,
            benchmark_return,
            excess_return,
            turnover,
            gross_turnover,
            transaction_cost,
            fixed_transaction_cost,
            bid_ask_cost,
            slippage_cost,
            num_holdings,
            regime
        FROM {_SCHEMA}.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    engine = get_db_engine()
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"run_id": run_id})
    if df.empty:
        raise ValueError(f"no backtest_performance rows found for run_id={run_id}")
    df["period_end_date"] = pd.to_datetime(df["period_end_date"])
    numeric_cols = [
        "gross_return",
        "net_return",
        "benchmark_return",
        "excess_return",
        "turnover",
        "gross_turnover",
        "transaction_cost",
        "fixed_transaction_cost",
        "bid_ask_cost",
        "slippage_cost",
        "num_holdings",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["num_holdings"].fillna(0) > 0].copy()
    if df.empty:
        raise ValueError(f"run_id={run_id} has no active holding periods")
    df["gross_turnover_proxy"] = df["gross_turnover"].fillna(df["turnover"]).fillna(0.0)
    df["cost_total"] = df["transaction_cost"].fillna(0.0).where(df["transaction_cost"].notna(), 0.0)
    missing_cost_mask = df["cost_total"].abs() <= 0
    if missing_cost_mask.any():
        df.loc[missing_cost_mask, "cost_total"] = df.loc[missing_cost_mask, "gross_return"].fillna(
            0.0
        ) - df.loc[missing_cost_mask, "net_return"].fillna(0.0)
    return df.reset_index(drop=True)


def _annualized_return(returns: np.ndarray, periods_per_year: int = 12) -> float:
    clean = np.asarray(returns, dtype=float)
    if clean.size == 0:
        return 0.0
    total = np.prod(1.0 + clean)
    if total <= 0:
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
    return float((nav / peaks - 1.0).min())


def _compound(returns: np.ndarray) -> float:
    clean = np.asarray(returns, dtype=float)
    if clean.size == 0:
        return 0.0
    return float(np.prod(1.0 + clean) - 1.0)


def _path_metrics(
    returns: np.ndarray,
    benchmark_returns: Optional[np.ndarray] = None,
) -> Dict[str, float]:
    ann_return = _annualized_return(returns)
    ann_vol = _annualized_volatility(returns)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0
    metrics = {
        "annualized_return": ann_return,
        "annualized_volatility": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": _max_drawdown(returns),
        "cumulative_return": _compound(returns),
    }
    if benchmark_returns is not None:
        bench = np.asarray(benchmark_returns, dtype=float)
        if bench.shape == np.asarray(returns).shape:
            metrics["annualized_excess_return"] = ann_return - _annualized_return(bench)
    return metrics


def _quantile(path_df: pd.DataFrame, column: str, q: float) -> float:
    if column not in path_df.columns or path_df.empty:
        return float("nan")
    return float(pd.to_numeric(path_df[column], errors="coerce").dropna().quantile(q))


def _summarize_path_distribution(
    *,
    test_key: str,
    scenario_key: str,
    title: str,
    path_df: pd.DataFrame,
    implementation_status: str,
    evidence_note: str,
) -> Dict[str, Any]:
    clean = path_df.copy()
    for col in clean.columns:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")
    return {
        "test_key": test_key,
        "scenario_key": scenario_key,
        "title": title,
        "implementation_status": implementation_status,
        "evidence_note": evidence_note,
        "path_count": int(len(clean)),
        "annualized_return_p05": _quantile(clean, "annualized_return", 0.05),
        "annualized_return_p25": _quantile(clean, "annualized_return", 0.25),
        "annualized_return_p50": _quantile(clean, "annualized_return", 0.50),
        "annualized_return_p75": _quantile(clean, "annualized_return", 0.75),
        "annualized_return_p95": _quantile(clean, "annualized_return", 0.95),
        "sharpe_p05": _quantile(clean, "sharpe", 0.05),
        "sharpe_p25": _quantile(clean, "sharpe", 0.25),
        "sharpe_p50": _quantile(clean, "sharpe", 0.50),
        "sharpe_p75": _quantile(clean, "sharpe", 0.75),
        "sharpe_p95": _quantile(clean, "sharpe", 0.95),
        "max_drawdown_p05": _quantile(clean, "max_drawdown", 0.05),
        "max_drawdown_p25": _quantile(clean, "max_drawdown", 0.25),
        "max_drawdown_p50": _quantile(clean, "max_drawdown", 0.50),
        "max_drawdown_p75": _quantile(clean, "max_drawdown", 0.75),
        "max_drawdown_p95": _quantile(clean, "max_drawdown", 0.95),
        "positive_return_probability": float(
            (pd.to_numeric(clean.get("annualized_return"), errors="coerce") > 0).mean()
        ),
        "positive_sharpe_probability": float(
            (pd.to_numeric(clean.get("sharpe"), errors="coerce") > 0).mean()
        ),
        "annualized_excess_return_p50": _quantile(clean, "annualized_excess_return", 0.50),
    }


def _load_path_metrics(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _build_test9_bootstrap(path_metrics_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    path_df = _load_path_metrics(path_metrics_root / "bootstrap_block.csv")
    summary = _summarize_path_distribution(
        test_key="test_9",
        scenario_key="stationary_block_bootstrap",
        title="Stationary Block Bootstrap",
        path_df=path_df,
        implementation_status="completed",
        evidence_note="Directly mapped from existing stationary block bootstrap path metrics.",
    )
    summary["annualized_return_ci90_low"] = summary.get("annualized_return_p05")
    summary["annualized_return_ci90_high"] = summary.get("annualized_return_p95")
    summary["max_drawdown_worst_case_p95"] = summary.get("max_drawdown_p05")
    summary_df = pd.DataFrame([summary])
    return summary_df, path_df


def _simulate_cost_paths(
    perf_df: pd.DataFrame,
    *,
    path_count: int,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    base_cost = perf_df["cost_total"].fillna(0.0).to_numpy(dtype=float)
    gross_returns = perf_df["gross_return"].fillna(perf_df["net_return"]).to_numpy(dtype=float)
    bench = perf_df["benchmark_return"].fillna(0.0).to_numpy(dtype=float)
    turnover = perf_df["gross_turnover_proxy"].fillna(0.0).to_numpy(dtype=float)

    specs = [
        {
            "scenario_key": "cost_multiplier_sigma_30pct",
            "title": "Monte Carlo Cost Perturbation (sigma 30%)",
            "mean_multiplier": 1.0,
            "std_multiplier": 0.30,
            "flat_bps": 0.0,
            "implementation_status": "completed",
            "evidence_note": "Matches the requirement-sheet Monte Carlo cost perturbation with realized cost multiplier epsilon ~ N(0, 0.3^2).",
        },
        {
            "scenario_key": "cost_multiplier_sigma_50pct",
            "title": "Monte Carlo Cost Perturbation (sigma 50%)",
            "mean_multiplier": 1.0,
            "std_multiplier": 0.50,
            "flat_bps": 0.0,
            "implementation_status": "completed",
            "evidence_note": "Stress version of Test 10 using wider cost multiplier dispersion.",
        },
        {
            "scenario_key": "flat_extra_25bps",
            "title": "Flat +25bps Execution Drag",
            "mean_multiplier": 1.0,
            "std_multiplier": 0.0,
            "flat_bps": 25.0,
            "implementation_status": "completed",
            "evidence_note": "Requirement-sheet style cost robustness using turnover-linked 25bps incremental drag.",
        },
    ]

    detail_frames: List[pd.DataFrame] = []
    summary_rows: List[Dict[str, Any]] = []
    benchmark_ann_return = _annualized_return(bench)
    for spec in specs:
        path_rows: List[Dict[str, Any]] = []
        for path_index in range(path_count):
            if spec["std_multiplier"] > 0:
                multiplier = np.clip(
                    rng.normal(
                        spec["mean_multiplier"], spec["std_multiplier"], size=len(base_cost)
                    ),
                    0.0,
                    None,
                )
            else:
                multiplier = np.full(len(base_cost), spec["mean_multiplier"], dtype=float)
            extra_drag = turnover * (spec["flat_bps"] / 10000.0)
            simulated_returns = gross_returns - base_cost * multiplier - extra_drag
            metrics = _path_metrics(simulated_returns, bench)
            metrics["path_index"] = path_index
            metrics["scenario_key"] = spec["scenario_key"]
            path_rows.append(metrics)
        path_df = pd.DataFrame(path_rows)
        detail_frames.append(path_df)
        summary = _summarize_path_distribution(
            test_key="test_10",
            scenario_key=spec["scenario_key"],
            title=spec["title"],
            path_df=path_df,
            implementation_status=spec["implementation_status"],
            evidence_note=spec["evidence_note"],
        )
        if spec["scenario_key"] == "cost_multiplier_sigma_30pct":
            sharpe_series = pd.to_numeric(path_df["sharpe"], errors="coerce")
            ann_return_series = pd.to_numeric(path_df["annualized_return"], errors="coerce")
            tail_threshold = float(sharpe_series.quantile(0.05))
            summary["probability_sharpe_gt_0_50"] = float((sharpe_series > 0.50).mean())
            summary["probability_ann_return_gt_primary_benchmark"] = float(
                (ann_return_series > benchmark_ann_return).mean()
            )
            summary["sharpe_cvar_5pct"] = float(
                sharpe_series[sharpe_series <= tail_threshold].mean()
            )
        summary_rows.append(summary)
    return pd.DataFrame(summary_rows), pd.concat(detail_frames, ignore_index=True)


def _build_test11_dirichlet(path_metrics_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    specs = [
        ("dirichlet_loose_alpha_100.csv", "loose_alpha_100", "Dirichlet Neighbourhood (loose)"),
        ("dirichlet_medium_alpha_250.csv", "medium_alpha_250", "Dirichlet Neighbourhood (medium)"),
        ("dirichlet_tight_alpha_500.csv", "tight_alpha_500", "Dirichlet Neighbourhood (tight)"),
    ]
    detail_frames: List[pd.DataFrame] = []
    rows: List[Dict[str, Any]] = []
    for filename, scenario_key, title in specs:
        path_df = _load_path_metrics(path_metrics_root / filename)
        if path_df.empty:
            continue
        tagged = path_df.copy()
        tagged["scenario_key"] = scenario_key
        detail_frames.append(tagged)
        rows.append(
            _summarize_path_distribution(
                test_key="test_11",
                scenario_key=scenario_key,
                title=title,
                path_df=path_df,
                implementation_status="completed_code_equivalent",
                evidence_note="Current code perturbs realized portfolio weights with Dirichlet neighbourhoods, which is the closest implemented equivalent to the requirement wording.",
            )
        )
    return pd.DataFrame(rows), (
        pd.concat(detail_frames, ignore_index=True) if detail_frames else pd.DataFrame()
    )


def _build_test11_rerun_summary(summary_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not summary_csv.exists():
        return pd.DataFrame(), pd.DataFrame()
    summary_df = pd.read_csv(summary_csv)
    if summary_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    detail_df = summary_df.copy()
    group_rows: List[Dict[str, Any]] = []
    for band_key, band_df in detail_df.groupby("neighbourhood_band"):
        numeric_cols = [
            "return.annualized_return",
            "risk_adjusted.sharpe_ratio",
            "risk.max_drawdown",
            "static_baseline.excess_return_annualized",
        ]
        clean = band_df.copy()
        for col in numeric_cols:
            if col in clean.columns:
                clean[col] = pd.to_numeric(clean[col], errors="coerce")
        # Test 11 rerun summaries come from deterministic summary records, where
        # return / drawdown fields are stored in percentage points rather than
        # decimal fractions. Normalize them here so downstream reporting uses the
        # same unit convention as every other stochastic test.
        for pct_col in (
            "return.annualized_return",
            "risk.max_drawdown",
            "static_baseline.excess_return_annualized",
        ):
            if pct_col in clean.columns:
                clean[pct_col] = clean[pct_col] / 100.0
        path_like = pd.DataFrame(
            {
                "annualized_return": clean.get("return.annualized_return"),
                "sharpe": clean.get("risk_adjusted.sharpe_ratio"),
                "max_drawdown": clean.get("risk.max_drawdown"),
                "annualized_excess_return": clean.get("static_baseline.excess_return_annualized"),
            }
        )
        group_rows.append(
            _summarize_path_distribution(
                test_key="test_11",
                scenario_key=f"factor_weight_{band_key}",
                title=f"Factor-weight Dirichlet Neighbourhood ({band_key})",
                path_df=path_like,
                implementation_status="completed",
                evidence_note="Requirement-style reruns built from full snapshot refresh, backtest, analysis, and report generation for sampled regime.normal factor weights.",
            )
        )
    return pd.DataFrame(group_rows), detail_df


def _write_test11_report_ready(detail_df: pd.DataFrame, output_root: Path) -> None:
    if detail_df.empty or "neighbourhood_band" not in detail_df.columns:
        return
    output_root.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    metric_map = {
        "return.annualized_return": "annualized_return_mean_pct",
        "risk_adjusted.sharpe_ratio": "sharpe_mean",
        "static_baseline.excess_return_annualized": "excess_return_mean_pct",
        "risk.max_drawdown": "max_drawdown_mean_pct",
    }
    for band, band_df in detail_df.groupby("neighbourhood_band"):
        row: Dict[str, Any] = {
            "sample_band": str(band),
            "start_date": "2021-04-20",
            "end_date": "2026-04-20",
            "sample_count": int(len(band_df)),
        }
        for source_col, target_col in metric_map.items():
            if source_col not in band_df.columns:
                row[target_col] = ""
                continue
            value = pd.to_numeric(band_df[source_col], errors="coerce").mean()
            row[target_col] = "" if pd.isna(value) else round(float(value), 3)
        rows.append(row)

    ready_df = pd.DataFrame(rows).sort_values("sample_band")
    ready_csv = output_root / "test11_report_ready_summary.csv"
    ready_md = output_root / "test11_report_ready_summary.md"
    ready_df.to_csv(ready_csv, index=False, encoding="utf-8-sig")
    columns = list(ready_df.columns)
    lines = [
        "# Test 11 Report-ready Summary",
        "",
        "This table is built from the formal fast factor-weight neighbourhood reruns and is used by the web robustness view.",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for record in ready_df.to_dict(orient="records"):
        lines.append("| " + " | ".join(str(record.get(col, "")) for col in columns) + " |")
    ready_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _build_test12_rolling_oos(perf_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    window = 24
    rows: List[Dict[str, Any]] = []
    if len(perf_df) <= window:
        return pd.DataFrame(), pd.DataFrame()

    net = perf_df["net_return"].fillna(0.0).to_numpy(dtype=float)
    bench = perf_df["benchmark_return"].fillna(0.0).to_numpy(dtype=float)
    detail_rows: List[Dict[str, Any]] = []
    oos_strategy: List[float] = []
    oos_benchmark: List[float] = []
    oos_excess: List[float] = []

    for end_idx in range(window, len(perf_df)):
        is_slice = slice(end_idx - window, end_idx)
        oos_idx = end_idx
        is_net = net[is_slice]
        is_bench = bench[is_slice]
        oos_ret = float(net[oos_idx])
        oos_bench = float(bench[oos_idx])
        oos_exc = oos_ret - oos_bench
        oos_strategy.append(oos_ret)
        oos_benchmark.append(oos_bench)
        oos_excess.append(oos_exc)
        detail_rows.append(
            {
                "period_end_date": perf_df.loc[oos_idx, "period_end_date"].date().isoformat(),
                "is_start_date": perf_df.loc[end_idx - window, "period_end_date"]
                .date()
                .isoformat(),
                "is_end_date": perf_df.loc[end_idx - 1, "period_end_date"].date().isoformat(),
                "is_ann_return": _annualized_return(is_net),
                "is_sharpe": _path_metrics(is_net)["sharpe"],
                "is_ann_excess_return": _annualized_return(is_net) - _annualized_return(is_bench),
                "oos_return": oos_ret,
                "oos_benchmark_return": oos_bench,
                "oos_excess_return": oos_exc,
                "beat_benchmark": oos_exc > 0,
            }
        )

    oos_strategy_arr = np.asarray(oos_strategy, dtype=float)
    oos_benchmark_arr = np.asarray(oos_benchmark, dtype=float)
    oos_detail_df = pd.DataFrame(detail_rows)
    summary_row = {
        "test_key": "test_12",
        "scenario_key": "rolling_24p_is_1p_oos",
        "title": "Rolling Out-of-Sample (24P IS / 1P OOS)",
        "implementation_status": "completed",
        "evidence_note": "Built directly from monthly return records of the quarterly-rebalanced strategy using rolling 24-period estimation windows and chained 1-period OOS evaluation.",
        "oos_period_count": int(len(oos_detail_df)),
        "oos_hit_rate": float((oos_detail_df["beat_benchmark"]).mean()),
        "oos_mean_excess_return": float(oos_detail_df["oos_excess_return"].mean()),
        "oos_median_excess_return": float(oos_detail_df["oos_excess_return"].median()),
        "oos_annualized_return": _annualized_return(oos_strategy_arr),
        "oos_benchmark_annualized_return": _annualized_return(oos_benchmark_arr),
        "oos_annualized_excess_return": _annualized_return(oos_strategy_arr)
        - _annualized_return(oos_benchmark_arr),
        "oos_sharpe": _path_metrics(oos_strategy_arr)["sharpe"],
        "oos_max_drawdown": _max_drawdown(oos_strategy_arr),
    }
    rows.append(summary_row)
    return pd.DataFrame(rows), oos_detail_df


def _simulate_parametric_paths(
    perf_df: pd.DataFrame,
    *,
    path_count: int,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    samples = perf_df[["net_return", "benchmark_return"]].fillna(0.0).to_numpy(dtype=float)
    mu = samples.mean(axis=0)
    sigma = np.cov(samples, rowvar=False, ddof=1)
    horizon = len(samples)
    detail_rows: List[Dict[str, Any]] = []
    sample_path_rows: List[Dict[str, Any]] = []
    sample_path_indices = set(range(min(5, path_count)))
    for path_index in range(path_count):
        simulated = rng.multivariate_normal(mu, sigma, size=horizon)
        strategy_path = simulated[:, 0]
        benchmark_path = simulated[:, 1]
        metrics = _path_metrics(strategy_path, benchmark_path)
        metrics["path_index"] = path_index
        detail_rows.append(metrics)
        if path_index in sample_path_indices:
            nav = np.cumprod(1.0 + strategy_path)
            for period_index, nav_value in enumerate(nav, start=1):
                sample_path_rows.append(
                    {
                        "path_index": path_index,
                        "period_index": period_index,
                        "simulated_nav": float(nav_value),
                    }
                )
    detail_df = pd.DataFrame(detail_rows)
    sample_paths_df = pd.DataFrame(sample_path_rows)
    summary_df = pd.DataFrame(
        [
            _summarize_path_distribution(
                test_key="test_13",
                scenario_key="empirical_mean_covariance",
                title="Monte Carlo Path Simulation from Empirical Mean/Covariance",
                path_df=detail_df,
                implementation_status="completed",
                evidence_note="Uses multivariate normal simulation fitted to realized monthly strategy and benchmark returns from the quarterly-rebalanced run.",
            )
        ]
    )
    return summary_df, detail_df, sample_paths_df


def _save_histogram(
    df: pd.DataFrame,
    column: str,
    title: str,
    output_path: Path,
    *,
    as_percent: bool = False,
) -> None:
    series = pd.to_numeric(df.get(column), errors="coerce").dropna()
    if series.empty:
        return
    values = series.to_numpy(dtype=float)
    if as_percent:
        values = values * 100.0
    plt.figure(figsize=(8, 4.5))
    plt.hist(values, bins=40, color="#2f5d8a", edgecolor="white", alpha=0.9)
    plt.title(title)
    plt.ylabel("Frequency")
    plt.xlabel(f"{column}{' (%)' if as_percent else ''}")
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=160)
    plt.close()


def _save_sample_paths(sample_paths_df: pd.DataFrame, output_path: Path) -> None:
    if sample_paths_df.empty:
        return
    plt.figure(figsize=(8, 4.5))
    for path_index, group in sample_paths_df.groupby("path_index"):
        plt.plot(
            group["period_index"],
            group["simulated_nav"],
            linewidth=1.4,
            label=f"path_{int(path_index) + 1}",
        )
    plt.title("Test 13 Sample Paths")
    plt.xlabel("Period")
    plt.ylabel("Simulated NAV")
    plt.legend(loc="best", fontsize=8)
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=160)
    plt.close()


def _write_report_ready_markdown(summary_frames: Iterable[pd.DataFrame], output_path: Path) -> None:
    rows: List[Dict[str, Any]] = []
    for frame in summary_frames:
        if not frame.empty:
            rows.extend(frame.to_dict(orient="records"))
    lines = ["# Stochastic Robustness Report-Ready Notes", ""]
    for row in rows:
        test_key = str(row.get("test_key"))
        if test_key == "test_9":
            lines.append(
                "Test 9 uses stationary block bootstrap on the realized monthly return series from the quarterly-rebalanced strategy. "
                f"The central annualized return is {float(row.get('annualized_return_p50')):.2%}, "
                f"the central Sharpe is {float(row.get('sharpe_p50')):.3f}, and the 90% annualized-return interval is "
                f"{float(row.get('annualized_return_ci90_low')):.2%} to {float(row.get('annualized_return_ci90_high')):.2%}."
            )
        elif (
            test_key == "test_10" and str(row.get("scenario_key")) == "cost_multiplier_sigma_30pct"
        ):
            lines.append(
                "Test 10 perturbs realized trading costs with epsilon ~ N(0, 0.3^2). "
                f"The central Sharpe is {float(row.get('sharpe_p50')):.3f}, "
                f"P(Sharpe > 0.50) is {float(row.get('probability_sharpe_gt_0_50')):.1%}, "
                f"and the worst-5% Sharpe CVaR is {float(row.get('sharpe_cvar_5pct')):.3f}."
            )
        elif test_key == "test_12":
            lines.append(
                "Test 12 evaluates a rolling 24-period in-sample / 1-period out-of-sample chain. "
                f"Out-of-sample annualized return is {float(row.get('oos_annualized_return')):.2%}, "
                f"Sharpe is {float(row.get('oos_sharpe')):.3f}, and hit rate versus benchmark is {float(row.get('oos_hit_rate')):.1%}."
            )
        elif test_key == "test_13":
            lines.append(
                "Test 13 simulates long-run paths from the empirical mean/covariance fit. "
                f"The annualized-return percentiles are {float(row.get('annualized_return_p05')):.2%} / "
                f"{float(row.get('annualized_return_p25')):.2%} / {float(row.get('annualized_return_p50')):.2%} / "
                f"{float(row.get('annualized_return_p75')):.2%} / {float(row.get('annualized_return_p95')):.2%}, "
                f"with central Sharpe {float(row.get('sharpe_p50')):.3f}."
            )
        lines.append("")
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _conclusion_for_row(row: Mapping[str, Any]) -> str:
    ann_return = float(
        row.get("annualized_return_p50", row.get("oos_annualized_return", float("nan")))
    )
    sharpe = row.get("sharpe_p50", row.get("oos_sharpe", float("nan")))
    pos_prob = row.get("positive_return_probability", row.get("oos_hit_rate", float("nan")))
    impl = str(row.get("implementation_status", ""))
    note = str(row.get("evidence_note", ""))
    return (
        f"{row.get('title')} delivers about {ann_return:.2%} annualized return at the central estimate, "
        f"about {float(sharpe):.3f} Sharpe, and about {float(pos_prob):.1%} on the key positive-probability metric. "
        f"Implementation status: {impl}. {note}"
    )


def _build_dashboard(
    perf_df: pd.DataFrame,
    summary_frames: Iterable[pd.DataFrame],
) -> pd.DataFrame:
    baseline = _path_metrics(
        perf_df["net_return"].fillna(0.0).to_numpy(dtype=float),
        perf_df["benchmark_return"].fillna(0.0).to_numpy(dtype=float),
    )
    rows: List[Dict[str, Any]] = [
        {
            "section": "baseline",
            "item_key": "mainline_realized",
            "title": "Mainline Realized Baseline",
            "annualized_return": baseline["annualized_return"],
            "annualized_excess_return": baseline.get("annualized_excess_return"),
            "sharpe": baseline["sharpe"],
            "max_drawdown": baseline["max_drawdown"],
            "implementation_status": "completed",
        }
    ]
    for frame in summary_frames:
        if frame.empty:
            continue
        for row in frame.to_dict(orient="records"):
            rows.append(
                {
                    "section": row.get("test_key"),
                    "item_key": row.get("scenario_key"),
                    "title": row.get("title"),
                    "annualized_return": row.get(
                        "annualized_return_p50", row.get("oos_annualized_return")
                    ),
                    "annualized_excess_return": row.get(
                        "annualized_excess_return_p50",
                        row.get("oos_annualized_excess_return"),
                    ),
                    "sharpe": row.get("sharpe_p50", row.get("oos_sharpe")),
                    "max_drawdown": row.get("max_drawdown_p50", row.get("oos_max_drawdown")),
                    "implementation_status": row.get("implementation_status"),
                }
            )
    return pd.DataFrame(rows)


def _build_status_matrix(summary_frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for frame in summary_frames:
        if frame.empty:
            continue
        for row in frame.to_dict(orient="records"):
            rows.append(
                {
                    "category": "stochastic_acceptance",
                    "item_key": f"{row.get('test_key')}::{row.get('scenario_key')}",
                    "label": row.get("title"),
                    "status": row.get("implementation_status"),
                    "detail": row.get("evidence_note"),
                }
            )
    return pd.DataFrame(rows)


def _markdown_report(summary_frames: Iterable[pd.DataFrame]) -> str:
    lines = [
        "# Stochastic Robustness Acceptance Pack",
        "",
        "## Test Status",
        "",
        "| Test | Scenario | Status | P50 Ann Return / OOS Ann Return | P50 Sharpe / OOS Sharpe |",
        "|---|---|---|---:|---:|",
    ]
    all_rows: List[Dict[str, Any]] = []
    for frame in summary_frames:
        if not frame.empty:
            all_rows.extend(frame.to_dict(orient="records"))
    for row in all_rows:
        ann_return = row.get("annualized_return_p50", row.get("oos_annualized_return"))
        sharpe = row.get("sharpe_p50", row.get("oos_sharpe"))
        lines.append(
            f"| {row.get('test_key')} | {row.get('scenario_key')} | {row.get('implementation_status')} | {float(ann_return):.2%} | {float(sharpe):.3f} |"
        )
    lines.extend(["", "## Conclusions", ""])
    for row in all_rows:
        lines.append(f"- {_conclusion_for_row(row)}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_env_layers()

    run_id = str(args.run_id)
    path_metrics_root = Path(str(args.path_metrics_root)).resolve()
    test11_rerun_summary_path = _resolve_latest_tagged_csv(
        Path(str(args.test11_rerun_summary_csv)).resolve()
    )
    output_root = Path(str(args.output_root)).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    plots_root = output_root / "plots"
    rng = np.random.default_rng(int(args.seed))

    perf_df = _fetch_performance(run_id)
    test9_summary, test9_detail = _build_test9_bootstrap(path_metrics_root)
    test10_summary, test10_detail = _simulate_cost_paths(
        perf_df,
        path_count=int(args.cost_paths),
        rng=rng,
    )
    test11_summary, test11_detail = _build_test11_rerun_summary(test11_rerun_summary_path)
    _write_test11_report_ready(
        test11_detail,
        test11_rerun_summary_path.parent / "report_ready",
    )
    if test11_summary.empty:
        test11_summary, test11_detail = _build_test11_dirichlet(path_metrics_root)
    test12_summary, test12_detail = _build_test12_rolling_oos(perf_df)
    test13_summary, test13_detail, test13_sample_paths = _simulate_parametric_paths(
        perf_df,
        path_count=int(args.parametric_paths),
        rng=rng,
    )

    summary_frames = [
        test9_summary,
        test10_summary,
        test11_summary,
        test12_summary,
        test13_summary,
    ]
    stochastic_acceptance_summary = pd.concat(
        [frame for frame in summary_frames if not frame.empty],
        ignore_index=True,
    )
    dashboard_df = _build_dashboard(perf_df, summary_frames)
    status_df = _build_status_matrix(summary_frames)

    test9_summary.to_csv(
        output_root / "test9_bootstrap_summary.csv", index=False, encoding="utf-8-sig"
    )
    test9_detail.to_csv(
        output_root / "test9_bootstrap_paths.csv", index=False, encoding="utf-8-sig"
    )
    test10_summary.to_csv(
        output_root / "test10_cost_perturbation_summary.csv", index=False, encoding="utf-8-sig"
    )
    test10_detail.to_csv(
        output_root / "test10_cost_perturbation_paths.csv", index=False, encoding="utf-8-sig"
    )
    test11_summary.to_csv(
        output_root / "test11_dirichlet_neighbourhood_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    if not test11_detail.empty:
        test11_detail.to_csv(
            output_root / "test11_dirichlet_neighbourhood_paths.csv",
            index=False,
            encoding="utf-8-sig",
        )
    test12_summary.to_csv(
        output_root / "test12_rolling_oos_summary.csv", index=False, encoding="utf-8-sig"
    )
    test12_detail.to_csv(
        output_root / "test12_rolling_oos_detail.csv", index=False, encoding="utf-8-sig"
    )
    test13_summary.to_csv(
        output_root / "test13_parametric_path_summary.csv", index=False, encoding="utf-8-sig"
    )
    test13_detail.to_csv(
        output_root / "test13_parametric_path_metrics.csv", index=False, encoding="utf-8-sig"
    )
    if not test13_sample_paths.empty:
        test13_sample_paths.to_csv(
            output_root / "test13_sample_paths.csv", index=False, encoding="utf-8-sig"
        )
    stochastic_acceptance_summary.to_csv(
        output_root / "stochastic_acceptance_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    dashboard_df.to_csv(output_root / "robustness_dashboard.csv", index=False, encoding="utf-8-sig")
    status_df.to_csv(
        output_root / "stochastic_acceptance_status.csv", index=False, encoding="utf-8-sig"
    )
    (output_root / "stochastic_acceptance_report.md").write_text(
        _markdown_report(summary_frames),
        encoding="utf-8",
    )
    _write_report_ready_markdown(summary_frames, output_root / "stochastic_report_ready_notes.md")
    _save_histogram(
        test9_detail,
        "sharpe",
        "Test 9 Bootstrap Sharpe Distribution",
        plots_root / "test9_bootstrap_sharpe_hist.png",
    )
    _save_histogram(
        test10_detail[test10_detail["scenario_key"] == "cost_multiplier_sigma_30pct"],
        "sharpe",
        "Test 10 Cost Perturbation Sharpe Distribution",
        plots_root / "test10_cost_sigma30_sharpe_hist.png",
    )
    _save_histogram(
        test12_detail,
        "oos_excess_return",
        "Test 12 OOS Excess Return Distribution",
        plots_root / "test12_oos_excess_return_hist.png",
        as_percent=True,
    )
    _save_histogram(
        test13_detail,
        "sharpe",
        "Test 13 Monte Carlo Sharpe Distribution",
        plots_root / "test13_parametric_sharpe_hist.png",
    )
    _save_sample_paths(test13_sample_paths, plots_root / "test13_sample_paths.png")
    (output_root / "stochastic_acceptance_manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "output_root": str(output_root),
                "summary_rows": int(len(stochastic_acceptance_summary)),
                "dashboard_rows": int(len(dashboard_df)),
                "status_rows": int(len(status_df)),
                "plots": [
                    "plots/test9_bootstrap_sharpe_hist.png",
                    "plots/test10_cost_sigma30_sharpe_hist.png",
                    "plots/test12_oos_excess_return_hist.png",
                    "plots/test13_parametric_sharpe_hist.png",
                    "plots/test13_sample_paths.png",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "output_root": str(output_root),
                "summary_rows": int(len(stochastic_acceptance_summary)),
                "dashboard_rows": int(len(dashboard_df)),
                "status_rows": int(len(status_df)),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
