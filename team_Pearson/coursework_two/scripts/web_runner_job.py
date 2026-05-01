from __future__ import annotations

"""Execute a web-materialized CW2 job and keep its status JSON in sync."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
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


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _metadata_kafka_config(metadata: dict[str, Any]) -> dict[str, Any]:
    scenario_config = metadata.get("scenario_config")
    if not isinstance(scenario_config, dict):
        return {}
    kafka_config = scenario_config.get("kafka")
    return kafka_config if isinstance(kafka_config, dict) else {}


def _kafka_bootstrap_servers(metadata: dict[str, Any], env: dict[str, str]) -> list[str]:
    env_servers = str(env.get("KAFKA_BOOTSTRAP_SERVERS", "")).strip()
    if env_servers:
        return [item.strip() for item in env_servers.split(",") if item.strip()]
    kafka_config = _metadata_kafka_config(metadata)
    raw_servers = kafka_config.get("bootstrap_servers") or ["localhost:29092"]
    if isinstance(raw_servers, str):
        return [item.strip() for item in raw_servers.split(",") if item.strip()]
    return [str(item).strip() for item in raw_servers if str(item).strip()]


def _socket_reachable(server: str, timeout: float = 2.0) -> bool:
    try:
        host, port_text = server.rsplit(":", 1)
        with socket.create_connection((host, int(port_text)), timeout=timeout):
            return True
    except Exception:
        return False


def _any_kafka_server_reachable(servers: list[str]) -> bool:
    return any(_socket_reachable(server) for server in servers)


def _wait_for_kafka(servers: list[str], timeout_seconds: int = 45) -> bool:
    deadline = time.time() + max(1, timeout_seconds)
    while time.time() < deadline:
        if _any_kafka_server_reachable(servers):
            return True
        time.sleep(1.0)
    return False


def _ensure_optional_kafka(metadata: dict[str, Any], env: dict[str, str], log_handle: Any) -> None:
    kafka_config = _metadata_kafka_config(metadata)
    env_enabled = env.get("KAFKA_ENABLED")
    kafka_enabled = _coerce_bool(env_enabled, _coerce_bool(kafka_config.get("enabled"), False))
    if not kafka_enabled:
        return

    servers = _kafka_bootstrap_servers(metadata, env)
    required = _coerce_bool(env.get("KAFKA_REQUIRED"), _coerce_bool(kafka_config.get("required"), False))
    if _any_kafka_server_reachable(servers):
        log_handle.write(f"[{_timestamp()}] Kafka preflight ok: {', '.join(servers)}\n")
        return

    auto_start = _coerce_bool(env.get("KAFKA_AUTO_START"), True)
    container_name = str(env.get("KAFKA_CONTAINER") or "kafka_cw").strip() or "kafka_cw"
    if auto_start:
        docker_exe = shutil.which("docker")
        if docker_exe:
            log_handle.write(
                f"[{_timestamp()}] Kafka enabled but unreachable; starting Docker container {container_name}.\n"
            )
            log_handle.flush()
            try:
                completed = subprocess.run(
                    [docker_exe, "start", container_name],
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if completed.stdout.strip():
                    log_handle.write(completed.stdout.strip() + "\n")
                if completed.stderr.strip():
                    log_handle.write(completed.stderr.strip() + "\n")
            except Exception as exc:
                log_handle.write(
                    f"[{_timestamp()}] Kafka auto-start command failed: {exc!r}\n"
                )
            log_handle.flush()
            if _wait_for_kafka(servers, timeout_seconds=45):
                log_handle.write(f"[{_timestamp()}] Kafka preflight ok after auto-start.\n")
                return
        else:
            log_handle.write(
                f"[{_timestamp()}] Kafka enabled but Docker CLI was not found for auto-start.\n"
            )

    if required:
        log_handle.write(
            f"[{_timestamp()}] Kafka is required and unreachable: {', '.join(servers)}\n"
        )
        return

    env["KAFKA_ENABLED"] = "false"
    log_handle.write(
        f"[{_timestamp()}] Kafka is optional and unreachable; disabling Kafka for this job.\n"
    )


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
        _ensure_optional_kafka(metadata, env, log_handle)
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
