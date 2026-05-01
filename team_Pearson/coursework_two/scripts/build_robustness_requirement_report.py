from __future__ import annotations

"""Build report-friendly robustness outputs aligned with the coursework requirement sheet."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

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
from team_Pearson.coursework_two.modules.robustness.persistence import (  # noqa: E402
    persist_robustness_outputs,
)
from team_Pearson.coursework_two.scripts.orchestration import load_env_layers  # noqa: E402

_SCHEMA = "systematic_equity"
_DEFAULT_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"
_DEFAULT_SENSITIVITY_SUMMARY_DIR = CW2_ROOT / "outputs" / "robustness" / "sensitivity" / "summaries"
_DEFAULT_STOCHASTIC_SUMMARY = (
    CW2_ROOT
    / "outputs"
    / "robustness"
    / "stochastic"
    / "summaries"
    / "stochastic_robustness_summary.csv"
)
_DEFAULT_ABLATION_SUMMARY_DIR = CW2_ROOT / "outputs" / "robustness" / "ablation" / "summaries"
_DEFAULT_SUBPERIOD_SUMMARY = (
    CW2_ROOT / "outputs" / "robustness" / "subperiod" / "subperiod_analysis.csv"
)
_DEFAULT_OUTPUT_ROOT = CW2_ROOT / "outputs" / "robustness" / "requirement_report"
_DEFAULT_STOCHASTIC_ACCEPTANCE_SUMMARY = (
    CW2_ROOT
    / "outputs"
    / "robustness"
    / "stochastic"
    / "acceptance"
    / "stochastic_acceptance_summary.csv"
)
_DEFAULT_STOCHASTIC_ACCEPTANCE_STATUS = (
    CW2_ROOT
    / "outputs"
    / "robustness"
    / "stochastic"
    / "acceptance"
    / "stochastic_acceptance_status.csv"
)
_DEFAULT_STOCHASTIC_DASHBOARD = (
    CW2_ROOT / "outputs" / "robustness" / "stochastic" / "acceptance" / "robustness_dashboard.csv"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build requirement-aligned robustness summary tables and markdown."
    )
    parser.add_argument("--run-id", default=_DEFAULT_RUN_ID)
    parser.add_argument("--sensitivity-summary-dir", default=str(_DEFAULT_SENSITIVITY_SUMMARY_DIR))
    parser.add_argument("--stochastic-summary-csv", default=str(_DEFAULT_STOCHASTIC_SUMMARY))
    parser.add_argument("--ablation-summary-dir", default=str(_DEFAULT_ABLATION_SUMMARY_DIR))
    parser.add_argument("--subperiod-summary-csv", default=str(_DEFAULT_SUBPERIOD_SUMMARY))
    parser.add_argument(
        "--stochastic-acceptance-summary-csv",
        default=str(_DEFAULT_STOCHASTIC_ACCEPTANCE_SUMMARY),
    )
    parser.add_argument(
        "--stochastic-acceptance-status-csv",
        default=str(_DEFAULT_STOCHASTIC_ACCEPTANCE_STATUS),
    )
    parser.add_argument(
        "--stochastic-dashboard-csv",
        default=str(_DEFAULT_STOCHASTIC_DASHBOARD),
    )
    parser.add_argument("--output-root", default=str(_DEFAULT_OUTPUT_ROOT))
    return parser


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _load_sensitivity_summaries(summary_dir: Path) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for path in sorted(summary_dir.glob("deterministic_sensitivity_summary*.csv")):
        df = _read_csv_if_exists(path)
        if df.empty:
            continue
        df["source_file"] = path.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    rename_map = {
        "annualized_return": "return.annualized_return",
        "gross_annualized_return": "return.gross_annualized_return",
        "sharpe_ratio": "risk_adjusted.sharpe_ratio",
        "annualized_volatility": "risk.annualized_volatility",
        "max_drawdown": "risk.max_drawdown",
        "avg_monthly_turnover": "portfolio.avg_monthly_recorded_turnover",
        "annualized_turnover_ratio": "portfolio.annualized_turnover_ratio",
        "report_dir": "report_output_dir",
    }
    merged = merged.rename(columns={k: v for k, v in rename_map.items() if k in merged.columns})
    if merged.columns.duplicated().any():
        deduped: Dict[str, pd.Series] = {}
        for column_name in pd.unique(merged.columns):
            subset = merged.loc[:, merged.columns == column_name]
            if isinstance(subset, pd.Series):
                deduped[column_name] = subset
            else:
                deduped[column_name] = subset.bfill(axis=1).iloc[:, 0]
        merged = pd.DataFrame(deduped)
    for column in ("test_key", "scenario_key", "run_id"):
        if column not in merged.columns:
            raise ValueError(f"missing expected column in sensitivity summaries: {column}")
    merged["test_key"] = pd.to_numeric(merged["test_key"], errors="coerce").astype("Int64")
    merged = merged.sort_values(["test_key", "scenario_key", "source_file"])
    merged = merged.drop_duplicates(subset=["test_key", "scenario_key"], keep="last")
    return merged.reset_index(drop=True)


def _load_ablation_summaries(summary_dir: Path) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for path in sorted(summary_dir.glob("ablation_summary*.csv")):
        df = _read_csv_if_exists(path)
        if df.empty:
            continue
        df["source_file"] = path.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    return merged.drop_duplicates(subset=["block_key", "scenario_key"], keep="last").reset_index(
        drop=True
    )


def _fetch_table(
    run_id: str,
    sql: str,
    params: Optional[Mapping[str, Any]] = None,
) -> pd.DataFrame:
    engine = get_db_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"run_id": run_id, **(params or {})})


def _load_backtest_metrics(run_id: str) -> pd.DataFrame:
    df = _fetch_table(
        run_id,
        f"""
        SELECT metric_group, metric_name, metric_value
        FROM {_SCHEMA}.backtest_metrics
        WHERE run_id = :run_id
        ORDER BY metric_group, metric_name
        """,
    )
    if df.empty:
        return df
    df["metric_value"] = pd.to_numeric(df["metric_value"], errors="coerce")
    return df


def _load_relative_metrics(run_id: str) -> pd.DataFrame:
    df = _fetch_table(
        run_id,
        f"""
        SELECT versus_series, metric_name, metric_value, metric_unit
        FROM {_SCHEMA}.backtest_relative_metrics
        WHERE run_id = :run_id
        ORDER BY versus_series, metric_name
        """,
    )
    if df.empty:
        return df
    df["metric_value"] = pd.to_numeric(df["metric_value"], errors="coerce")
    return df


def _load_regime_attribution(run_id: str) -> pd.DataFrame:
    df = _fetch_table(
        run_id,
        f"""
        SELECT regime, versus_series, n_periods,
               strategy_ann_return, versus_ann_return, excess_ann_return,
               strategy_ann_vol, versus_ann_vol, strategy_sharpe, versus_sharpe,
               strategy_max_dd, versus_max_dd, hit_rate
        FROM {_SCHEMA}.backtest_regime_attribution
        WHERE run_id = :run_id
        ORDER BY CASE regime WHEN 'normal' THEN 1 WHEN 'stress' THEN 2 ELSE 3 END,
                 versus_series
        """,
    )
    return df


def _load_scorecard(run_id: str) -> pd.DataFrame:
    df = _fetch_table(
        run_id,
        f"""
        SELECT criterion_id, criterion_name, passed, evidence
        FROM {_SCHEMA}.backtest_scorecard
        WHERE run_id = :run_id
        ORDER BY criterion_id
        """,
    )
    return df


def _apply_cost_scorecard_from_deterministic(
    scorecard_df: pd.DataFrame,
    deterministic_df: pd.DataFrame,
) -> pd.DataFrame:
    if scorecard_df.empty or deterministic_df.empty:
        return scorecard_df
    cost_25 = deterministic_df[deterministic_df["scenario_key"].eq("cost_25bps")]
    if cost_25.empty:
        return scorecard_df
    row = cost_25.iloc[0]
    # The final report treats SPY as the investor-facing primary baseline.
    # Universe EW remains useful as an internal same-universe comparator, but
    # criterion 4 should not silently score the cost test against the wrong
    # benchmark when SPY metrics are available.
    primary_label = "SPY" if "SPY.excess_return_annualized" in row.index else "universe_ew"
    excess = pd.to_numeric(row.get(f"{primary_label}.excess_return_annualized"), errors="coerce")
    if pd.isna(excess):
        return scorecard_df
    universe_excess = pd.to_numeric(
        row.get("universe_ew.excess_return_annualized"), errors="coerce"
    )
    supporting = (
        f", 'supporting_excess_return_annualized_vs_universe_ew_pct': {float(universe_excess):.6f}"
        if primary_label == "SPY" and not pd.isna(universe_excess)
        else ""
    )
    updated = scorecard_df.copy()
    mask = updated["criterion_id"].astype(str).eq("4")
    if not mask.any():
        return updated
    updated.loc[mask, "passed"] = bool(float(excess) > 0.0)
    updated.loc[mask, "evidence"] = (
        "{"
        f"'threshold': 0.0, "
        f"'scenario_key': 'cost_25bps', "
        f"'primary_benchmark': '{primary_label}', "
        f"'excess_return_annualized_vs_primary_pct': {float(excess):.6f}, "
        f"'annualized_return_pct': {float(row.get('return.annualized_return')):.6f}, "
        f"'sharpe_ratio': {float(row.get('risk_adjusted.sharpe_ratio')):.6f}"
        f"{supporting}"
        "}"
    )
    return updated


def _build_completion_matrix(deterministic_df: pd.DataFrame) -> pd.DataFrame:
    expected = pd.DataFrame({"test_key": list(range(1, 9))})
    if deterministic_df.empty:
        expected["scenario_count"] = 0
        expected["completed"] = False
        return expected
    counts = (
        deterministic_df.groupby("test_key")["scenario_key"]
        .nunique()
        .rename("scenario_count")
        .reset_index()
    )
    out = expected.merge(counts, on="test_key", how="left").fillna({"scenario_count": 0})
    out["scenario_count"] = out["scenario_count"].astype(int)
    out["completed"] = out["scenario_count"] > 0
    return out


def _build_requirement_status_matrix(
    completion_df: pd.DataFrame,
    scorecard_df: pd.DataFrame,
    ablation_df: pd.DataFrame,
    subperiod_df: pd.DataFrame,
    stochastic_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for row in completion_df.to_dict(orient="records"):
        rows.append(
            {
                "category": "deterministic",
                "item_key": f"test_{int(row['test_key'])}",
                "label": f"Deterministic Test {int(row['test_key'])}",
                "status": "completed" if bool(row["completed"]) else "pending",
                "detail": f"scenario_count={int(row['scenario_count'])}",
            }
        )
    for row in scorecard_df.to_dict(orient="records"):
        passed = row.get("passed")
        if pd.isna(passed):
            status = "skipped"
        else:
            status = "pass" if bool(passed) else "fail"
        rows.append(
            {
                "category": "scorecard",
                "item_key": f"criterion_{int(row['criterion_id'])}",
                "label": str(row["criterion_name"]),
                "status": status,
                "detail": str(row.get("evidence")),
            }
        )
    if not ablation_df.empty:
        for row in ablation_df.to_dict(orient="records"):
            rows.append(
                {
                    "category": "ablation",
                    "item_key": f"{row.get('block_key')}::{row.get('scenario_key')}",
                    "label": f"Ablation {row.get('block_key')} {row.get('scenario_key')}",
                    "status": "completed",
                    "detail": (
                        f"ann_return={row.get('return.annualized_return')}, "
                        f"sharpe={row.get('risk_adjusted.sharpe_ratio')}"
                    ),
                }
            )
    if not subperiod_df.empty:
        for row in subperiod_df.to_dict(orient="records"):
            rows.append(
                {
                    "category": "subperiod",
                    "item_key": f"{row.get('window_key')}::{row.get('versus_series')}",
                    "label": f"{row.get('window_label')} vs {row.get('versus_series')}",
                    "status": "completed" if int(row.get("n_periods") or 0) > 0 else "unavailable",
                    "detail": f"n_periods={int(row.get('n_periods') or 0)}",
                }
            )
    if not stochastic_df.empty:
        for row in stochastic_df.to_dict(orient="records"):
            rows.append(
                {
                    "category": "stochastic",
                    "item_key": f"{row['method']}::{row['scenario_key']}",
                    "label": f"{row['method']} {row['scenario_key']}",
                    "status": str(row.get("classification") or "reported"),
                    "detail": (
                        f"p50_ann_return={row.get('annualized_return_p50')}, "
                        f"p50_sharpe={row.get('sharpe_p50')}, "
                        f"positive_return_prob={row.get('positive_return_probability')}"
                    ),
                }
            )
    return pd.DataFrame(rows)


def _status_from_rows(
    df: pd.DataFrame,
    *,
    matcher: callable,
    empty_status: str = "pending",
) -> str:
    if df.empty:
        return empty_status
    subset = df[df.apply(matcher, axis=1)].copy()
    if subset.empty:
        return empty_status
    statuses = {
        str(value)
        for value in subset.get("implementation_status", subset.get("status", pd.Series(dtype=str)))
        .dropna()
        .tolist()
    }
    if not statuses:
        return "completed"
    if statuses == {"completed"}:
        return "completed"
    if any("code_equivalent" in status for status in statuses):
        return "completed_code_equivalent"
    if any("partial" in status for status in statuses):
        return "partial"
    return ",".join(sorted(statuses))


def _build_acceptance_matrix(
    completion_df: pd.DataFrame,
    ablation_df: pd.DataFrame,
    subperiod_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    stochastic_acceptance_df: pd.DataFrame,
    stochastic_dashboard_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for test_key in range(1, 9):
        match = completion_df[completion_df["test_key"] == test_key]
        scenario_count = 0 if match.empty else int(match["scenario_count"].iloc[0])
        status = "completed" if scenario_count > 0 else "pending"
        rows.append(
            {
                "requirement_group": "Part 1 Deterministic",
                "item_key": f"test_{test_key}",
                "label": f"Deterministic Test {test_key}",
                "status": status,
                "detail": f"scenario_count={scenario_count}",
            }
        )

    for block_key in ("A", "B", "C"):
        subset = (
            ablation_df[ablation_df["block_key"] == block_key]
            if not ablation_df.empty
            else pd.DataFrame()
        )
        rows.append(
            {
                "requirement_group": "Part 2 Ablation",
                "item_key": f"ablation_{block_key.lower()}",
                "label": f"Ablation Block {block_key}",
                "status": "completed" if not subset.empty else "pending",
                "detail": f"scenario_count={int(len(subset))}",
            }
        )

    fixed_windows = (
        subperiod_df[subperiod_df.get("window_label", pd.Series(dtype=str)).notna()]
        if not subperiod_df.empty
        else pd.DataFrame()
    )
    unavailable_count = (
        int((fixed_windows.get("n_periods", pd.Series(dtype=float)).fillna(0) <= 0).sum())
        if not fixed_windows.empty
        else 0
    )
    fixed_window_status = "completed"
    if unavailable_count > 0:
        fixed_window_status = "partial_code_baseline"
    rows.append(
        {
            "requirement_group": "Part 3 Subperiod",
            "item_key": "fixed_subperiod_windows",
            "label": "Fixed Window Subperiod Tables",
            "status": fixed_window_status,
            "detail": f"rows={int(len(fixed_windows))}; unavailable_rows={unavailable_count}",
        }
    )
    rows.append(
        {
            "requirement_group": "Part 3 Subperiod",
            "item_key": "regime_decomposition",
            "label": "Normal / Stress / All Regime Decomposition",
            "status": "completed" if not regime_df.empty else "pending",
            "detail": f"rows={int(len(regime_df))}",
        }
    )

    for test_key in ("test_9", "test_10", "test_11", "test_12", "test_13"):
        status = _status_from_rows(
            stochastic_acceptance_df,
            matcher=lambda row, tk=test_key: str(row.get("test_key")) == tk,
        )
        detail_subset = (
            stochastic_acceptance_df[
                stochastic_acceptance_df.get("test_key", pd.Series(dtype=str)) == test_key
            ]
            if not stochastic_acceptance_df.empty
            else pd.DataFrame()
        )
        path_count = (
            int(pd.to_numeric(detail_subset.get("path_count"), errors="coerce").fillna(0).max())
            if not detail_subset.empty and "path_count" in detail_subset.columns
            else 0
        )
        rows.append(
            {
                "requirement_group": "Part 4 Stochastic",
                "item_key": test_key,
                "label": test_key.replace("_", " ").title(),
                "status": status,
                "detail": f"scenario_count={int(len(detail_subset))}; path_count_max={path_count}",
            }
        )

    rows.append(
        {
            "requirement_group": "Part 5 Packaging",
            "item_key": "tables_and_conclusions",
            "label": "Per-test tables and conclusion paragraphs",
            "status": "completed" if not stochastic_acceptance_df.empty else "pending",
            "detail": f"acceptance_rows={int(len(stochastic_acceptance_df))}",
        }
    )
    rows.append(
        {
            "requirement_group": "Part 5 Packaging",
            "item_key": "robustness_dashboard",
            "label": "Comprehensive robustness dashboard",
            "status": "completed" if not stochastic_dashboard_df.empty else "pending",
            "detail": f"dashboard_rows={int(len(stochastic_dashboard_df))}",
        }
    )
    return pd.DataFrame(rows)


def _build_stochastic_focus_tables(
    stochastic_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if stochastic_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    core = stochastic_df[stochastic_df["classification"].isin(["core", "stress_only"])].copy()
    auxiliary = stochastic_df[stochastic_df["classification"] == "auxiliary"].copy()
    return core.reset_index(drop=True), auxiliary.reset_index(drop=True)


def _format_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.3f}%"


def _format_num(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):.3f}"


def _first_non_null(*values: Any) -> Any:
    for value in values:
        if value is not None and not pd.isna(value):
            return value
    return None


def _topline_markdown(
    run_id: str,
    deterministic_df: pd.DataFrame,
    ablation_df: pd.DataFrame,
    subperiod_df: pd.DataFrame,
    stochastic_df: pd.DataFrame,
    stochastic_acceptance_df: pd.DataFrame,
    acceptance_matrix_df: pd.DataFrame,
    completion_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    scorecard_df: pd.DataFrame,
) -> str:
    lines = [
        "# Robustness Requirement Report",
        "",
        f"- Main run id: `{run_id}`",
        "- Formal baseline: `cw2_formal_20260420_fund_ra3_s30_t50`.",
        "- Cadence: quarterly target generation and quarterly execution; monthly rows are holding-period performance records.",
        "- Exclusion: the 2026-04-24 report is not used because it predates the PIT fix and formal parameter selection.",
        f"- Deterministic tests completed: {int(completion_df['completed'].sum())} / {len(completion_df)}",
        f"- Stochastic scenarios captured: {0 if stochastic_df.empty else len(stochastic_df)}",
        "",
        "## Deterministic Completion",
        "",
        "| Test | Scenario Count | Completed |",
        "|---|---:|---|",
    ]
    for row in completion_df.to_dict(orient="records"):
        lines.append(
            f"| {int(row['test_key'])} | {int(row['scenario_count'])} | {'Yes' if bool(row['completed']) else 'No'} |"
        )

    if not regime_df.empty:
        lines.extend(
            [
                "",
                "## Stress / Normal / All",
                "",
                "| Regime | Versus | Ann Return | Versus Return | Excess | Strategy Sharpe | Max DD | Hit Rate |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in regime_df.to_dict(orient="records"):
            lines.append(
                "| {regime} | {versus_series} | {strategy_ann_return} | {versus_ann_return} | {excess_ann_return} | {strategy_sharpe} | {strategy_max_dd} | {hit_rate} |".format(
                    regime=row.get("regime"),
                    versus_series=row.get("versus_series"),
                    strategy_ann_return=_format_pct(row.get("strategy_ann_return")),
                    versus_ann_return=_format_pct(row.get("versus_ann_return")),
                    excess_ann_return=_format_pct(row.get("excess_ann_return")),
                    strategy_sharpe=_format_num(row.get("strategy_sharpe")),
                    strategy_max_dd=_format_pct(row.get("strategy_max_dd")),
                    hit_rate=_format_pct(row.get("hit_rate")),
                )
            )

    if not scorecard_df.empty:
        lines.extend(
            [
                "",
                "## Scorecard",
                "",
                "| Criterion | Passed |",
                "|---|---|",
            ]
        )
        for row in scorecard_df.to_dict(orient="records"):
            passed = row.get("passed")
            label = "Skipped" if pd.isna(passed) else ("Pass" if bool(passed) else "Fail")
            lines.append(f"| {int(row['criterion_id'])}. {row['criterion_name']} | {label} |")

    if not stochastic_df.empty:
        lines.extend(
            [
                "",
                "## Stochastic",
                "",
                "| Method | Scenario | Class | P50 Ann Return | P50 Sharpe | P50 Max DD | Positive Return Prob |",
                "|---|---|---|---:|---:|---:|---:|",
            ]
        )
        for row in stochastic_df.to_dict(orient="records"):
            lines.append(
                "| {method} | {scenario_key} | {classification} | {annualized_return_p50} | {sharpe_p50} | {max_drawdown_p50} | {positive_return_probability} |".format(
                    method=row.get("method"),
                    scenario_key=row.get("scenario_key"),
                    classification=row.get("classification"),
                    annualized_return_p50=_format_pct(
                        None
                        if pd.isna(row.get("annualized_return_p50"))
                        else float(row.get("annualized_return_p50")) * 100.0
                    ),
                    sharpe_p50=_format_num(row.get("sharpe_p50")),
                    max_drawdown_p50=_format_pct(
                        None
                        if pd.isna(row.get("max_drawdown_p50"))
                        else float(row.get("max_drawdown_p50")) * 100.0
                    ),
                    positive_return_probability=_format_pct(
                        None
                        if pd.isna(row.get("positive_return_probability"))
                        else float(row.get("positive_return_probability")) * 100.0
                    ),
                )
            )

    if not stochastic_acceptance_df.empty:
        lines.extend(
            [
                "",
                "## Stochastic Acceptance",
                "",
                "| Test | Scenario | Status | P50 Ann Return / OOS Ann Return | P50 Sharpe / OOS Sharpe |",
                "|---|---|---|---:|---:|",
            ]
        )
        for row in stochastic_acceptance_df.to_dict(orient="records"):
            ann_return = _first_non_null(
                row.get("annualized_return_p50"), row.get("oos_annualized_return")
            )
            sharpe = _first_non_null(row.get("sharpe_p50"), row.get("oos_sharpe"))
            lines.append(
                "| {test_key} | {scenario_key} | {implementation_status} | {ann_return} | {sharpe} |".format(
                    test_key=row.get("test_key"),
                    scenario_key=row.get("scenario_key"),
                    implementation_status=row.get("implementation_status"),
                    ann_return=_format_pct(
                        None if pd.isna(ann_return) else float(ann_return) * 100.0
                    ),
                    sharpe=_format_num(sharpe),
                )
            )

    if not acceptance_matrix_df.empty:
        lines.extend(
            [
                "",
                "## Acceptance Matrix",
                "",
                "| Requirement Group | Item | Status | Detail |",
                "|---|---|---|---|",
            ]
        )
        for row in acceptance_matrix_df.to_dict(orient="records"):
            lines.append(
                f"| {row.get('requirement_group')} | {row.get('label')} | {row.get('status')} | {row.get('detail')} |"
            )

    if not subperiod_df.empty:
        lines.extend(
            [
                "",
                "## Fixed Sub-Periods",
                "",
                "Code-aligned coverage note: rows with `N Periods = 0` are unavailable because the current baseline series begins after those requested windows, not because the analysis was skipped.",
                "",
                "| Window | Versus | N Periods | Strategy Ann Return | Sharpe | Max DD | Excess Ann Return |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in subperiod_df.to_dict(orient="records"):
            lines.append(
                "| {window_label} | {versus_series} | {n_periods} | {strategy_ann_return} | {strategy_sharpe} | {strategy_max_drawdown} | {excess_ann_return} |".format(
                    window_label=row.get("window_label"),
                    versus_series=row.get("versus_series"),
                    n_periods=int(row.get("n_periods") or 0),
                    strategy_ann_return=_format_pct(
                        None
                        if pd.isna(row.get("strategy_ann_return"))
                        else float(row.get("strategy_ann_return")) * 100.0
                    ),
                    strategy_sharpe=_format_num(row.get("strategy_sharpe")),
                    strategy_max_drawdown=_format_pct(
                        None
                        if pd.isna(row.get("strategy_max_drawdown"))
                        else float(row.get("strategy_max_drawdown")) * 100.0
                    ),
                    excess_ann_return=_format_pct(
                        None
                        if pd.isna(row.get("excess_ann_return"))
                        else float(row.get("excess_ann_return")) * 100.0
                    ),
                )
            )

    if not ablation_df.empty:
        lines.extend(
            [
                "",
                "## Ablation",
                "",
                "| Block | Scenario | Ann Return | Sharpe | Max DD | Avg Monthly Recorded Turnover |",
                "|---|---|---:|---:|---:|---:|",
            ]
        )
        for row in ablation_df.to_dict(orient="records"):
            lines.append(
                "| {block_key} | {scenario_key} | {ann_return} | {sharpe} | {max_dd} | {turnover} |".format(
                    block_key=row.get("block_key"),
                    scenario_key=row.get("scenario_key"),
                    ann_return=_format_pct(row.get("return.annualized_return")),
                    sharpe=_format_num(row.get("risk_adjusted.sharpe_ratio")),
                    max_dd=_format_pct(row.get("risk.max_drawdown")),
                    turnover=_format_pct(row.get("portfolio.avg_monthly_recorded_turnover")),
                )
            )

    if not deterministic_df.empty:
        lines.extend(
            [
                "",
                "## Deterministic Detail",
                "",
                "| Test | Scenario | Ann Return | Sharpe | Max DD | Source |",
                "|---|---|---:|---:|---:|---|",
            ]
        )
        for row in deterministic_df.sort_values(["test_key", "scenario_key"]).to_dict(
            orient="records"
        ):
            lines.append(
                "| {test_key} | {scenario_key} | {ann_return} | {sharpe} | {max_dd} | {source_file} |".format(
                    test_key=int(row["test_key"]),
                    scenario_key=row.get("scenario_key"),
                    ann_return=_format_pct(row.get("return.annualized_return")),
                    sharpe=_format_num(row.get("risk_adjusted.sharpe_ratio")),
                    max_dd=_format_pct(row.get("risk.max_drawdown")),
                    source_file=row.get("source_file", ""),
                )
            )

    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_env_layers()

    run_id = str(args.run_id)
    summary_dir = Path(str(args.sensitivity_summary_dir)).resolve()
    stochastic_path = Path(str(args.stochastic_summary_csv)).resolve()
    ablation_summary_dir = Path(str(args.ablation_summary_dir)).resolve()
    subperiod_summary_path = Path(str(args.subperiod_summary_csv)).resolve()
    stochastic_acceptance_summary_path = Path(str(args.stochastic_acceptance_summary_csv)).resolve()
    stochastic_acceptance_status_path = Path(str(args.stochastic_acceptance_status_csv)).resolve()
    stochastic_dashboard_path = Path(str(args.stochastic_dashboard_csv)).resolve()
    output_root = Path(str(args.output_root)).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    deterministic_df = _load_sensitivity_summaries(summary_dir)
    ablation_df = _load_ablation_summaries(ablation_summary_dir)
    subperiod_df = _read_csv_if_exists(subperiod_summary_path)
    stochastic_df = _read_csv_if_exists(stochastic_path)
    stochastic_acceptance_df = _read_csv_if_exists(stochastic_acceptance_summary_path)
    stochastic_acceptance_status_df = _read_csv_if_exists(stochastic_acceptance_status_path)
    stochastic_dashboard_df = _read_csv_if_exists(stochastic_dashboard_path)
    metrics_df = _load_backtest_metrics(run_id)
    relative_df = _load_relative_metrics(run_id)
    regime_df = _load_regime_attribution(run_id)
    scorecard_df = _load_scorecard(run_id)
    scorecard_df = _apply_cost_scorecard_from_deterministic(scorecard_df, deterministic_df)
    completion_df = _build_completion_matrix(deterministic_df)
    status_matrix_df = _build_requirement_status_matrix(
        completion_df=completion_df,
        scorecard_df=scorecard_df,
        ablation_df=ablation_df,
        subperiod_df=subperiod_df,
        stochastic_df=stochastic_df,
    )
    acceptance_matrix_df = _build_acceptance_matrix(
        completion_df=completion_df,
        ablation_df=ablation_df,
        subperiod_df=subperiod_df,
        regime_df=regime_df,
        stochastic_acceptance_df=stochastic_acceptance_df,
        stochastic_dashboard_df=stochastic_dashboard_df,
    )
    stochastic_core_df, stochastic_aux_df = _build_stochastic_focus_tables(stochastic_df)

    deterministic_df.to_csv(
        output_root / "deterministic_master.csv", index=False, encoding="utf-8-sig"
    )
    ablation_df.to_csv(output_root / "ablation_master.csv", index=False, encoding="utf-8-sig")
    subperiod_df.to_csv(output_root / "subperiod_master.csv", index=False, encoding="utf-8-sig")
    completion_df.to_csv(
        output_root / "deterministic_completion_matrix.csv", index=False, encoding="utf-8-sig"
    )
    status_matrix_df.to_csv(
        output_root / "requirement_status_matrix.csv", index=False, encoding="utf-8-sig"
    )
    acceptance_matrix_df.to_csv(
        output_root / "acceptance_matrix.csv", index=False, encoding="utf-8-sig"
    )
    metrics_df.to_csv(output_root / "baseline_metrics.csv", index=False, encoding="utf-8-sig")
    relative_df.to_csv(
        output_root / "baseline_relative_metrics.csv", index=False, encoding="utf-8-sig"
    )
    regime_df.to_csv(
        output_root / "baseline_regime_subperiod.csv", index=False, encoding="utf-8-sig"
    )
    scorecard_df.to_csv(output_root / "baseline_scorecard.csv", index=False, encoding="utf-8-sig")
    if not stochastic_df.empty:
        stochastic_df.to_csv(
            output_root / "stochastic_summary.csv", index=False, encoding="utf-8-sig"
        )
        stochastic_core_df.to_csv(
            output_root / "stochastic_core_and_stress.csv", index=False, encoding="utf-8-sig"
        )
        stochastic_aux_df.to_csv(
            output_root / "stochastic_auxiliary_local_perturbation.csv",
            index=False,
            encoding="utf-8-sig",
        )
    if not stochastic_acceptance_df.empty:
        stochastic_acceptance_df.to_csv(
            output_root / "stochastic_acceptance_summary.csv", index=False, encoding="utf-8-sig"
        )
    if not stochastic_acceptance_status_df.empty:
        stochastic_acceptance_status_df.to_csv(
            output_root / "stochastic_acceptance_status.csv", index=False, encoding="utf-8-sig"
        )
    if not stochastic_dashboard_df.empty:
        stochastic_dashboard_df.to_csv(
            output_root / "stochastic_dashboard.csv", index=False, encoding="utf-8-sig"
        )

    markdown = _topline_markdown(
        run_id=run_id,
        deterministic_df=deterministic_df,
        ablation_df=ablation_df,
        subperiod_df=subperiod_df,
        stochastic_df=stochastic_df,
        stochastic_acceptance_df=stochastic_acceptance_df,
        acceptance_matrix_df=acceptance_matrix_df,
        completion_df=completion_df,
        regime_df=regime_df,
        scorecard_df=scorecard_df,
    )
    (output_root / "robustness_requirement_report.md").write_text(markdown, encoding="utf-8")
    (output_root / "robustness_requirement_report.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "deterministic_rows": int(len(deterministic_df)),
                "deterministic_completed_tests": int(completion_df["completed"].sum()),
                "ablation_rows": int(len(ablation_df)),
                "subperiod_rows": int(len(subperiod_df)),
                "stochastic_rows": int(len(stochastic_df)),
                "scorecard_rows": int(len(scorecard_df)),
                "status_matrix_rows": int(len(status_matrix_df)),
                "acceptance_matrix_rows": int(len(acceptance_matrix_df)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    persistence_result: Dict[str, Any]
    try:
        persistence_result = persist_robustness_outputs(
            engine=get_db_engine(),
            report_name=f"cw2_robustness_outputs_{run_id}",
            output_root=output_root.parent,
            source_run_id=run_id,
        )
    except Exception:
        persistence_result = {"ok": False, "error": "robustness_persistence_failed"}

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "output_root": str(output_root),
                "completed_tests": int(completion_df["completed"].sum()),
                "deterministic_rows": int(len(deterministic_df)),
                "ablation_rows": int(len(ablation_df)),
                "subperiod_rows": int(len(subperiod_df)),
                "stochastic_rows": int(len(stochastic_df)),
                "acceptance_rows": int(len(acceptance_matrix_df)),
                "robustness_persistence": persistence_result,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
