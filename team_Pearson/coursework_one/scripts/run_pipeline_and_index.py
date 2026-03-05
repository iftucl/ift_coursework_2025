from __future__ import annotations

"""Pipeline orchestrator: run Main.py (which owns optional Mongo indexing)."""

import argparse
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import List

from modules.utils.args_parser import ALLOWED_FREQUENCIES, valid_date
from modules.utils.env import load_dotenv_if_exists


def _build_main_cmd(args: argparse.Namespace, project_root: Path) -> List[str]:
    """Build Main.py command from orchestrator arguments."""
    cmd = [
        sys.executable,
        str((project_root / "Main.py").resolve()),
        "--run-date",
        args.run_date,
        "--frequency",
        args.frequency,
    ]
    if args.config:
        cmd.extend(["--config", args.config])
    if args.backfill_years is not None:
        cmd.extend(["--backfill-years", str(args.backfill_years)])
    if args.company_limit is not None:
        cmd.extend(["--company-limit", str(args.company_limit)])
    if args.enabled_extractors:
        cmd.extend(["--enabled-extractors", args.enabled_extractors])
    if args.dry_run:
        cmd.append("--dry-run")
    if args.index_mongo:
        cmd.append("--index-mongo")
    else:
        cmd.append("--no-index-mongo")
    return cmd


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI parser for pipeline + optional Mongo indexing."""
    parser = argparse.ArgumentParser(
        description=(
            "Run Main.py pipeline wrapper. Main.py itself controls optional Mongo "
            "indexing (default enabled)."
        )
    )
    parser.add_argument("--run-date", required=True, type=valid_date, help="YYYY-MM-DD")
    parser.add_argument("--frequency", required=True, choices=sorted(ALLOWED_FREQUENCIES))
    parser.add_argument("--config", default="config/conf.yaml")
    parser.add_argument("--backfill-years", type=int, default=None)
    parser.add_argument("--company-limit", type=int, default=None)
    parser.add_argument("--enabled-extractors", default="")
    parser.add_argument("--dry-run", action="store_true")

    parser.add_argument(
        "--index-mongo",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pass through to Main.py to control Mongo indexing (default: enabled).",
    )
    return parser


def main() -> int:
    """Run main pipeline once; Mongo stage is handled inside Main.py."""
    args = build_parser().parse_args()
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv_if_exists(project_root / ".env")

    main_cmd = _build_main_cmd(args, project_root)
    print("[orchestrator] main command: " + " ".join(main_cmd))
    # Safe: validated argparse values + fixed Main.py path; shell not used.
    main_result = subprocess.run(
        main_cmd,
        check=False,
    )  # nosec B603
    if main_result.returncode != 0:
        print(f"[orchestrator] main failed rc={main_result.returncode}")
        return int(main_result.returncode)

    if args.index_mongo:
        print("[orchestrator] mongo indexing handled by Main.py (--index-mongo)")
    else:
        print("[orchestrator] mongo indexing disabled via Main.py (--no-index-mongo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
