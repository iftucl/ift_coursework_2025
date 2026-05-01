#!/usr/bin/env python3
"""Score development-period constrained-search candidates from report summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def _load_summary(report_name: str) -> dict[str, Any] | None:
    path = Path("team_Pearson/coursework_two/outputs/reports") / report_name / "report_summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _passes(summary: dict[str, Any], constraints: dict[str, float]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if summary.get("annualized_return", float("-inf")) < constraints["min_annualized_return"]:
        failures.append("annualized_return")
    if (
        summary.get("information_ratio_vs_primary", float("-inf"))
        < constraints["min_information_ratio_vs_primary"]
    ):
        failures.append("information_ratio_vs_primary")
    if summary.get("max_drawdown", float("inf")) > constraints["max_max_drawdown"]:
        failures.append("max_drawdown")
    beta = summary.get("beta_raw")
    if beta is None or beta < constraints["min_beta_raw"] or beta > constraints["max_beta_raw"]:
        failures.append("beta_raw")
    if (
        summary.get("avg_monthly_turnover_one_way", float("inf"))
        > constraints["max_avg_monthly_turnover_one_way"]
    ):
        failures.append("avg_monthly_turnover_one_way")
    if summary.get("scorecard_passed", float("-inf")) < constraints["min_scorecard_passed"]:
        failures.append("scorecard_passed")
    return (len(failures) == 0, failures)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    manifest = yaml.safe_load(args.manifest.read_text())
    constraints = manifest["constraints"]
    scored: list[dict[str, Any]] = []

    for candidate in manifest.get("candidates", []):
        report_name = candidate["report_name"]
        summary = _load_summary(report_name)
        if summary is None:
            scored.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "status": "pending",
                    "report_name": report_name,
                }
            )
            continue
        passed, failures = _passes(summary, constraints)
        scored.append(
            {
                "candidate_id": candidate["candidate_id"],
                "status": "eligible" if passed else "failed_constraints",
                "failures": failures,
                "run_id": summary.get("run_id"),
                "report_name": report_name,
                "sharpe_ratio": summary.get("sharpe_ratio"),
                "annualized_return": summary.get("annualized_return"),
                "max_drawdown": summary.get("max_drawdown"),
                "information_ratio_vs_primary": summary.get("information_ratio_vs_primary"),
                "beta_raw": summary.get("beta_raw"),
                "avg_monthly_turnover_one_way": summary.get("avg_monthly_turnover_one_way"),
                "scorecard_passed": summary.get("scorecard_passed"),
                "parameter_changes": candidate.get("parameter_changes", 0),
            }
        )

    ranked = sorted(
        [row for row in scored if row.get("status") == "eligible"],
        key=lambda row: (
            -(row.get("sharpe_ratio") or float("-inf")),
            row.get("max_drawdown") or float("inf"),
            -(row.get("information_ratio_vs_primary") or float("-inf")),
            row.get("avg_monthly_turnover_one_way") or float("inf"),
            row.get("parameter_changes") or float("inf"),
        ),
    )

    print(json.dumps({"scored": scored, "ranked_eligible": ranked}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
