from __future__ import annotations

"""Build an ordered report evidence pack for the coursework robustness section."""

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import matplotlib
import pandas as pd
from sqlalchemy import text

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"
ROBUSTNESS_ROOT = CW2_ROOT / "outputs" / "robustness"
REQUIREMENT_ROOT = ROBUSTNESS_ROOT / "requirement_report"
STOCHASTIC_ACCEPTANCE_ROOT = ROBUSTNESS_ROOT / "stochastic" / "acceptance"
SUBPERIOD_ROOT = ROBUSTNESS_ROOT / "subperiod"
DEFAULT_OUTPUT_ROOT = ROBUSTNESS_ROOT / "report_evidence"
FORMAL_BASELINE_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.modules.robustness.persistence import (  # noqa: E402
    persist_robustness_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build report-ready robustness evidence files.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    return parser


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _resolve_latest_tagged_csv(path: Path) -> Path:
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


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fmt_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.3f}%"


def _fmt_dec_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value) * 100.0:.3f}%"


def _fmt_num(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.3f}"


def _write_markdown(path: Path, lines: Iterable[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _bar_chart(
    df: pd.DataFrame,
    label_col: str,
    value_cols: Sequence[str],
    output_path: Path,
    *,
    title: str,
    percent_cols: Optional[Sequence[str]] = None,
) -> None:
    if df.empty:
        return
    percent_cols = set(percent_cols or [])
    chart_df = df[[label_col, *value_cols]].copy()
    chart_df = chart_df.fillna(0.0)
    labels = chart_df[label_col].astype(str).tolist()
    x = range(len(labels))
    width = 0.8 / max(len(value_cols), 1)
    plt.figure(figsize=(10, 4.8))
    for idx, col in enumerate(value_cols):
        values = pd.to_numeric(chart_df[col], errors="coerce").fillna(0.0)
        if col in percent_cols:
            values = values * 100.0
        offset = (idx - (len(value_cols) - 1) / 2) * width
        plt.bar([item + offset for item in x], values, width=width, label=col)
    plt.xticks(list(x), labels, rotation=25, ha="right")
    plt.title(title)
    plt.legend(loc="best", fontsize=8)
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=160)
    plt.close()


def _extract_chart_path(report_field: Any, chart_key: str) -> Optional[Path]:
    if report_field is None or pd.isna(report_field):
        return None
    try:
        report_dict = ast.literal_eval(str(report_field))
    except (ValueError, SyntaxError):
        return None
    chart_paths = report_dict.get("chart_paths", {})
    raw = chart_paths.get(chart_key)
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.exists() else None


def _copy_file(src: Optional[Path], dst: Path) -> bool:
    if src is None or not src.exists():
        return False
    dst.write_bytes(src.read_bytes())
    return True


def _central_nav_reference(output_root: Path) -> Optional[Path]:
    """Generate one formal baseline NAV figure for fast summary-only reruns."""
    shared_root = _ensure_dir(output_root / "shared")
    chart_path = shared_root / "formal_baseline_nav_reference.png"
    if chart_path.exists():
        return chart_path
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            perf = pd.read_sql(
                text("""
                    SELECT period_end_date, portfolio_nav
                    FROM systematic_equity.backtest_performance
                    WHERE run_id = :run_id
                    ORDER BY period_end_date
                    """),
                conn,
                params={"run_id": FORMAL_BASELINE_RUN_ID},
            )
            bench = pd.read_sql(
                text("""
                    SELECT period_end_date, series_name, nav
                    FROM systematic_equity.backtest_benchmark_nav
                    WHERE run_id = :run_id
                    ORDER BY period_end_date, series_name
                    """),
                conn,
                params={"run_id": FORMAL_BASELINE_RUN_ID},
            )
    except Exception:
        return None
    if perf.empty:
        return None
    perf["period_end_date"] = pd.to_datetime(perf["period_end_date"])
    perf["portfolio_nav"] = pd.to_numeric(perf["portfolio_nav"], errors="coerce")
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    ax.plot(perf["period_end_date"], perf["portfolio_nav"], label="strategy", linewidth=2.2)
    if not bench.empty:
        bench["period_end_date"] = pd.to_datetime(bench["period_end_date"])
        bench["nav"] = pd.to_numeric(bench["nav"], errors="coerce")
        for series_name, group in bench.groupby("series_name"):
            ax.plot(group["period_end_date"], group["nav"], label=str(series_name), linewidth=1.6)
    ax.set_title("Formal Baseline NAV vs Benchmarks")
    ax.set_ylabel("NAV")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(chart_path, dpi=180)
    plt.close(fig)
    return chart_path if chart_path.exists() else None


def _build_part1(deterministic_df: pd.DataFrame, output_root: Path) -> List[Dict[str, str]]:
    part_root = _ensure_dir(output_root / "part_1_deterministic")
    central_nav_src = _central_nav_reference(output_root)
    config = {
        1: {
            "title": "Test 1 - Trading Cost Sensitivity",
            "columns": [
                "scenario_key",
                "risk_adjusted.sharpe_ratio",
                "return.annualized_return",
                "portfolio.total_cost_drag",
                "static_baseline.excess_return_annualized",
            ],
            "chart_cols": ["risk_adjusted.sharpe_ratio", "return.annualized_return"],
            "percent_cols": ["return.annualized_return"],
        },
        2: {
            "title": "Test 2 - Backtest Window Start Sensitivity",
            "columns": [
                "scenario_key",
                "risk_adjusted.sharpe_ratio",
                "return.annualized_return",
                "risk.max_drawdown",
                "static_baseline.excess_return_annualized",
            ],
            "chart_cols": [
                "risk_adjusted.sharpe_ratio",
                "static_baseline.excess_return_annualized",
            ],
            "percent_cols": ["static_baseline.excess_return_annualized"],
        },
        3: {
            "title": "Test 3 - Concentration Sensitivity",
            "columns": [
                "scenario_key",
                "risk_adjusted.sharpe_ratio",
                "risk.annualized_volatility",
                "portfolio.avg_holdings",
                "risk.max_drawdown",
                "portfolio.avg_monthly_recorded_turnover",
            ],
            "chart_cols": ["risk_adjusted.sharpe_ratio", "risk.max_drawdown"],
            "percent_cols": [],
        },
        4: {
            "title": "Test 4 - Factor Weight Perturbation Sensitivity",
            "columns": [
                "scenario_key",
                "risk_adjusted.sharpe_ratio",
                "static_baseline.excess_return_annualized",
                "return.annualized_return",
            ],
            "chart_cols": [
                "risk_adjusted.sharpe_ratio",
                "static_baseline.excess_return_annualized",
            ],
            "percent_cols": ["static_baseline.excess_return_annualized"],
        },
        5: {
            "title": "Test 5 - Regime Threshold Sensitivity",
            "columns": [
                "scenario_key",
                "risk_adjusted.sharpe_ratio",
                "stress.static_baseline.excess_ann_return",
                "risk.max_drawdown",
            ],
            "chart_cols": [
                "risk_adjusted.sharpe_ratio",
                "stress.static_baseline.excess_ann_return",
            ],
            "percent_cols": ["stress.static_baseline.excess_ann_return"],
        },
        6: {
            "title": "Test 6 - Drawdown Brake Sensitivity",
            "columns": [
                "scenario_key",
                "risk_adjusted.sharpe_ratio",
                "risk.max_drawdown",
                "portfolio.avg_monthly_recorded_turnover",
                "drawdown_brake_trigger_count",
                "drawdown_brake_trigger_months",
            ],
            "chart_cols": ["risk_adjusted.sharpe_ratio", "portfolio.avg_monthly_recorded_turnover"],
            "percent_cols": ["portfolio.avg_monthly_recorded_turnover"],
        },
        7: {
            "title": "Test 7 - Banded Selector Sensitivity",
            "columns": [
                "scenario_key",
                "risk_adjusted.sharpe_ratio",
                "portfolio.avg_monthly_recorded_turnover",
                "portfolio.avg_holdings",
            ],
            "chart_cols": ["risk_adjusted.sharpe_ratio", "portfolio.avg_monthly_recorded_turnover"],
            "percent_cols": ["portfolio.avg_monthly_recorded_turnover"],
        },
        8: {
            "title": "Test 8 - No-Trade Band and Per-Name Cap Sensitivity",
            "columns": [
                "scenario_key",
                "risk_adjusted.sharpe_ratio",
                "portfolio.avg_monthly_recorded_turnover",
                "risk.max_drawdown",
            ],
            "chart_cols": ["risk_adjusted.sharpe_ratio", "portfolio.avg_monthly_recorded_turnover"],
            "percent_cols": ["portfolio.avg_monthly_recorded_turnover"],
        },
    }
    index_rows: List[Dict[str, str]] = []
    for test_key, meta in config.items():
        test_df = deterministic_df[deterministic_df["test_key"] == test_key].copy()
        if test_df.empty:
            continue
        keep_cols = [col for col in meta["columns"] if col in test_df.columns]
        export_df = test_df[keep_cols].copy()
        csv_path = part_root / f"test_{test_key:02d}_table.csv"
        export_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        chart_path = part_root / f"test_{test_key:02d}_chart.png"
        _bar_chart(
            export_df,
            "scenario_key",
            [col for col in meta["chart_cols"] if col in export_df.columns],
            chart_path,
            title=meta["title"],
            percent_cols=[col for col in meta["percent_cols"] if col in export_df.columns],
        )
        mainline_row = test_df.sort_values("risk_adjusted.sharpe_ratio", ascending=False).iloc[0]
        lines = [
            f"# {meta['title']}",
            "",
            "## Table",
            f"- Source table: `{csv_path.name}`",
            f"- Figure: `{chart_path.name}`",
            "",
            "## Writing Notes",
            (
                f"This test contains {len(test_df)} scenarios. "
                f"The best observed Sharpe in this block is {_fmt_num(mainline_row.get('risk_adjusted.sharpe_ratio'))}, "
                f"with annualized return {_fmt_pct(mainline_row.get('return.annualized_return'))}."
            ),
            (
                "Use the table to compare the full scenario set, and use the bar chart to describe whether the mainline "
                "configuration remains inside a stable neighbourhood rather than standing on an isolated spike."
            ),
        ]
        if "static_baseline.excess_return_annualized" in test_df.columns:
            positive = (
                pd.to_numeric(
                    test_df["static_baseline.excess_return_annualized"], errors="coerce"
                ).fillna(0.0)
                > 0
            ).all()
            lines.append(
                "All scenarios keep positive excess return versus static baseline."
                if positive
                else "At least one scenario loses positive excess return versus static baseline and should be described honestly."
            )
        md_path = part_root / f"test_{test_key:02d}_notes.md"
        _write_markdown(md_path, lines)
        # Reuse one representative nav figure when available.
        nav_src = _extract_chart_path(test_df.iloc[0].get("report"), "nav_vs_benchmarks")
        nav_dst = part_root / f"test_{test_key:02d}_nav_reference.png"
        if _copy_file(nav_src, nav_dst) or _copy_file(central_nav_src, nav_dst):
            lines.extend(["", f"- Extra reference NAV chart: `{nav_dst.name}`"])
            _write_markdown(md_path, lines)
        index_rows.append(
            {
                "part": "Part 1",
                "item": f"Test {test_key}",
                "table": csv_path.name,
                "figure": chart_path.name,
                "notes": md_path.name,
            }
        )
    return index_rows


def _build_part2(ablation_df: pd.DataFrame, output_root: Path) -> List[Dict[str, str]]:
    part_root = _ensure_dir(output_root / "part_2_ablation")
    central_nav_src = _central_nav_reference(output_root)
    index_rows: List[Dict[str, str]] = []
    for block_key in ("A", "B", "C"):
        block_df = ablation_df[ablation_df["block_key"] == block_key].copy()
        if block_df.empty:
            continue
        export_df = block_df[
            [
                "scenario_key",
                "return.annualized_return",
                "risk_adjusted.sharpe_ratio",
                "risk.max_drawdown",
                "portfolio.avg_monthly_recorded_turnover",
            ]
        ].copy()
        csv_path = part_root / f"ablation_block_{block_key.lower()}_table.csv"
        export_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        chart_path = part_root / f"ablation_block_{block_key.lower()}_chart.png"
        _bar_chart(
            export_df,
            "scenario_key",
            ["risk_adjusted.sharpe_ratio", "return.annualized_return"],
            chart_path,
            title=f"Ablation Block {block_key}",
            percent_cols=["return.annualized_return"],
        )
        mainline_like = block_df.sort_values("risk_adjusted.sharpe_ratio", ascending=False).iloc[0]
        lines = [
            f"# Ablation Block {block_key}",
            "",
            f"- Source table: `{csv_path.name}`",
            f"- Figure: `{chart_path.name}`",
            "",
            "## Writing Notes",
            (
                f"Block {block_key} compares {len(block_df)} ablation scenarios. "
                f"The highest Sharpe in this block is {_fmt_num(mainline_like.get('risk_adjusted.sharpe_ratio'))} "
                f"and the corresponding annualized return is {_fmt_pct(mainline_like.get('return.annualized_return'))}."
            ),
            (
                "The report should explain whether removing a factor or mechanism lowers risk-adjusted performance, "
                "or whether a component appears redundant or even harmful in the current sample."
            ),
        ]
        md_path = part_root / f"ablation_block_{block_key.lower()}_notes.md"
        _write_markdown(md_path, lines)
        nav_src = _extract_chart_path(block_df.iloc[0].get("report"), "nav_vs_benchmarks")
        _copy_file(
            nav_src, part_root / f"ablation_block_{block_key.lower()}_nav_reference.png"
        ) or _copy_file(
            central_nav_src,
            part_root / f"ablation_block_{block_key.lower()}_nav_reference.png",
        )
        index_rows.append(
            {
                "part": "Part 2",
                "item": f"Ablation {block_key}",
                "table": csv_path.name,
                "figure": chart_path.name,
                "notes": md_path.name,
            }
        )
    return index_rows


def _build_part3(
    requirement_root: Path, subperiod_root: Path, output_root: Path
) -> List[Dict[str, str]]:
    part_root = _ensure_dir(output_root / "part_3_subperiod")
    index_rows: List[Dict[str, str]] = []
    fixed_df = _read_csv(requirement_root / "subperiod_master.csv")
    regime_df = _read_csv(requirement_root / "baseline_regime_subperiod.csv")
    coverage_note = subperiod_root / "subperiod_coverage_note.md"
    if not fixed_df.empty:
        fixed_csv = part_root / "subperiod_fixed_windows_table.csv"
        fixed_df.to_csv(fixed_csv, index=False, encoding="utf-8-sig")
        fixed_chart = part_root / "subperiod_fixed_windows_chart.png"
        chart_df = fixed_df[fixed_df["n_periods"].fillna(0) > 0].copy()
        if not chart_df.empty:
            _bar_chart(
                chart_df,
                "window_label",
                ["strategy_ann_return", "excess_ann_return"],
                fixed_chart,
                title="Subperiod Fixed Window Annualized Return",
                percent_cols=["strategy_ann_return", "excess_ann_return"],
            )
        fixed_md = part_root / "subperiod_fixed_windows_notes.md"
        _write_markdown(
            fixed_md,
            [
                "# Sub-Period 1 - Fixed Windows",
                "",
                f"- Source table: `{fixed_csv.name}`",
                f"- Figure: `{fixed_chart.name}`",
                "",
                "## Writing Notes",
                "Use the table to discuss each historical window separately.",
                "Rows with `n_periods = 0` are unavailable because the current baseline series starts in June 2021.",
                f"- Coverage note: `{coverage_note.name}`",
            ],
        )
        _copy_file(coverage_note, part_root / coverage_note.name)
        index_rows.append(
            {
                "part": "Part 3",
                "item": "Fixed windows",
                "table": fixed_csv.name,
                "figure": fixed_chart.name,
                "notes": fixed_md.name,
            }
        )
    if not regime_df.empty:
        regime_csv = part_root / "subperiod_regime_decomposition_table.csv"
        regime_df.to_csv(regime_csv, index=False, encoding="utf-8-sig")
        regime_chart = part_root / "subperiod_regime_decomposition_chart.png"
        _bar_chart(
            regime_df,
            "regime",
            ["strategy_ann_return", "excess_ann_return"],
            regime_chart,
            title="Regime Decomposition Annualized Return",
            percent_cols=["strategy_ann_return", "excess_ann_return"],
        )
        regime_md = part_root / "subperiod_regime_decomposition_notes.md"
        _write_markdown(
            regime_md,
            [
                "# Sub-Period 2 - Regime Decomposition",
                "",
                f"- Source table: `{regime_csv.name}`",
                f"- Figure: `{regime_chart.name}`",
                "",
                "## Writing Notes",
                "This table is the cleanest source for the normal / stress / all discussion.",
                "Stress-period excess return versus static baseline remains the key sentence for justifying regime switching.",
            ],
        )
        index_rows.append(
            {
                "part": "Part 3",
                "item": "Regime decomposition",
                "table": regime_csv.name,
                "figure": regime_chart.name,
                "notes": regime_md.name,
            }
        )
    return index_rows


def _build_part4(
    stochastic_df: pd.DataFrame, acceptance_root: Path, output_root: Path
) -> List[Dict[str, str]]:
    part_root = _ensure_dir(output_root / "part_4_stochastic")
    plots_root = acceptance_root / "plots"
    index_rows: List[Dict[str, str]] = []
    config = {
        "test_9": ("Stationary Block Bootstrap", "test9_bootstrap_sharpe_hist.png"),
        "test_10": ("Monte Carlo Cost Perturbation", "test10_cost_sigma30_sharpe_hist.png"),
        "test_11": ("Factor-weight Dirichlet Neighbourhood", ""),
        "test_12": ("Rolling Out-of-Sample", "test12_oos_excess_return_hist.png"),
        "test_13": ("Monte Carlo Path Simulation", "test13_parametric_sharpe_hist.png"),
    }
    for test_key, (title, plot_name) in config.items():
        subset = stochastic_df[stochastic_df["test_key"] == test_key].copy()
        if subset.empty:
            continue
        csv_path = part_root / f"{test_key}_table.csv"
        subset.to_csv(csv_path, index=False, encoding="utf-8-sig")
        plot_dst = part_root / plot_name if plot_name else None
        if plot_name:
            plot_src = plots_root / plot_name
            _copy_file(plot_src, plot_dst)
        lines = [
            f"# {title}",
            "",
            f"- Source table: `{csv_path.name}`",
            "",
            "## Writing Notes",
        ]
        if plot_dst is not None:
            lines.insert(3, f"- Figure: `{plot_dst.name}`")
        row = subset.iloc[0]
        if test_key == "test_9":
            lines.append(
                f"The bootstrap central Sharpe is {_fmt_num(row.get('sharpe_p50'))}, with annualized return interval {_fmt_dec_pct(row.get('annualized_return_p05'))} to {_fmt_dec_pct(row.get('annualized_return_p95'))}."
            )
        elif test_key == "test_10":
            lines.append(
                f"The sigma 30% cost perturbation keeps central Sharpe at {_fmt_num(row.get('sharpe_p50'))}, and P(Sharpe > 0.50) is {_fmt_num(float(row.get('probability_sharpe_gt_0_50', 0)) * 100.0)}%."
            )
        elif test_key == "test_11":
            lines.append(
                "This is the current report-usable Test 11 rerun set built from full reruns around sampled regime.normal factor weights."
            )
            lines.append(
                f"The current loose / medium / tight bands use {int(pd.to_numeric(subset['path_count'], errors='coerce').fillna(0).max())} reruns per grouped scenario row in the acceptance summary."
            )
            lines.append(
                "Use this section as local-robustness evidence, but avoid overstating it as a 200-path neighbourhood study."
            )
            report_ready_src = (
                acceptance_root.parent.parent
                / "test11_factor_neighbourhood"
                / "summaries"
                / "report_ready"
                / "test11_report_ready_summary.md"
            )
            report_ready_csv_src = (
                acceptance_root.parent.parent
                / "test11_factor_neighbourhood"
                / "summaries"
                / "report_ready"
                / "test11_report_ready_summary.csv"
            )
            raw_summary_src = _resolve_latest_tagged_csv(
                acceptance_root.parent.parent
                / "test11_factor_neighbourhood"
                / "summaries"
                / "test11_factor_neighbourhood_summary.csv"
            )
            _copy_file(report_ready_src, part_root / "test11_report_ready_summary.md")
            _copy_file(report_ready_csv_src, part_root / "test11_report_ready_summary.csv")
            _copy_file(raw_summary_src, part_root / "test11_factor_neighbourhood_summary.csv")
        elif test_key == "test_12":
            lines.append(
                f"Rolling OOS annualized return is {_fmt_dec_pct(row.get('oos_annualized_return'))}, with OOS Sharpe {_fmt_num(row.get('oos_sharpe'))}."
            )
        elif test_key == "test_13":
            lines.append(
                f"The central Monte Carlo Sharpe is {_fmt_num(row.get('sharpe_p50'))}, with central annualized return {_fmt_dec_pct(row.get('annualized_return_p50'))}."
            )
            sample_src = plots_root / "test13_sample_paths.png"
            _copy_file(sample_src, part_root / "test13_sample_paths.png")
            lines.append("- Extra figure: `test13_sample_paths.png`")
        md_path = part_root / f"{test_key}_notes.md"
        _write_markdown(md_path, lines)
        index_rows.append(
            {
                "part": "Part 4",
                "item": test_key,
                "table": csv_path.name,
                "figure": "" if plot_dst is None else plot_dst.name,
                "notes": md_path.name,
            }
        )
    # Add general stochastic notes.
    notes_src = acceptance_root / "stochastic_report_ready_notes.md"
    _copy_file(notes_src, part_root / notes_src.name)
    return index_rows


def _build_part5(requirement_root: Path, output_root: Path) -> List[Dict[str, str]]:
    part_root = _ensure_dir(output_root / "part_5_dashboard_and_conclusions")
    index_rows: List[Dict[str, str]] = []
    for name in [
        "acceptance_matrix.csv",
        "stochastic_dashboard.csv",
        "robustness_requirement_report.md",
        "baseline_scorecard.csv",
    ]:
        src = requirement_root / name
        if src.exists():
            _copy_file(src, part_root / name)
    notes_path = part_root / "dashboard_notes.md"
    _write_markdown(
        notes_path,
        [
            "# Part 5 Packaging",
            "",
            "Use `acceptance_matrix.csv` to explain which blocks are complete, which are partial, and why.",
            "Use `stochastic_dashboard.csv` and `baseline_scorecard.csv` for the top-level robustness summary paragraph.",
            "Use `robustness_requirement_report.md` as the long-form internal reference, not as the final polished report text.",
        ],
    )
    index_rows.append(
        {
            "part": "Part 5",
            "item": "Dashboard",
            "table": "acceptance_matrix.csv",
            "figure": "stochastic_dashboard.csv",
            "notes": notes_path.name,
        }
    )
    return index_rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_root = _ensure_dir(Path(str(args.output_root)).resolve())
    deterministic_df = _read_csv(REQUIREMENT_ROOT / "deterministic_master.csv")
    ablation_df = _read_csv(REQUIREMENT_ROOT / "ablation_master.csv")
    stochastic_df = _read_csv(STOCHASTIC_ACCEPTANCE_ROOT / "stochastic_acceptance_summary.csv")

    index_rows: List[Dict[str, str]] = []
    index_rows.extend(_build_part1(deterministic_df, output_root))
    index_rows.extend(_build_part2(ablation_df, output_root))
    index_rows.extend(_build_part3(REQUIREMENT_ROOT, SUBPERIOD_ROOT, output_root))
    index_rows.extend(_build_part4(stochastic_df, STOCHASTIC_ACCEPTANCE_ROOT, output_root))
    index_rows.extend(_build_part5(REQUIREMENT_ROOT, output_root))

    index_df = pd.DataFrame(index_rows)
    index_df.to_csv(output_root / "REPORT_EVIDENCE_INDEX.csv", index=False, encoding="utf-8-sig")
    _write_markdown(
        output_root / "REPORT_EVIDENCE_INDEX.md",
        [
            "# Robustness Report Evidence Pack",
            "",
            "This directory is ordered to match the requirement document from Part 1 onwards.",
            "Each part folder contains report-group friendly tables, figures, and short writing notes.",
            "",
            "Formal baseline: `cw2_formal_20260420_fund_ra3_s30_t50`; formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`.",
            "Target generation and actual rebalancing are quarterly. Monthly rows are holding-period performance records, not monthly rebalancing.",
            "The 2026-04-24 report is deliberately excluded because it predates the PIT fix and formal parameter selection.",
            "",
            "| Part | Item | Table | Figure | Notes |",
            "|---|---|---|---|---|",
            *[
                f"| {row['part']} | {row['item']} | {row['table']} | {row['figure']} | {row['notes']} |"
                for row in index_rows
            ],
        ],
    )
    (output_root / "manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "output_root": str(output_root),
                "index_rows": len(index_rows),
                "parts": sorted({row["part"] for row in index_rows}),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    persistence_result = None
    try:
        persistence_result = persist_robustness_outputs(
            engine=get_db_engine(),
            report_name="cw2_robustness_report_evidence_pack",
            output_root=output_root,
            source_run_id=None,
        )
    except Exception:
        persistence_result = {"ok": False, "error": "robustness_persistence_failed"}
    print(
        json.dumps(
            {
                "ok": True,
                "output_root": str(output_root),
                "index_rows": len(index_rows),
                "robustness_persistence": persistence_result,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
