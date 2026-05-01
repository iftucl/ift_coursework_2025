from __future__ import annotations

"""One-command full workflow runner for CW2.

The script validates the local quality gate, checks infrastructure
reachability, runs the formal full-chain strategy/report path, refreshes
robustness evidence surfaces, and verifies that the FastAPI web layer can read
the resulting artifacts.
"""

import argparse
import json
import os
import socket
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
TEAM_ROOT = REPO_ROOT / "team_Pearson"
CW1_ROOT = TEAM_ROOT / "coursework_one"
CW2_ROOT = TEAM_ROOT / "coursework_two"
SCRIPTS_ROOT = CW2_ROOT / "scripts"
SUMMARY_ROOT = CW2_ROOT / "outputs" / "web_state" / "full_workflow"
FORMAL_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"
DEFAULT_SERVICE_ENV = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5439",
    "POSTGRES_DB": "fift",
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "postgres",
    "POSTGRES_CONTAINER": "postgres_db_cw",
    "POSTGRES_ADMIN_DB": "postgres",
    "MONGO_HOST": "localhost",
    "MONGO_PORT": "27019",
    "MINIO_ENDPOINT": "localhost:9000",
    "MINIO_ROOT_USER": "minio",
    "MINIO_ROOT_PASSWORD": "minio123",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6380",
    "KAFKA_BOOTSTRAP_SERVERS": "localhost:29092",
}
REQUIRED_CONTAINERS = (
    "postgres_db_cw",
    "mongo_db_cw",
    "miniocw",
    "minio_client_cw",
    "team_pearson_redis",
    "kafka_cw",
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(CW1_ROOT) not in sys.path:
    sys.path.insert(0, str(CW1_ROOT))

from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    default_cw1_config,
    load_env_layers,
)


