from __future__ import annotations

"""Run the formal robustness suite using summary-only scenario reruns."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

CW2_ROOT = Path(__file__).resolve().parents[1]
TEAM_ROOT = CW2_ROOT.parent
REPO_ROOT = TEAM_ROOT.parent
CW1_ROOT = TEAM_ROOT / "coursework_one"
SCRIPTS = CW2_ROOT / "scripts"
LOG_ROOT = CW2_ROOT / "outputs" / "robustness" / "logs" / "formal_fast_6905_20260429"
STATUS_PATH = LOG_ROOT / "runner_status.json"
FORMAL_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"
TAG = "formal_fast_6905_20260429"
DEFAULT_PART2_BLOCKS = os.environ.get("FORMAL_FAST_PART2_BLOCKS", "B")
DEFAULT_TEST11_NEIGHBOURHOOD = os.environ.get("FORMAL_FAST_TEST11_NEIGHBOURHOOD", "core6")
PART1_RUN_PREFIX = "cw2_sensitivity_fast"
PART1_EXPECTED_SCENARIOS = 34


def _pydeps_path() -> Path:
    return REPO_ROOT.parents[1] / "_restore_workspace" / "pydeps"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or resume the formal fast robustness suite.")
    parser.add_argument(
        "--part2-blocks",
        default=DEFAULT_PART2_BLOCKS,
        help="Comma-separated ablation blocks for part2_ablation_fast. Defaults to B.",
    )
    parser.add_argument(
        "--test11-neighbourhood",
        choices=("core6", "full9"),
        default=DEFAULT_TEST11_NEIGHBOURHOOD,
        help="Test 11 factor-neighbourhood size. core6 uses 2/2/2; full9 uses 3/3/3.",
    )
    parser.add_argument(
        "--test11-counts",
        default="",
        help="Optional explicit loose,medium,tight counts, e.g. 2,2,2 or 3,3,3.",
    )
    parser.add_argument(
        "--start-at",
        default="",
        help="Optional step name to start from, e.g. part2_ablation_fast.",
    )
    parser.add_argument(
        "--wait-for-part1",
        action="store_true",
        help="Poll the database until part1 sensitivity has completed before running the selected start step.",
    )
    parser.add_argument(
        "--wait-poll-seconds",
        type=int,
        default=60,
        help="Polling interval for --wait-for-part1.",
    )
    parser.add_argument(
        "--wait-timeout-hours",
        type=float,
        default=12.0,
        help="Maximum time to wait for part1 completion before failing.",
    )
    parser.add_argument(
        "--expected-sensitivity-scenarios",
        type=int,
        default=PART1_EXPECTED_SCENARIOS,
        help="Expected unique completed sensitivity scenarios for part1.",
    )
    return parser


def _test11_counts(mode: str, explicit_counts: str = "") -> Tuple[int, int, int]:
    if str(explicit_counts).strip():
        parts = [part.strip() for part in str(explicit_counts).split(",")]
        if len(parts) != 3:
            raise ValueError("--test11-counts must be loose,medium,tight, e.g. 2,2,2")
        counts = tuple(int(part) for part in parts)
    elif str(mode) == "full9":
        counts = (3, 3, 3)
    else:
        counts = (2, 2, 2)
    if any(count < 0 for count in counts):
        raise ValueError("Test 11 counts must be non-negative integers")
    return counts


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _write_status(payload: Dict[str, Any]) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _append_runner_log(message: str) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    with (LOG_ROOT / "runner.log").open("a", encoding="utf-8") as handle:
        handle.write(f"[{_utc_now()}] {message}\n")


def _ensure_project_paths() -> None:
    for path in (str(_pydeps_path()), str(REPO_ROOT), str(CW1_ROOT)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


def _sensitivity_scenario_id(run_name: str) -> str:
    stem = str(run_name)
    prefix = f"{PART1_RUN_PREFIX}_"
    if stem.startswith(prefix):
        stem = stem[len(prefix) :]
    return re.sub(r"_\d{8}T\d{6}Z$", "", stem)


def _completed_sensitivity_scenario_count() -> int:
    _ensure_project_paths()
    from sqlalchemy import text
    from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine

    sql = text("""
        SELECT run_name
        FROM systematic_equity.backtest_runs
        WHERE run_name LIKE :run_prefix
          AND status = 'completed'
        """)
    engine = get_db_engine()
    with engine.connect() as conn:
        run_names = [
            str(row[0]) for row in conn.execute(sql, {"run_prefix": f"{PART1_RUN_PREFIX}_%"})
        ]
    return len({_sensitivity_scenario_id(name) for name in run_names})


def _wait_for_part1_completion(
    *,
    expected_count: int,
    poll_seconds: int,
    timeout_hours: float,
    status: Dict[str, Any],
) -> bool:
    deadline = time.time() + max(float(timeout_hours), 0.0) * 3600.0
    poll_interval = max(int(poll_seconds), 5)
    status["current_step"] = "waiting_for_part1_sensitivity_fast"
    status["wait_for_part1"] = {
        "expected_completed_unique": int(expected_count),
        "poll_seconds": poll_interval,
        "timeout_hours": float(timeout_hours),
        "started_at": _utc_now(),
    }
    _write_status(status)
    _append_runner_log(f"waiting for part1 sensitivity completion expected={expected_count}")

    while True:
        completed = _completed_sensitivity_scenario_count()
        status["wait_for_part1"]["completed_unique"] = completed
        status["wait_for_part1"]["updated_at"] = _utc_now()
        status["updated_at"] = _utc_now()
        _write_status(status)
        _append_runner_log(f"part1 sensitivity completed_unique={completed}/{expected_count}")
        if completed >= expected_count:
            status["wait_for_part1"]["finished_at"] = _utc_now()
            status["updated_at"] = _utc_now()
            _write_status(status)
            return True
        if time.time() >= deadline:
            status["wait_for_part1"]["timed_out_at"] = _utc_now()
            status["ok"] = False
            status["updated_at"] = _utc_now()
            _write_status(status)
            _append_runner_log("timed out waiting for part1 sensitivity completion")
            return False
        time.sleep(poll_interval)


def _base_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "MPLBACKEND": "Agg",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "5439",
            "POSTGRES_DB": "fift_formal_slim_6905_work",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
            "KAFKA_ENABLED": "false",
            "KAFKA_REQUIRED": "false",
        }
    )
    pydeps = str(_pydeps_path())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = pydeps if not existing else f"{pydeps}{os.pathsep}{existing}"
    return env


def _commands(
    part2_blocks: str = DEFAULT_PART2_BLOCKS,
    test11_counts: Tuple[int, int, int] = (2, 2, 2),
) -> List[Tuple[str, Sequence[str]]]:
    py = sys.executable
    loose_count, medium_count, tight_count = test11_counts
    return [
        (
            "part1_sensitivity_fast",
            [
                py,
                str(SCRIPTS / "run_sensitivity_analysis.py"),
                "--tests",
                "all",
                "--fast-summary-only",
                "--skip-existing-snapshots",
                "--summary-tag",
                TAG,
                "--run-prefix",
                "cw2_sensitivity_fast",
            ],
        ),
        (
            "part2_ablation_fast",
            [
                py,
                str(SCRIPTS / "run_ablation_analysis.py"),
                "--blocks",
                str(part2_blocks),
                "--fast-summary-only",
                "--skip-existing-snapshots",
                "--summary-tag",
                TAG,
                "--run-prefix",
                "cw2_ablation_fast",
            ],
        ),
        (
            "part3_subperiod",
            [
                py,
                str(SCRIPTS / "run_subperiod_analysis.py"),
                "--run-id",
                FORMAL_RUN_ID,
            ],
        ),
        (
            "part4_stochastic_paths",
            [
                py,
                str(SCRIPTS / "run_stochastic_robustness.py"),
                "--run-id",
                FORMAL_RUN_ID,
            ],
        ),
        (
            "part4_test11_factor_neighbourhood_fast",
            [
                py,
                str(SCRIPTS / "run_test11_factor_neighbourhood.py"),
                "--fast-summary-only",
                "--skip-existing-snapshots",
                "--summary-tag",
                TAG,
                "--run-prefix",
                "cw2_test11_factor_nbhd_fast",
                "--loose-count",
                str(loose_count),
                "--medium-count",
                str(medium_count),
                "--tight-count",
                str(tight_count),
            ],
        ),
        (
            "part4_stochastic_acceptance",
            [
                py,
                str(SCRIPTS / "build_stochastic_acceptance_pack.py"),
                "--run-id",
                FORMAL_RUN_ID,
            ],
        ),
        (
            "part5_requirement_report",
            [
                py,
                str(SCRIPTS / "build_robustness_requirement_report.py"),
                "--run-id",
                FORMAL_RUN_ID,
            ],
        ),
        (
            "part5_report_evidence_pack",
            [
                py,
                str(SCRIPTS / "build_report_evidence_pack.py"),
            ],
        ),
        (
            "part5_report_evidence_readme",
            [
                py,
                str(SCRIPTS / "build_report_evidence_readme.py"),
            ],
        ),
    ]


def main() -> int:
    args = build_parser().parse_args()
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    test11_counts = _test11_counts(str(args.test11_neighbourhood), str(args.test11_counts))
    commands = _commands(str(args.part2_blocks), test11_counts)
    if args.start_at:
        step_names = [name for name, _ in commands]
        if str(args.start_at) not in step_names:
            raise ValueError(
                f"unknown --start-at step {args.start_at!r}; choose one of {step_names}"
            )
        start_index = step_names.index(str(args.start_at))
        commands = commands[start_index:]
    status: Dict[str, Any] = {
        "ok": False,
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "formal_run_id": FORMAL_RUN_ID,
        "tag": TAG,
        "part2_blocks": str(args.part2_blocks),
        "test11_neighbourhood": str(args.test11_neighbourhood),
        "test11_counts": {
            "loose": test11_counts[0],
            "medium": test11_counts[1],
            "tight": test11_counts[2],
            "total": sum(test11_counts),
        },
        "start_at": str(args.start_at),
        "current_step": None,
        "steps": [],
    }
    _write_status(status)
    _append_runner_log("formal fast robustness runner started")
    env = _base_env()
    os.environ.update(env)
    if args.wait_for_part1 and not _wait_for_part1_completion(
        expected_count=int(args.expected_sensitivity_scenarios),
        poll_seconds=int(args.wait_poll_seconds),
        timeout_hours=float(args.wait_timeout_hours),
        status=status,
    ):
        return 2

    for index, (name, cmd) in enumerate(commands, start=1):
        out_path = LOG_ROOT / f"{index:02d}_{name}.out.log"
        err_path = LOG_ROOT / f"{index:02d}_{name}.err.log"
        step = {
            "index": index,
            "name": name,
            "cmd": cmd,
            "stdout": str(out_path),
            "stderr": str(err_path),
            "started_at": _utc_now(),
            "finished_at": None,
            "elapsed_seconds": None,
            "returncode": None,
            "status": "running",
        }
        status["current_step"] = name
        status["steps"].append(step)
        status["updated_at"] = _utc_now()
        _write_status(status)
        _append_runner_log(f"starting {name}")
        start = time.time()
        with (
            out_path.open("w", encoding="utf-8") as stdout,
            err_path.open("w", encoding="utf-8") as stderr,
        ):
            process = subprocess.Popen(
                list(cmd),
                cwd=str(CW2_ROOT),
                env=env,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
            )
            step["pid"] = process.pid
            _write_status(status)
            returncode = process.wait()
        step["returncode"] = returncode
        step["finished_at"] = _utc_now()
        step["elapsed_seconds"] = round(time.time() - start, 2)
        step["status"] = "completed" if returncode == 0 else "failed"
        status["updated_at"] = _utc_now()
        _write_status(status)
        _append_runner_log(
            f"finished {name} returncode={returncode} elapsed={step['elapsed_seconds']}"
        )
        if returncode != 0:
            status["ok"] = False
            status["current_step"] = name
            status["failed_step"] = step
            status["updated_at"] = _utc_now()
            _write_status(status)
            return returncode
    status["ok"] = True
    status["current_step"] = None
    status["finished_at"] = _utc_now()
    status["updated_at"] = _utc_now()
    _write_status(status)
    _append_runner_log("formal fast robustness runner completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
