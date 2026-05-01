from __future__ import annotations

"""Scheduler-safe wrapper for the CW2 daily update-decision flow."""

import argparse
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    CW2_ROOT,
    default_cw1_config,
    default_cw2_config,
    load_env_layers,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CW2 daily update decision under scheduler control."
    )
    parser.add_argument("--run-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=default_cw2_config())
    parser.add_argument("--with-upstream", action="store_true")
    return parser


def _build_main_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str((CW2_ROOT / "Main.py").resolve()),
        "--mode",
        "update-decision",
        "--run-date",
        str(args.run_date),
        "--cw1-config",
        str(args.cw1_config),
        "--cw2-config",
        str(args.cw2_config),
    ]
    if bool(args.with_upstream):
        cmd.append("--with-upstream")
    return cmd


def main() -> int:
    args = build_parser().parse_args()
    load_env_layers()
    cmd = _build_main_cmd(args)
    env = os.environ.copy()
    completed = subprocess.run(cmd, cwd=str(CW2_ROOT), env=env, check=False)  # nosec B603
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