def _formal_config_path() -> str:
    candidate = (
        CW2_ROOT / "config" / "experiments" / "formal" / "cw2_formal_20260420_fund_ra3_s30_t50.yaml"
    )
    if candidate.exists():
        return str(candidate)
    return str(CW2_ROOT / "config" / "conf.yaml")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _python_exe() -> str:
    return sys.executable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the CW2 one-command full workflow. By default this executes "
            "quality checks, the formal full-chain run, robustness bridge, and "
            "web checks; skip/reuse modes are opt-in flags."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--run-date", default="2026-04-20")
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=_formal_config_path())
    parser.add_argument(
        "--company-limit",
        type=int,
        default=None,
        help="Optional full-chain universe cap. Omit it for the configured full universe.",
    )
    parser.add_argument(
        "--smoke-profile",
        "--quick-profile",
        dest="quick_profile",
        action="store_true",
        help=(
            "Optional fast end-to-end validation path: pass through a temporary "
            "relaxed config to the full-chain runner. Defaults off for the full "
            "workflow, so omitting this flag runs the configured full path."
        ),
    )
    parser.add_argument(
        "--smoke-lookback-years",
        "--quick-lookback-years",
        dest="quick_lookback_years",
        type=int,
        default=None,
        help=(
            "Optional lookback window for --smoke-profile. Omit it to use the "
            "full-chain runner default."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--start-services", action="store_true")
    parser.add_argument(
        "--serve", action="store_true", help="Keep the web server open after checks."
    )
    parser.add_argument("--skip-quality", action="store_true")
    parser.add_argument("--skip-chain", action="store_true")
    parser.add_argument(
        "--reuse-existing-formal",
        action="store_true",
        help=(
            "Verify the checked-in formal 6905 report, robustness, repro, and "
            "web-state artifacts, then skip the expensive data refresh/full-chain "
            "rerun. Robustness bridge and web checks still run unless skipped."
        ),
    )
    parser.add_argument("--skip-robustness", action="store_true")
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--include-pytest", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    return parser


def _base_env() -> dict[str, str]:
    load_env_layers()
    for key, value in DEFAULT_SERVICE_ENV.items():
        if not os.environ.get(key):
            os.environ[key] = value
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("MPLBACKEND", "Agg")
    python_path = [str(REPO_ROOT), str(CW1_ROOT)]
    existing = env.get("PYTHONPATH")
    if existing:
        python_path.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(python_path)
    return env


def _run_step(
    name: str,
    cmd: list[str],
    *,
    cwd: Path = CW2_ROOT,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(  # nosec B603
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    elapsed = round(time.time() - started, 3)
    result = {
        "step": name,
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "elapsed_seconds": elapsed,
        "cmd": " ".join(cmd),
    }
    if completed.stdout.strip():
        result["stdout_tail"] = completed.stdout.strip()[-4000:]
    if completed.stderr.strip():
        result["stderr_tail"] = completed.stderr.strip()[-4000:]
    if completed.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {completed.returncode}: {result}")
    return result


def _run_quality(
    env: dict[str, str], *, include_pytest: bool, timeout: int
) -> list[dict[str, Any]]:
    py = _python_exe()
    steps = [
        ("black", [py, "-m", "black", "--check", "modules", "scripts", "tests", "api"]),
        ("isort", [py, "-m", "isort", "--check-only", "modules", "scripts", "tests", "api"]),
        ("flake8", [py, "-m", "flake8", "--jobs=1", "modules", "scripts", "tests", "api", "web"]),
        ("bandit", [py, "-m", "bandit", "-c", "bandit.yaml", "-r", "modules", "api", "web", "-ll"]),
        ("large_file_check", [py, "scripts/check_large_files.py", "--max-mb", "5"]),
        (
            "sphinx",
            [py, "-m", "sphinx", "-W", "--keep-going", "-b", "html", "docs", "docs/_build/html"],
        ),
    ]
    if include_pytest:
        steps.append(
            (
                "pytest_coverage",
                [
                    py,
                    "-m",
                    "pytest",
                    "-p",
                    "no:cacheprovider",
                    "tests",
                    "--cov=modules",
                    "--cov-report=term-missing",
                    "--cov-report=html",
                ],
            )
        )
    return [_run_step(name, cmd, env=env, timeout=timeout) for name, cmd in steps]


def _docker_compose_cmd() -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(REPO_ROOT / "docker-compose.yml"),
        "-f",
        str(CW1_ROOT / "docker-compose.pearson.override.yml"),
        "up",
        "-d",
        "postgres_db",
        "mongo_db",
        "miniocw",
        "minio_client_cw",
        "team_pearson_redis",
        "kafka_cw",
    ]


def _list_docker_containers(env: dict[str, str]) -> set[str]:
    result = subprocess.run(  # nosec B603,B607
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _start_services(env: dict[str, str]) -> list[dict[str, Any]]:
    existing = _list_docker_containers(env)
    required = set(REQUIRED_CONTAINERS)
    if required.issubset(existing):
        return [
            _run_step(
                "docker_start_existing",
                ["docker", "start", *REQUIRED_CONTAINERS],
                cwd=REPO_ROOT,
                env=env,
                timeout=300,
            )
        ]
    return [
        _run_step(
            "docker_compose_up",
            _docker_compose_cmd(),
            cwd=REPO_ROOT,
            env=env,
            timeout=300,
        )
    ]


def _socket_check(name: str, host: str, port: int, timeout: float = 3.0) -> dict[str, Any]:
    started = time.time()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return {
                "service": name,
                "host": host,
                "port": int(port),
                "status": "ok",
                "elapsed_seconds": round(time.time() - started, 3),
            }
    except OSError as exc:
        return {
            "service": name,
            "host": host,
            "port": int(port),
            "status": "failed",
            "error": str(exc),
        }


def _check_infrastructure() -> list[dict[str, Any]]:
    checks = [
        (
            "postgres",
            os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            int(os.environ.get("POSTGRES_PORT", "5439")),
        ),
        (
            "mongo",
            os.environ.get("MONGO_HOST", "127.0.0.1"),
            int(os.environ.get("MONGO_PORT", "27019")),
        ),
        (
            "minio",
            str(os.environ.get("MINIO_ENDPOINT", "127.0.0.1:9000")).split(":", 1)[0],
            int(str(os.environ.get("MINIO_ENDPOINT", "127.0.0.1:9000")).split(":")[-1]),
        ),
        (
            "redis",
            os.environ.get("REDIS_HOST", "127.0.0.1"),
            int(os.environ.get("REDIS_PORT", "6380")),
        ),
        (
            "kafka",
            str(os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")).split(":", 1)[0],
            int(str(os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")).split(":")[-1]),
        ),
    ]
    results = [_socket_check(name, host, port) for name, host, port in checks]

    try:
        from sqlalchemy import text
        from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine

        engine = get_db_engine()
        with engine.connect() as conn:
            schema_exists = conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name='systematic_equity')"
                )
            ).scalar()
        results.append(
            {"service": "postgres_sql", "status": "ok", "systematic_equity": bool(schema_exists)}
        )
    except Exception as exc:  # noqa: BLE001
        results.append({"service": "postgres_sql", "status": "failed", "error": str(exc)})

    failed = [item for item in results if item.get("status") != "ok"]
    if failed:
        raise RuntimeError(f"Infrastructure check failed: {failed}")
    return results


def _parse_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        return json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _required_formal_artifacts() -> list[tuple[str, Path]]:
    report_dir = CW2_ROOT / "outputs" / "reports" / "cw2_formal_fund_ra3_s30_t50_20260420_report"
    robustness_dir = CW2_ROOT / "outputs" / "robustness"
    web_state_dir = CW2_ROOT / "outputs" / "web_state"
    return [
        ("formal_config", Path(_formal_config_path())),
        ("reference_run_contract", CW2_ROOT / "repro" / "reference_run_20260420.json"),
        ("formal_report_markdown", report_dir / "report.md"),
        ("formal_report_summary", report_dir / "report_summary.json"),
        ("formal_nav_chart", report_dir / "nav_vs_benchmarks.png"),
        ("formal_turnover_cost_chart", report_dir / "turnover_and_cost.png"),
        (
            "robustness_evidence_pack",
            robustness_dir / "report_evidence" / "ROBUSTNESS_REPORT_EVIDENCE_PACK.md",
        ),
        (
            "robustness_evidence_index",
            robustness_dir / "report_evidence" / "REPORT_EVIDENCE_INDEX.md",
        ),
        (
            "robustness_dashboard",
            robustness_dir / "stochastic" / "acceptance" / "robustness_dashboard.csv",
        ),
        ("web_mainline_scenario", web_state_dir / "scenarios" / "_mainline.json"),
        ("web_ai_report_registry", web_state_dir / "ai_reports" / "registry.json"),
    ]


def _check_existing_formal_artifacts() -> dict[str, Any]:
    checked = _required_formal_artifacts()
    missing = [f"{name}: {path}" for name, path in checked if not path.exists()]
    if missing:
        raise RuntimeError(
            "Cannot reuse existing formal artifacts because required files are missing: "
            + "; ".join(missing)
        )

    reference_path = CW2_ROOT / "repro" / "reference_run_20260420.json"
    reference_payload = json.loads(reference_path.read_text(encoding="utf-8"))
    reference_run_id = (
        reference_payload.get("reference_run", {}).get("run_id")
        if isinstance(reference_payload, dict)
        else None
    )
    if reference_run_id != FORMAL_RUN_ID:
        raise RuntimeError(
            "Existing formal artifact check found an unexpected reference run id: "
            f"{reference_run_id!r}; expected {FORMAL_RUN_ID!r}"
        )

    summary_path = (
        CW2_ROOT
        / "outputs"
        / "reports"
        / "cw2_formal_fund_ra3_s30_t50_20260420_report"
        / "report_summary.json"
    )
    report_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    key_metrics = {
        key: report_payload.get(key)
        for key in (
            "total_return",
            "annualized_return",
            "annualized_volatility",
            "sharpe_ratio",
            "max_drawdown",
            "information_ratio_vs_primary",
        )
        if key in report_payload
    }
    return {
        "step": "reuse_existing_formal_artifacts",
        "status": "ok",
        "reused_run_id": FORMAL_RUN_ID,
        "skipped_stage": "formal_full_chain",
        "artifact_count": len(checked),
        "artifacts": [
            {"name": name, "path": str(path.relative_to(CW2_ROOT))} for name, path in checked
        ],
        "key_metrics": key_metrics,
    }


def _run_chain(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    py = _python_exe()
    tag = _timestamp()
    cmd = [
        py,
        str(SCRIPTS_ROOT / "run_full_chain.py"),
        "--run-date",
        str(args.run_date),
        "--cw1-config",
        str(args.cw1_config),
        "--cw2-config",
        str(args.cw2_config),
        "--run-name",
        f"full_workflow_{tag}",
        "--report-name",
        f"full_workflow_report_{tag}",
        "--report-output-dir",
        str(CW2_ROOT / "outputs" / "reports" / "full_workflow"),
    ]
    if args.company_limit is not None:
        cmd.extend(["--company-limit", str(args.company_limit)])
    if bool(args.quick_profile):
        cmd.append("--smoke-profile")
    if args.quick_lookback_years is not None:
        cmd.extend(["--smoke-lookback-years", str(args.quick_lookback_years)])
    step = _run_step("formal_full_chain", cmd, env=env, timeout=int(args.timeout_seconds))
    payload = _parse_json_payload(str(step.get("stdout_tail") or ""))
    step["payload"] = payload
    return step


def _run_robustness_bridge(env: dict[str, str], timeout: int) -> list[dict[str, Any]]:
    py = _python_exe()
    steps = [
        (
            "build_robustness_requirement_report",
            [
                py,
                str(SCRIPTS_ROOT / "build_robustness_requirement_report.py"),
                "--run-id",
                FORMAL_RUN_ID,
            ],
        ),
        (
            "persist_robustness_outputs",
            [
                py,
                str(SCRIPTS_ROOT / "persist_robustness_outputs.py"),
                "--report-name",
                "cw2_robustness_outputs_full_workflow",
                "--source-run-id",
                FORMAL_RUN_ID,
            ],
        ),
    ]
    return [_run_step(name, cmd, env=env, timeout=timeout) for name, cmd in steps]


def _http_get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json,text/html"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
        return int(response.status), response.read().decode("utf-8", errors="replace")


def _wait_for_http(url: str, timeout_seconds: int = 60) -> bool:
    deadline = time.time() + int(timeout_seconds)
    while time.time() < deadline:
        try:
            status, _ = _http_get(url, timeout=3.0)
            if 200 <= status < 500:
                return True
        except (OSError, urllib.error.URLError):
            time.sleep(1.0)
    return False


def _start_api_server(
    args: argparse.Namespace, env: dict[str, str]
) -> tuple[subprocess.Popen[str] | None, str]:
    base_url = f"http://{args.host}:{int(args.port)}"
    if _wait_for_http(f"{base_url}/health", timeout_seconds=2):
        return None, base_url
    cmd = [
        _python_exe(),
        "-m",
        "uvicorn",
        "api.main:app",
        "--host",
        str(args.host),
        "--port",
        str(args.port),
    ]
    proc = subprocess.Popen(  # nosec B603
        cmd,
        cwd=str(CW2_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if not _wait_for_http(f"{base_url}/health", timeout_seconds=60):
        proc.terminate()
        raise RuntimeError(f"API server did not become ready at {base_url}")
    return proc, base_url


def _check_web(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    proc, base_url = _start_api_server(args, env)
    endpoints = [
        "/health",
        "/",
        "/api/summary",
        "/api/runs/recent",
        "/api/artifacts",
        "/api/robustness/dashboard",
        "/api/robustness/acceptance",
        "/api/robustness/report-evidence",
        "/api/workbench/context",
    ]
    checks = []
    try:
        for endpoint in endpoints:
            status, body = _http_get(f"{base_url}{endpoint}")
            checks.append(
                {
                    "endpoint": endpoint,
                    "status_code": status,
                    "ok": 200 <= status < 300,
                    "bytes": len(body.encode("utf-8")),
                }
            )
        failed = [item for item in checks if not item["ok"]]
        if failed:
            raise RuntimeError(f"Web endpoint checks failed: {failed}")
        return {
            "status": "ok",
            "base_url": base_url,
            "checks": checks,
            "server_started": proc is not None,
        }
    finally:
        if proc is not None and not bool(args.serve):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _write_summary(summary: dict[str, Any]) -> Path:
    SUMMARY_ROOT.mkdir(parents=True, exist_ok=True)
    path = SUMMARY_ROOT / f"full_workflow_summary_{_timestamp()}.json"
    path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    latest = SUMMARY_ROOT / "latest.json"
    latest.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return path


def _print_step_table(items: Iterable[dict[str, Any]]) -> None:
    for item in items:
        name = item.get("step") or item.get("service") or item.get("endpoint")
        print(f"[{item.get('status', 'ok')}] {name}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = _base_env()
    summary: dict[str, Any] = {
        "status": "ok",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_date": args.run_date,
        "cw1_config": str(args.cw1_config),
        "cw2_config": str(args.cw2_config),
        "company_limit": args.company_limit,
        "smoke_profile": bool(args.quick_profile),
        "smoke_lookback_years": args.quick_lookback_years,
        "quick_profile": bool(args.quick_profile),
        "quick_lookback_years": args.quick_lookback_years,
        "reuse_existing_formal": bool(args.reuse_existing_formal),
        "steps": [],
    }
    try:
        if args.start_services:
            summary["steps"].extend(_start_services(env))
        if not args.skip_quality:
            quality_steps = _run_quality(
                env,
                include_pytest=bool(args.include_pytest),
                timeout=int(args.timeout_seconds),
            )
            summary["steps"].extend(quality_steps)
        infrastructure = _check_infrastructure()
        summary["infrastructure"] = infrastructure
        if bool(args.reuse_existing_formal) and not args.skip_chain:
            reuse_step = _check_existing_formal_artifacts()
            summary["steps"].append(reuse_step)
            summary["full_workflow_run_id"] = FORMAL_RUN_ID
        elif not args.skip_chain:
            chain = _run_chain(args, env)
            summary["steps"].append(chain)
            summary["full_workflow_run_id"] = (chain.get("payload") or {}).get("run_id")
        if not args.skip_robustness:
            summary["steps"].extend(_run_robustness_bridge(env, timeout=int(args.timeout_seconds)))
        if not args.skip_web:
            summary["web"] = _check_web(args, env)
        summary_path = _write_summary(summary)
        _print_step_table(summary.get("steps", []))
        _print_step_table(summary.get("infrastructure", []))
        if summary.get("web"):
            _print_step_table((summary["web"] or {}).get("checks", []))
            print(f"Web URL: {summary['web']['base_url']}")
        print(f"Full workflow summary: {summary_path}")
        if bool(args.serve):
            print("Web server is running. Press Ctrl+C to stop.")
            while True:
                time.sleep(60)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        summary["status"] = "failed"
        summary["error"] = str(exc)
        summary_path = _write_summary(summary)
        print(f"Full workflow failed. Summary: {summary_path}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
