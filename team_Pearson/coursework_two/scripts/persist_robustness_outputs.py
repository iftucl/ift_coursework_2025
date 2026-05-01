from __future__ import annotations

"""Persist current robustness outputs into PostgreSQL."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_two.modules.reporting.report import (  # noqa: E402
    _load_shared_db_engine,
)
from team_Pearson.coursework_two.modules.robustness.persistence import (  # noqa: E402
    persist_robustness_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persist robustness outputs into PostgreSQL.")
    parser.add_argument("--report-name", default="cw2_robustness_outputs")
    parser.add_argument(
        "--output-root",
        default=str(Path(__file__).resolve().parents[1] / "outputs" / "robustness"),
    )
    parser.add_argument("--source-run-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = _load_shared_db_engine()
    result = persist_robustness_outputs(
        engine=engine,
        report_name=str(args.report_name),
        output_root=str(args.output_root),
        source_run_id=str(args.source_run_id) if args.source_run_id else None,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
