from __future__ import annotations

"""Scheduler-safe wrapper for the CW2 operate flow."""

import argparse
import os
import subprocess  # nosec B404
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    CW2_ROOT,
    coerce_optional_int,
    default_cw1_config,
    default_cw2_config,
    is_rebalance_trading_day,
    load_env_layers,
    print_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CW2 operate flow under scheduler control."
    )
    parser.add_argument("--run-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=default_cw2_config())
    parser.add_argument("--company-limit", default=None)
    parser.add_argument("--recommendation-name", default=None)
    parser.add_argument("--briefing-dir", default=None)
    parser.add_argument("--decision-actor", default="airflow_cw2")
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--auto-publish", action="store_true")
    parser.add_argument(
        "--require-rebalance-anchor",
        dest="require_rebalance_anchor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip successfully when run_date is not the configured trading rebalance anchor.",
    )
    parser.add_argument(
        "--require-month-end",
        dest="require_rebalance_anchor",
        action=argparse.BooleanOptionalAction,
        help=argparse.SUPPRESS,
    )
    return parser


def _build_main_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str((CW2_ROOT / "Main.py").resolve()),
        "--mode",
        "operate",
        "--run-date",
        str(args.run_date),
        "--cw1-config",
        str(args.cw1_config),
        "--cw2-config",
        str(args.cw2_config),
        "--decision-actor",
        str(args.decision_actor),
    ]
    company_limit = coerce_optional_int(args.company_limit)
    if company_limit is not None:
        cmd.extend(["--company-limit", str(company_limit)])
    if args.recommendation_name:
        cmd.extend(["--recommendation-name", str(args.recommendation_name)])
    if args.briefing_dir:
        cmd.extend(["--briefing-dir", str(args.briefing_dir)])
    if args.auto_approve:
        cmd.append("--auto-approve")
    if args.auto_publish:
        cmd.append("--auto-publish")
    return cmd


def main() -> int:
    args = build_parser().parse_args()
    load_env_layers()
    run_date = date.fromisoformat(str(args.run_date))
    if args.require_rebalance_anchor and not is_rebalance_trading_day(
        run_date=run_date,
        cw2_config_path=str(args.cw2_config),
    ):
        print_json(
            {
                "status": "skipped",
                "reason": "run_date is not the configured trading rebalance anchor",
                "run_date": run_date.isoformat(),
            }
        )
        return 0

    cmd = _build_main_cmd(args)
    env = os.environ.copy()
    completed = subprocess.run(cmd, cwd=str(CW2_ROOT), env=env, check=False)  # nosec B603
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
