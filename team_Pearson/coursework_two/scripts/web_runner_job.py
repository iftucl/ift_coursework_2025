from __future__ import annotations

"""Execute a web-materialized CW2 job and keep its status JSON in sync."""

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _timestamp() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _extend_pythonpath(env: dict[str, str], entries: list[str]) -> dict[str, str]:
    cleaned = [str(item).strip() for item in entries if str(item).strip()]
    if not cleaned:
        return env
    existing = str(env.get("PYTHONPATH", "")).strip()
    combined = cleaned + ([existing] if existing else [])
    env["PYTHONPATH"] = os.pathsep.join(combined)
    return env


def _extend_env_vars(env: dict[str, str], entries: dict[str, Any] | None) -> dict[str, str]:
    if not entries:
        return env
    for key, value in entries.items():
        cleaned_key = str(key).strip()
        if cleaned_key:
            env[cleaned_key] = str(value)
    return env


def _ensure_default_postgres_env(env: dict[str, str]) -> dict[str, str]:
    defaults = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5439",
        "POSTGRES_DB": "fift",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
    }
    for key, fallback in defaults.items():
        current = str(env.get(key, "")).strip()
        if not current:
            env[key] = fallback
    return env


def _set_job_status(
    metadata_path: Path,
    *,
    status: str,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _read_json(metadata_path)
    payload["status"] = status
    payload["updated_at"] = _timestamp()
    if updates:
        payload.update(updates)
    _write_json(metadata_path, payload)
    return payload


def run_job(metadata_path: Path) -> int:
    metadata = _set_job_status(
        metadata_path,
        status="running",
        updates={
            "started_at": _timestamp(),
            "runner_pid": os.getpid(),
        },
    )
    log_path = Path(metadata["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    commands = metadata.get("commands") or []
    if not commands:
        _set_job_status(
            metadata_path,
            status="failed",
            updates={
                "finished_at": _timestamp(),
                "exit_code": 1,
                "error": "No commands were materialized for this job.",
            },
        )
        return 1

    env = _extend_pythonpath(os.environ.copy(), metadata.get("pythonpath_entries") or [])
    env = _extend_env_vars(env, metadata.get("env_vars"))
    env = _ensure_default_postgres_env(env)
    exit_code = 0
    with log_path.open("a", encoding="utf-8") as log_handle:
        log_handle.write(f"[{_timestamp()}] Starting job {metadata.get('run_id')}\n")
        for index, command in enumerate(commands, start=1):
            display = command.get("display") or " ".join(command.get("args") or [])
            cwd = command.get("cwd") or os.getcwd()
            _set_job_status(
                metadata_path,
                status="running",
                updates={
                    "current_step_index": index,
                    "current_step_name": str(command.get("name") or f"step_{index}"),
                    "current_step_display": display,
                },
            )
            log_handle.write(f"[{_timestamp()}] Step {index}/{len(commands)}\n")
            log_handle.write(f"[{_timestamp()}] CWD: {cwd}\n")
            log_handle.write(f"[{_timestamp()}] CMD: {display}\n")
            log_handle.flush()
            process = subprocess.run(
                command["args"],
                cwd=cwd,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
            )
            exit_code = int(process.returncode)
            log_handle.write(f"[{_timestamp()}] Step exit code: {exit_code}\n")
            log_handle.flush()
            if exit_code != 0:
                break

        final_status = "completed" if exit_code == 0 else "failed"
        _set_job_status(
            metadata_path,
            status=final_status,
            updates={
                "finished_at": _timestamp(),
                "exit_code": exit_code,
                "current_step_index": None,
                "current_step_name": None,
                "current_step_display": None,
            },
        )
        log_handle.write(
            f"[{_timestamp()}] Job finished with status={final_status} exit_code={exit_code}\n"
        )
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one materialized CW2 web job.")
    parser.add_argument("--job-metadata", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run_job(Path(args.job_metadata).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
