from __future__ import annotations

"""Build a single directly readable markdown file for the robustness report evidence pack."""

import argparse
from pathlib import Path
from typing import List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"
REPORT_EVIDENCE_ROOT = CW2_ROOT / "outputs" / "robustness" / "report_evidence"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a readable markdown overview for the report evidence pack."
    )
    parser.add_argument("--report-evidence-root", default=str(REPORT_EVIDENCE_ROOT))
    return parser


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _section_block(root: Path, title: str, file_specs: List[tuple[str, str]]) -> List[str]:
    lines = [f"## {title}", ""]
    for label, filename in file_specs:
        path = root / filename
        if path.exists():
            lines.append(f"- {label}: `{filename}`")
    lines.append("")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report_evidence_root = Path(str(args.report_evidence_root)).resolve()

    p1 = report_evidence_root / "part_1_deterministic"
    p2 = report_evidence_root / "part_2_ablation"
    p3 = report_evidence_root / "part_3_subperiod"
    p4 = report_evidence_root / "part_4_stochastic"
    p5 = report_evidence_root / "part_5_dashboard_and_conclusions"

    lines: List[str] = [
        "# Robustness Report Evidence Pack",
        "",
        "This is the directly readable overview for the report group.",
        "Use this file first, then open the linked tables / figures inside each part folder.",
        "",
        "## Formal Baseline And Cadence",
        "",
        "- Formal baseline: `cw2_formal_20260420_fund_ra3_s30_t50`.",
        "- Formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`.",
        "- Target-weight generation and actual rebalancing are both quarterly.",
        "- Performance rows, NAV, Sharpe, drawdown, IR, and turnover are measured monthly from the holding-period backtest.",
        "- Monthly monitoring / snapshot backfill is operational readiness evidence only; it is not monthly portfolio re-optimisation or monthly rebalancing.",
        "- Do not use the 2026-04-24 report as the robustness baseline because it predates the PIT fix and formal parameter selection.",
        "",
        "## Requirement Map",
        "",
        "### Part 1 - Deterministic Sensitivity",
        "",
        "- Test 1: Trading Cost Sensitivity. Checks whether strategy performance survives less optimistic execution-cost assumptions.",
        "- Test 2: Backtest Window Start Sensitivity. Checks whether results depend excessively on a particular sample start date.",
        "- Test 3: Concentration Sensitivity. Checks whether alpha depends on one specific portfolio breadth choice.",
        "- Test 4: Factor Weight Perturbation Sensitivity. Checks whether the normal-regime factor weights sit on an overfitted spike.",
        "- Test 5: Regime Threshold Sensitivity. Checks whether regime switching depends too strongly on one exact threshold choice.",
        "- Test 6: Drawdown Brake Sensitivity. Measures the return, drawdown, and turnover trade-off created by the drawdown brake design.",
        "- Test 7: Banded Selector Sensitivity. Measures the churn-versus-performance trade-off from different entry and exit band widths.",
        "- Test 8: No-Trade Band and Per-Name Cap Sensitivity. Measures how trade-size constraints suppress unnecessary surviving-name rebalancing.",
        "",
        "### Part 2 - Ablation Study",
        "",
        "- Ablation A: Factor Ablation. Removes one factor at a time to test its marginal contribution.",
        "- Ablation B: Mechanism Ablation. Removes one mechanism at a time to test whether it improves the strategy.",
        "- Ablation C: Optimizer Ablation. Replaces the main optimizer with simpler alternatives to test whether the optimizer adds risk-adjusted value.",
        "",
        "### Part 3 - Sub-Period Analysis",
        "",
        "- Sub-Period 1: Fixed Historical Windows. Compares performance across named market windows such as recovery, bear, and bull periods.",
        "- Sub-Period 2: Regime Decomposition. Splits performance into normal, stress, and all-period views.",
        "",
        "### Part 4 - Stochastic Robustness",
        "",
        "- Test 9: Stationary Block Bootstrap. Resamples the realized monthly return path while preserving short-range serial dependence.",
        "- Test 10: Monte Carlo Cost Perturbation. Randomizes execution costs to test whether net performance survives cost uncertainty.",
        "- Test 11: Bayesian / Dirichlet Weight Neighbourhood. Perturbs factor weights around the baseline normal-regime allocation to test local robustness.",
        "- Test 12: Rolling Out-of-Sample. Uses rolling estimation windows and one-step-forward evaluation to test out-of-sample decay.",
        "- Test 13: Monte Carlo Path Simulation. Simulates long-run return paths from the empirical return distribution fit.",
        "",
        "### Part 5 - Output Packaging",
        "",
        "- Per-test tables and conclusion paragraphs. Provides report-ready evidence for each block.",
        "- Comprehensive robustness dashboard. Provides the top-level acceptance and summary view across the whole robustness section.",
        "",
    ]
    lines.extend(
        _section_block(
            p1,
            "Part 1 Deterministic Sensitivity",
            [
                ("Index", "../REPORT_EVIDENCE_INDEX.md"),
                ("Test 1 notes", "test_01_notes.md"),
                ("Test 2 notes", "test_02_notes.md"),
                ("Test 3 notes", "test_03_notes.md"),
                ("Test 4 notes", "test_04_notes.md"),
                ("Test 5 notes", "test_05_notes.md"),
                ("Test 6 notes", "test_06_notes.md"),
                ("Test 7 notes", "test_07_notes.md"),
                ("Test 8 notes", "test_08_notes.md"),
            ],
        )
    )
    lines.extend(
        _section_block(
            p2,
            "Part 2 Ablation Study",
            [
                ("Ablation A notes", "ablation_block_a_notes.md"),
                ("Ablation B notes", "ablation_block_b_notes.md"),
                ("Ablation C notes", "ablation_block_c_notes.md"),
            ],
        )
    )
    lines.extend(
        _section_block(
            p3,
            "Part 3 Sub-Period Analysis",
            [
                ("Fixed windows notes", "subperiod_fixed_windows_notes.md"),
                ("Regime decomposition notes", "subperiod_regime_decomposition_notes.md"),
                ("Coverage note", "subperiod_coverage_note.md"),
            ],
        )
    )
    lines.extend(
        _section_block(
            p4,
            "Part 4 Stochastic Robustness",
            [
                ("Test 9 notes", "test_9_notes.md"),
                ("Test 10 notes", "test_10_notes.md"),
                ("Test 11 notes", "test_11_notes.md"),
                ("Test 11 report-ready summary", "test11_report_ready_summary.md"),
                ("Test 12 notes", "test_12_notes.md"),
                ("Test 13 notes", "test_13_notes.md"),
                ("General stochastic notes", "stochastic_report_ready_notes.md"),
            ],
        )
    )
    lines.extend(
        _section_block(
            p5,
            "Part 5 Dashboard and Conclusions",
            [
                ("Dashboard notes", "dashboard_notes.md"),
                ("Acceptance matrix", "acceptance_matrix.csv"),
                ("Stochastic dashboard", "stochastic_dashboard.csv"),
                ("Requirement report", "robustness_requirement_report.md"),
            ],
        )
    )

    embedded_files = [
        ("Part 1 - Test 1", p1 / "test_01_notes.md"),
        ("Part 1 - Test 4", p1 / "test_04_notes.md"),
        ("Part 2 - Ablation B", p2 / "ablation_block_b_notes.md"),
        ("Part 3 - Fixed windows", p3 / "subperiod_fixed_windows_notes.md"),
        ("Part 4 - Test 11", p4 / "test_11_notes.md"),
        ("Part 4 - Test 11 report-ready summary", p4 / "test11_report_ready_summary.md"),
        ("Part 4 - General stochastic notes", p4 / "stochastic_report_ready_notes.md"),
        ("Part 5 - Dashboard", p5 / "dashboard_notes.md"),
    ]
    for heading, path in embedded_files:
        content = _read(path).strip()
        if content:
            lines.extend([f"## {heading}", "", content, ""])

    output_path = report_evidence_root / "ROBUSTNESS_REPORT_EVIDENCE_PACK.md"
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
