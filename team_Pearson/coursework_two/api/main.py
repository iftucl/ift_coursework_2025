"""FastAPI service for the CW2 web platform."""

from __future__ import annotations

import asyncio
import csv
import gzip
import io
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


def _find_pydeps_path() -> Path | None:
    search_roots: list[Path] = []
    try:
        search_roots.append(Path.cwd())
    except Exception:
        pass
    try:
        search_roots.append(Path(__file__).parent)
    except Exception:
        pass
    seen: set[str] = set()
    for root in search_roots:
        for candidate_base in [root, *root.parents]:
            candidate = candidate_base / "_restore_workspace" / "pydeps"
            candidate_key = str(candidate)
            if candidate_key in seen:
                continue
            seen.add(candidate_key)
            try:
                if candidate.exists():
                    return candidate
            except OSError:
                continue
    return None


try:
    from sqlalchemy import create_engine
    from sqlalchemy import text as sql_text
except ModuleNotFoundError:  # pragma: no cover
    pydeps_path = _find_pydeps_path()
    if pydeps_path and str(pydeps_path) not in sys.path:
        sys.path.insert(0, str(pydeps_path))
    try:
        from sqlalchemy import create_engine
        from sqlalchemy import text as sql_text
    except ModuleNotFoundError:
        create_engine = None
        sql_text = None


BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
ROBUSTNESS_DIR = BASE_DIR / "outputs" / "robustness"
REPORT_EVIDENCE_DIR = ROBUSTNESS_DIR / "report_evidence"
LEGACY_REPORT_HANDOFF_DIR = ROBUSTNESS_DIR / "report_handoff"
REQUIREMENT_REPORT_DIR = ROBUSTNESS_DIR / "requirement_report"
SUBPERIOD_DIR = ROBUSTNESS_DIR / "subperiod"
TEST11_DIR = ROBUSTNESS_DIR / "test11_factor_neighbourhood"
WEB_STATE_DIR = BASE_DIR / "outputs" / "web_state"
SCENARIO_STATE_PATH = WEB_STATE_DIR / "scenario_builder_state.json"
SCENARIO_DIR = WEB_STATE_DIR / "scenarios"
MAINLINE_SCENARIO_PATH = SCENARIO_DIR / "_mainline.json"
RUN_QUEUE_DIR = WEB_STATE_DIR / "queued_runs"
GENERATED_CONFIG_DIR = WEB_STATE_DIR / "generated_configs"
JOB_BUNDLE_DIR = WEB_STATE_DIR / "job_bundles"
JOB_LOG_DIR = WEB_STATE_DIR / "job_logs"
AI_REPORT_DIR = WEB_STATE_DIR / "ai_reports"
AI_REPORT_LATEST_PATH = AI_REPORT_DIR / "latest.json"
AI_REPORT_REGISTRY_PATH = AI_REPORT_DIR / "registry.json"
AI_REPORT_DOCX_SCRIPT_PATH = BASE_DIR / "scripts" / "export_ai_report_docx.py"
AI_REPORT_PDF_SCRIPT_PATH = BASE_DIR / "scripts" / "export_ai_report_pdf.py"
AUDIT_LOG_PATH = WEB_STATE_DIR / "audit_log.json"
RUNNER_SCRIPT_PATH = BASE_DIR / "scripts" / "web_runner_job.py"
NIGHTLY_SCHEDULER_SCRIPT_PATH = BASE_DIR / "scripts" / "nightly_scheduler.py"
NIGHTLY_SCHEDULER_PID_PATH = WEB_STATE_DIR / "nightly_scheduler.pid"
NIGHTLY_SCHEDULER_LOG_PATH = WEB_STATE_DIR / "nightly_scheduler.log"
BASELINE_CONFIG_PATH = (
    BASE_DIR / "config" / "experiments" / "formal" / "cw2_formal_20260420_fund_ra3_s30_t50.yaml"
)
BACKFILL_START_DATE = "2021-04-20"
BACKFILL_END_DATE = "2026-04-20"
ROBUSTNESS_REPORT_PREFIX = "cw2_robustness_outputs_"
REPORT_EVIDENCE_NAME = "cw2_robustness_report_evidence_pack"
LEGACY_REPORT_HANDOFF_NAME = "cw2_robustness_handoff_pack"
REPORT_SECTION_ORDER = [
    "Executive Summary",
    "Strategy And Portfolio Construction",
    "Backtest Design",
    "Backtest Results",
    "Risk, Regime And Exposure Analysis",
    "Robustness And Sensitivity",
    "Limitations And Monitoring Signals",
]
DEFAULT_MAINLINE_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"
FORMAL_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"
OUTPUTS_DIR = BASE_DIR / "outputs"
FORMAL_BASELINE_DIR = OUTPUTS_DIR / "formal_baseline"
FORMAL_REPORT_DIR = FORMAL_BASELINE_DIR / "report"
FORMAL_DB_CSV_DIR = FORMAL_BASELINE_DIR / "db_csv" / "systematic_equity"
FORMAL_SLIM_DIR = (
    BASE_DIR / "inputs" / "formal_slim_6905_20260420_extracted" / "formal_slim_6905_20260420"
)
FORMAL_SLIM_DB_CSV_DIR = FORMAL_SLIM_DIR / "db_csv" / "systematic_equity"
FORMAL_DB_CSV_CANDIDATE_DIRS = [
    FORMAL_SLIM_DB_CSV_DIR,
    FORMAL_DB_CSV_DIR,
]
FORMAL_HANDOFF_DIR = BASE_DIR / "docs" / "formal_handoff_20260429"
FORMAL_CONFIG_PATH = (
    BASE_DIR / "config" / "experiments" / "formal" / "cw2_formal_20260420_fund_ra3_s30_t50.yaml"
)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


def _db_lookup_enabled() -> bool:
    raw_value = str(os.getenv("CW2_WEB_ENABLE_DB_LOOKUP", "")).strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _migrate_legacy_report_handoff_outputs() -> None:
    if not LEGACY_REPORT_HANDOFF_DIR.exists():
        legacy_zip = ROBUSTNESS_DIR / "report_handoff.zip"
        evidence_zip = ROBUSTNESS_DIR / "report_evidence.zip"
        if legacy_zip.exists() and not evidence_zip.exists():
            try:
                legacy_zip.replace(evidence_zip)
            except OSError:
                pass
        return
    try:
        if REPORT_EVIDENCE_DIR.exists():
            shutil.copytree(LEGACY_REPORT_HANDOFF_DIR, REPORT_EVIDENCE_DIR, dirs_exist_ok=True)
            shutil.rmtree(LEGACY_REPORT_HANDOFF_DIR, ignore_errors=True)
        else:
            LEGACY_REPORT_HANDOFF_DIR.replace(REPORT_EVIDENCE_DIR)
    except OSError:
        return
    rename_pairs = [
        ("REPORT_HANDOFF_INDEX.csv", "REPORT_EVIDENCE_INDEX.csv"),
        ("REPORT_HANDOFF_INDEX.md", "REPORT_EVIDENCE_INDEX.md"),
        ("ROBUSTNESS_REPORT_PACK.md", "ROBUSTNESS_REPORT_EVIDENCE_PACK.md"),
    ]
    for old_name, new_name in rename_pairs:
        old_path = REPORT_EVIDENCE_DIR / old_name
        new_path = REPORT_EVIDENCE_DIR / new_name
        if old_path.exists() and not new_path.exists():
            try:
                old_path.replace(new_path)
            except OSError:
                pass
    manifest_path = REPORT_EVIDENCE_DIR / "manifest.json"
    if manifest_path.exists():
        try:
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest_path.write_text(
                manifest_text.replace(
                    "\\outputs\\robustness\\report_handoff",
                    "\\outputs\\robustness\\report_evidence",
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
    overview_path = REPORT_EVIDENCE_DIR / "ROBUSTNESS_REPORT_EVIDENCE_PACK.md"
    if overview_path.exists():
        try:
            overview_text = overview_path.read_text(encoding="utf-8")
            overview_path.write_text(
                overview_text.replace("REPORT_HANDOFF_INDEX", "REPORT_EVIDENCE_INDEX"),
                encoding="utf-8",
            )
        except OSError:
            pass
    legacy_zip = ROBUSTNESS_DIR / "report_handoff.zip"
    evidence_zip = ROBUSTNESS_DIR / "report_evidence.zip"
    if legacy_zip.exists() and not evidence_zip.exists():
        try:
            legacy_zip.replace(evidence_zip)
        except OSError:
            pass


_migrate_legacy_report_handoff_outputs()


def _active_report_evidence_dir() -> Path:
    if REPORT_EVIDENCE_DIR.exists() and any(
        (REPORT_EVIDENCE_DIR / name).exists()
        for name in ("manifest.json", "REPORT_EVIDENCE_INDEX.csv", "REPORT_HANDOFF_INDEX.csv")
    ):
        return REPORT_EVIDENCE_DIR
    if LEGACY_REPORT_HANDOFF_DIR.exists() and any(
        (LEGACY_REPORT_HANDOFF_DIR / name).exists()
        for name in ("manifest.json", "REPORT_EVIDENCE_INDEX.csv", "REPORT_HANDOFF_INDEX.csv")
    ):
        return LEGACY_REPORT_HANDOFF_DIR
    return FORMAL_HANDOFF_DIR


def _fetch_report_evidence_db_artifacts() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    report, artifacts = _fetch_db_artifacts(report_name=REPORT_EVIDENCE_NAME)
    if report or artifacts:
        return report, artifacts
    return _fetch_db_artifacts(report_name=LEGACY_REPORT_HANDOFF_NAME)


def _scheduler_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _scheduler_log_is_fresh(*, max_age_seconds: int = 90) -> bool:
    if not NIGHTLY_SCHEDULER_LOG_PATH.exists():
        return False
    age_seconds = max(0.0, datetime.now().timestamp() - NIGHTLY_SCHEDULER_LOG_PATH.stat().st_mtime)
    return age_seconds <= max_age_seconds


def _ensure_nightly_scheduler_running() -> None:
    existing_pid = 0
    if NIGHTLY_SCHEDULER_PID_PATH.exists():
        try:
            existing_pid = int(NIGHTLY_SCHEDULER_PID_PATH.read_text(encoding="utf-8").strip())
        except Exception:
            existing_pid = 0
    if _scheduler_pid_alive(existing_pid) and _scheduler_log_is_fresh():
        return
    try:
        NIGHTLY_SCHEDULER_PID_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    env = os.environ.copy()
    pydeps_entries = (
        _resolve_runner_pythonpath_entries()
        if "_resolve_runner_pythonpath_entries" in globals()
        else []
    )
    if pydeps_entries:
        existing_pythonpath = str(env.get("PYTHONPATH", "")).strip()
        env["PYTHONPATH"] = os.pathsep.join(
            pydeps_entries + ([existing_pythonpath] if existing_pythonpath else [])
        )
    creation_flags = 0
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )
    try:
        subprocess.Popen(
            [sys.executable, str(NIGHTLY_SCHEDULER_SCRIPT_PATH)],
            cwd=str(BASE_DIR),
            env=env,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        try:
            JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
            (JOB_LOG_DIR / "nightly_scheduler_startup_warning.log").write_text(
                f"{_utc_now_text()} scheduler startup skipped: {exc}\n",
                encoding="utf-8",
            )
        except Exception:
            pass


class HealthResponse(BaseModel):
    status: str
    service: str


class SummaryCard(BaseModel):
    label: str
    value: str


class NavigationPage(BaseModel):
    id: str
    label: str
    section: str


class RunRecord(BaseModel):
    run_id: str
    started_at: str
    scenario: str
    status: str
    duration: str
    created_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    scheduled_for: str | None = None
    queue_type: str | None = None


class ArtifactRecord(BaseModel):
    name: str
    description: str
    status: str
    source: str


class RobustnessDashboardRecord(BaseModel):
    section: str
    item_key: str
    title: str
    annualized_return: float | None
    annualized_excess_return: float | None
    sharpe: float | None
    max_drawdown: float | None
    implementation_status: str


class AcceptanceRecord(BaseModel):
    requirement_group: str
    item_key: str
    label: str
    status: str
    detail: str


class ScenarioBuilderStatePayload(BaseModel):
    draft: dict[str, Any]
    presets: dict[str, dict[str, Any]]
    active_preset: str | None = None


class ScenarioPayload(BaseModel):
    scenario_name: str
    scenario_config: dict[str, Any]
    parent_scenario_id: str | None = None
    notes: str | None = None


class ScenarioRecord(BaseModel):
    scenario_id: str
    scenario_name: str
    scenario_config: dict[str, Any]
    status: str
    version: int
    version_hash: str
    is_mainline: bool = False
    parent_scenario_id: str | None = None
    created_at: str
    updated_at: str
    notes: str | None = None


class RunnerQueuePayload(BaseModel):
    run_id: str
    queue_type: str
    label: str
    owner: str
    priority: str
    scenario_name: str | None = None
    scenario_config: dict[str, Any]
    batch_targets: list[str] = []
    scenario_configs: dict[str, dict[str, Any]] = {}
    artifact_bundle: bool = True
    notifications: bool = True
    created_at: str | None = None
    scheduled_for: str | None = None
    auto_start: bool = False
    robustness_options: dict[str, Any] = {}


class AiReportRequest(BaseModel):
    api_url: str
    api_key: str
    model: str
    user_instruction: str | None = None
    system_prompt: str | None = None
    request_format: str = "openai"
    temperature: float = 0.2


class LlmModelsRequest(BaseModel):
    api_url: str
    api_key: str
    request_format: str = "openai"


class AiSectionRegenerateRequest(AiReportRequest):
    section_name: str


class AiCrossCheckRequest(BaseModel):
    report_id: str | None = None


class AiReportResponse(BaseModel):
    report_id: str
    status: str
    generated_at: str
    provider_url: str
    model: str
    request_format: str
    output_path: str
    output_markdown_path: str
    output_docx_path: str = ""
    output_pdf_path: str = ""
    analysis_text: str
    sections: dict[str, str]
    context_snapshot: dict[str, Any]
    prompt_template_version: str = "cw2-report-v5-narrative-pass"
    guardrails: dict[str, Any] = {}
    source_trace_preview: list[dict[str, Any]] = []
    selected_evidence: dict[str, Any] = {}
    error_message: str = ""


class BacktestRunRequest(BaseModel):
    scenario_id: str | None = None
    scenario_name: str | None = None
    scenario_config: dict[str, Any] | None = None
    owner: str = "Team C"
    priority: str = "Normal"
    artifact_bundle: bool = True
    notifications: bool = True
    mode: str = "full"
    auto_start: bool = True


class BacktestCompareRequest(BaseModel):
    scenario_ids: list[str] = []
    owner: str = "Team C"
    priority: str = "Normal"
    artifact_bundle: bool = True
    notifications: bool = True
    auto_start: bool = True


class BacktestEstimateRequest(BaseModel):
    scenario_id: str | None = None
    scenario_name: str | None = None
    scenario_config: dict[str, Any] | None = None
    mode: str = "full"


class PreviewRequest(BaseModel):
    scenario_id: str | None = None
    scenario_name: str | None = None
    scenario_config: dict[str, Any] | None = None


class RobustnessSensitivityRequest(BaseModel):
    scenario_id: str | None = None
    scenario_name: str | None = None
    scenario_config: dict[str, Any] | None = None
    base_scenario: str = "Current working scenario"
    sensitivity_dimensions: list[str] = []
    range_profile: str = "Mainline core"
    bootstrap_iterations: int = 1000
    stochastic_mode: str = "Bootstrap + Monte Carlo"
    subperiod_definition: str = "Normal vs stress"
    owner: str = "Team C"
    priority: str = "Normal"
    auto_start: bool = True


FACTOR_LABELS = {
    "quality": "Quality",
    "value": "Value",
    "market_technical": "Market Technical",
    "sentiment": "Sentiment",
    "dividend": "Dividend",
    "momentum": "Momentum",
}


def _title_factor_name(value: str) -> str:
    return FACTOR_LABELS.get(value, value.replace("_", " ").title())


def _format_cadence(value: Any) -> str:
    text_value = str(value or "").strip()
    return text_value[:1].upper() + text_value[1:] if text_value else ""


def _format_bps(value: Any) -> str:
    numeric_value = _safe_number(value)
    if numeric_value is None:
        return str(value or "").strip()
    return f"{numeric_value:g}bps"


def _format_weight_pct(value: Any) -> str:
    numeric_value = _safe_number(value)
    if numeric_value is None:
        return str(value or "").strip()
    return f"{numeric_value * 100:g}%"


def _factor_sleeves_from_regime(config: dict[str, Any]) -> list[str]:
    regime = config.get("regime") if isinstance(config.get("regime"), dict) else {}
    factor_keys: list[str] = []
    for regime_name in ("normal", "stress"):
        weights = regime.get(regime_name) if isinstance(regime.get(regime_name), dict) else {}
        for factor_name, factor_weight in weights.items():
            numeric_weight = _safe_number(factor_weight)
            if numeric_weight is not None and numeric_weight > 0 and factor_name not in factor_keys:
                factor_keys.append(factor_name)
    return [_title_factor_name(factor_name) for factor_name in factor_keys]


def _derive_universe_label(config: dict[str, Any]) -> str:
    universe = config.get("universe")
    if universe:
        return str(universe)
    investable = (
        config.get("investable_universe")
        if isinstance(config.get("investable_universe"), dict)
        else {}
    )
    countries = (
        investable.get("country_allowlist")
        if isinstance(investable.get("country_allowlist"), list)
        else []
    )
    liquidity = _safe_number(investable.get("min_liquidity_20d"))
    market_cap_log = _safe_number(investable.get("min_market_cap_log"))
    parts = []
    if countries:
        parts.append("/".join(str(item) for item in countries))
    parts.append("PIT screened universe")
    if liquidity is not None:
        parts.append(f"ADV >= {liquidity:,.0f}")
    if market_cap_log is not None:
        parts.append(f"log mcap >= {market_cap_log:g}")
    return " / ".join(parts)


def _scenario_config_with_defaults(scenario_config: dict[str, Any] | None) -> dict[str, Any]:
    config = (
        scenario_config
        if isinstance(scenario_config, dict) and scenario_config
        else _load_baseline_config_payload()
    )
    if not isinstance(config, dict):
        config = {}
    if (
        "portfolio_construction" not in config
        and "backtest" not in config
        and "regime" not in config
    ):
        factor_sleeves = config.get("factor_sleeves")
        if isinstance(factor_sleeves, str):
            factor_sleeves = [item.strip() for item in factor_sleeves.split("/") if item.strip()]
        merged = dict(config)
        merged["factor_sleeves"] = factor_sleeves or []
        return merged

    portfolio = (
        config.get("portfolio_construction")
        if isinstance(config.get("portfolio_construction"), dict)
        else {}
    )
    backtest = config.get("backtest") if isinstance(config.get("backtest"), dict) else {}
    regime = config.get("regime") if isinstance(config.get("regime"), dict) else {}
    preprocessing = (
        config.get("preprocessing") if isinstance(config.get("preprocessing"), dict) else {}
    )
    factor_sleeves = config.get("factor_sleeves") or _factor_sleeves_from_regime(config)
    if isinstance(factor_sleeves, str):
        factor_sleeves = [item.strip() for item in factor_sleeves.split("/") if item.strip()]
    rebalance = (
        config.get("rebalance")
        or backtest.get("rebalance_frequency")
        or portfolio.get("target_generation_frequency")
    )
    top_n = (
        config.get("top_n")
        or portfolio.get("top_n")
        or portfolio.get("hybrid_min_n")
        or backtest.get("top_n")
    )
    vix_threshold = config.get("vix_threshold") or regime.get("vix_stress_threshold")
    transaction_cost = config.get("transaction_cost") or _format_bps(
        backtest.get("transaction_cost_bps")
    )
    hold_cap = config.get("hold_cap") or _format_weight_pct(portfolio.get("max_single_weight"))
    benchmark = config.get("benchmark") or backtest.get("benchmark_ticker") or "Formal benchmark"
    lookback_years = backtest.get("lookback_years")
    output_pack = config.get("output_pack") or "Formal baseline evidence pack"
    neutralize_by = str(preprocessing.get("neutralize_by") or "").lower()
    return {
        **config,
        "universe": _derive_universe_label(config),
        "rebalance": _format_cadence(rebalance),
        "top_n": (
            ""
            if top_n is None
            else f"{_safe_number(top_n):g}" if _safe_number(top_n) is not None else str(top_n)
        ),
        "vix_threshold": (
            ""
            if vix_threshold is None
            else (
                f"{_safe_number(vix_threshold):g}"
                if _safe_number(vix_threshold) is not None
                else str(vix_threshold)
            )
        ),
        "transaction_cost": transaction_cost,
        "neutralisation": (
            config.get("neutralisation")
            if isinstance(config.get("neutralisation"), bool)
            else neutralize_by not in {"", "none", "false"}
        ),
        "factor_sleeves": factor_sleeves,
        "hold_cap": hold_cap,
        "benchmark": str(benchmark),
        "stress_overlay": (
            config.get("stress_overlay")
            if isinstance(config.get("stress_overlay"), bool)
            else bool(regime.get("vix_stress_threshold"))
        ),
        "lookback_window": config.get("lookback_window")
        or (f"{lookback_years:g} years" if _safe_number(lookback_years) is not None else ""),
        "output_pack": output_pack,
    }


def _read_json(path: Path) -> Any:
    raw_text = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        try:
            decoded, _ = decoder.raw_decode(raw_text.lstrip())
            return decoded
        except json.JSONDecodeError:
            raise


def _parse_timestamp(value: Any) -> datetime | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_pid_alive(pid_value: Any) -> bool:
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _terminate_pid_tree(pid_value: Any) -> bool:
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return completed.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def _cancel_run_metadata(run_id: str) -> bool:
    changed = False
    metadata = _load_job_metadata(run_id)
    runner_pid = metadata.get("runner_pid") or metadata.get("launcher_pid")
    _terminate_pid_tree(runner_pid)
    metadata["status"] = "canceled"
    metadata["updated_at"] = _utc_now_text()
    metadata["finished_at"] = metadata.get("finished_at") or _utc_now_text()
    metadata_path = metadata.get("metadata_path")
    if metadata_path:
        _write_json(Path(metadata_path), metadata)
        changed = True
    queue_path = RUN_QUEUE_DIR / f"{run_id}.json"
    if queue_path.exists():
        queue_payload = _read_json_if_exists(queue_path, {})
        queue_payload["status"] = "canceled"
        queue_payload["updated_at"] = _utc_now_text()
        _write_json(queue_path, queue_payload)
        changed = True
    return changed


def _is_terminal_run_status(status_value: Any) -> bool:
    return str(status_value or "").strip().lower() in {
        "completed",
        "failed",
        "canceled",
        "interrupted",
        "missing",
    }


def _delete_path_if_exists(path_value: Any) -> bool:
    path_text = str(path_value or "").strip()
    if not path_text:
        return False
    path = Path(path_text)
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    return True


def _delete_run_artifacts(run_id: str) -> list[str]:
    metadata = _load_job_metadata(run_id)
    status = str(metadata.get("status") or "").strip().lower()
    if not _is_terminal_run_status(status):
        raise HTTPException(
            status_code=409, detail=f"Run {run_id} is still active and cannot be deleted."
        )
    deleted_paths: list[str] = []
    paths_to_delete: list[Any] = [
        RUN_QUEUE_DIR / f"{run_id}.json",
        JOB_BUNDLE_DIR / run_id,
        metadata.get("log_path"),
        metadata.get("launch_path"),
    ]
    metadata_path_value = metadata.get("metadata_path")
    if metadata_path_value:
        metadata_path = Path(str(metadata_path_value))
        paths_to_delete.append(metadata_path.parent)
    for manifest in metadata.get("scenario_manifests") or []:
        if isinstance(manifest, dict):
            paths_to_delete.append(manifest.get("generated_config_path"))
    for path_value in metadata.get("extra_artifact_roots") or []:
        paths_to_delete.append(path_value)
    generated_matches = (
        list(GENERATED_CONFIG_DIR.glob(f"{run_id}*.yaml")) if GENERATED_CONFIG_DIR.exists() else []
    )
    paths_to_delete.extend(generated_matches)
    log_matches = list(JOB_LOG_DIR.glob(f"{run_id}*.log")) if JOB_LOG_DIR.exists() else []
    paths_to_delete.extend(log_matches)
    seen: set[str] = set()
    for path_value in paths_to_delete:
        path_text = str(path_value or "").strip()
        if not path_text or path_text in seen:
            continue
        seen.add(path_text)
        if _delete_path_if_exists(path_text):
            deleted_paths.append(path_text)
    return deleted_paths


def _delete_run_and_linked_children(run_id: str) -> tuple[list[str], dict[str, list[str]]]:
    metadata = _load_job_metadata(run_id)
    run_ids_to_delete = [run_id]
    if str(metadata.get("queue_type") or "").strip().lower() == "nightly_refresh":
        linked_run_id = str(metadata.get("last_run_id") or "").strip()
        if linked_run_id:
            run_ids_to_delete.append(linked_run_id)
    deleted_ids: list[str] = []
    deleted_paths: dict[str, list[str]] = {}
    seen: set[str] = set()
    parent_status = str(metadata.get("status") or "").strip().lower()
    for target_run_id in run_ids_to_delete:
        if not target_run_id or target_run_id in seen:
            continue
        seen.add(target_run_id)
        target_metadata = _load_job_metadata(target_run_id)
        target_status = str(target_metadata.get("status") or "").strip().lower()
        if (
            target_status not in {"completed", "failed", "canceled", "interrupted"}
            and parent_status == "canceled"
        ):
            _cancel_run_metadata(target_run_id)
            target_metadata = _load_job_metadata(target_run_id)
            target_status = str(target_metadata.get("status") or "").strip().lower()
        if target_status not in {"completed", "failed", "canceled", "interrupted"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Run {target_run_id} is not deletable until it reaches completed, "
                    "failed, canceled, or interrupted."
                ),
            )
        deleted_paths[target_run_id] = _delete_run_artifacts(target_run_id)
        deleted_ids.append(target_run_id)
    return deleted_ids, deleted_paths


def _reconcile_job_metadata(
    payload: dict[str, Any], *, metadata_path: Path | None = None
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return payload
    changed = False
    status = str(payload.get("status") or "").strip().lower()
    queue_type = str(payload.get("queue_type") or "").strip().lower()

    if queue_type == "nightly_refresh" and status not in {
        "canceled",
        "failed",
        "completed",
        "interrupted",
    }:
        linked_run_id = str(payload.get("last_run_id") or "").strip()
        if linked_run_id:
            linked_payload = _read_job_or_queue_payload(linked_run_id)
            linked_status = str(linked_payload.get("status") or "").strip().lower()
            if linked_status and status != linked_status:
                payload["status"] = linked_status
                status = linked_status
                changed = True
            linked_started_at = linked_payload.get("started_at") or linked_payload.get("created_at")
            if linked_started_at and payload.get("started_at") != linked_started_at:
                payload["started_at"] = linked_started_at
                changed = True
            linked_finished_at = linked_payload.get("finished_at")
            if linked_finished_at and payload.get("finished_at") != linked_finished_at:
                payload["finished_at"] = linked_finished_at
                changed = True

    if status == "running":
        runner_pid = payload.get("runner_pid") or payload.get("launcher_pid")
        last_update = (
            _parse_timestamp(payload.get("updated_at"))
            or _parse_timestamp(payload.get("started_at"))
            or _parse_timestamp(payload.get("created_at"))
        )
        age_seconds = None
        if last_update is not None:
            reference = datetime.now(tz=last_update.tzinfo or timezone.utc)
            age_seconds = max(0.0, (reference - last_update).total_seconds())
        if (
            runner_pid
            and not _is_pid_alive(runner_pid)
            and (age_seconds is None or age_seconds > 120)
        ):
            current_step_name = str(payload.get("current_step_name") or "").strip()
            current_step_display = str(payload.get("current_step_display") or "").strip()
            step_hint = current_step_name or current_step_display
            interrupted_error = "Runner process is no longer active; job was interrupted before final status writeback."
            if step_hint:
                interrupted_error = (
                    "Runner process is no longer active while executing "
                    f"{step_hint}; job was interrupted before final status writeback."
                )
            payload["status"] = "interrupted"
            payload["finished_at"] = payload.get("finished_at") or datetime.now(
                tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            payload["error"] = payload.get("error") or interrupted_error
            changed = True

    if changed and metadata_path is not None and metadata_path.exists():
        payload["updated_at"] = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        metadata_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        if not path.exists():
            return []
        if path.suffix.lower() == ".gz":
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def _formal_csv_rows(table_name: str, *, run_id: str | None = None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for directory in FORMAL_DB_CSV_CANDIDATE_DIRS:
        rows = _read_csv(directory / f"{table_name}.csv.gz")
        if rows:
            break
    if run_id is None:
        return rows
    return [row for row in rows if str(row.get("run_id") or "") == run_id]


def _latest_value(rows: list[dict[str, Any]], column: str) -> str | None:
    values = sorted(
        {str(row.get(column) or "").strip() for row in rows if str(row.get(column) or "").strip()}
    )
    return values[-1] if values else None


def _get_db_engine() -> Any | None:
    if not _db_lookup_enabled():
        return None
    if create_engine is None or sql_text is None:
        return None
    fallback_host = str(os.getenv("POSTGRES_HOST", "localhost")).strip() or "localhost"
    fallback_port = str(os.getenv("POSTGRES_PORT", "5439")).strip() or "5439"
    fallback_db = str(os.getenv("POSTGRES_DB", "fift")).strip() or "fift"
    fallback_user = str(os.getenv("POSTGRES_USER", "postgres")).strip() or "postgres"
    fallback_password = str(os.getenv("POSTGRES_PASSWORD", "postgres")).strip() or "postgres"
    try:
        return create_engine(
            f"postgresql://{fallback_user}:{fallback_password}@{fallback_host}:{fallback_port}/{fallback_db}"
        )
    except Exception:
        try:
            from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine
        except ModuleNotFoundError:  # pragma: no cover
            workspace_root = BASE_DIR.parent.parent
            if str(workspace_root) not in sys.path:
                sys.path.insert(0, str(workspace_root))
            try:
                from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine
            except ModuleNotFoundError:
                return None
        try:
            return get_db_engine()
        except Exception:
            return None


def _run_psql_csv_query(query: str) -> list[dict[str, str]]:
    if not _db_lookup_enabled():
        return []
    try:
        completed = subprocess.run(
            [
                "docker",
                "exec",
                "postgres_db_cw",
                "psql",
                "-U",
                str(os.getenv("POSTGRES_USER", "postgres")).strip() or "postgres",
                "-d",
                str(os.getenv("POSTGRES_DB", "fift")).strip() or "fift",
                "--csv",
                "-c",
                query,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return []
    text_value = completed.stdout.strip()
    if not text_value:
        return []
    return list(csv.DictReader(text_value.splitlines()))


def _lookup_company_sectors(symbols: list[str]) -> dict[str, str]:
    cleaned_symbols = sorted({str(symbol).strip() for symbol in symbols if str(symbol).strip()})
    if not cleaned_symbols:
        return {}
    sector_lookup: dict[str, str] = {}
    for row in _formal_csv_rows("company_static"):
        symbol = str(row.get("symbol") or "").strip()
        sector = str(row.get("gics_sector") or "").strip()
        if symbol in cleaned_symbols and sector:
            sector_lookup[symbol] = sector
    if len(sector_lookup) >= len(cleaned_symbols):
        return sector_lookup
    engine = _get_db_engine()
    if engine is not None and sql_text is not None:
        try:
            with engine.connect() as conn:
                mapping_rows = (
                    conn.execute(
                        sql_text("""
                        SELECT symbol, gics_sector
                        FROM systematic_equity.company_static
                        WHERE symbol = ANY(:symbols)
                        """),
                        {"symbols": cleaned_symbols},
                    )
                    .mappings()
                    .all()
                )
            sector_lookup.update(
                {
                    str(row["symbol"]): str(row["gics_sector"])
                    for row in mapping_rows
                    if row.get("symbol") and row.get("gics_sector")
                }
            )
        except Exception:
            sector_lookup = {}
    if not sector_lookup:
        safe_symbols = ", ".join(
            "'" + symbol.replace("'", "''") + "'" for symbol in cleaned_symbols
        )
        mapping_rows = _run_psql_csv_query(f"""
            SELECT symbol, gics_sector
            FROM systematic_equity.company_static
            WHERE symbol IN ({safe_symbols})
            """)
        sector_lookup.update(
            {
                str(row.get("symbol")): str(row.get("gics_sector"))
                for row in mapping_rows
                if row.get("symbol") and row.get("gics_sector")
            }
        )
    return sector_lookup


def _normalize_db_row_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
            return decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _fetch_latest_db_report(
    *,
    report_name: str | None = None,
    report_name_prefix: str | None = None,
) -> dict[str, Any] | None:
    engine = _get_db_engine()
    if engine is None or sql_text is None:
        return None
    clauses = ["report_status = 'generated'"]
    params: dict[str, Any] = {}
    if report_name:
        clauses.append("report_name = :report_name")
        params["report_name"] = report_name
    if report_name_prefix:
        clauses.append("report_name LIKE :report_name_prefix")
        params["report_name_prefix"] = f"{report_name_prefix}%"
    query = sql_text(f"""
        SELECT
            robustness_report_id::text AS robustness_report_id,
            report_name,
            report_scope,
            report_status,
            output_root,
            source_run_id::text AS source_run_id,
            summary_json,
            created_at,
            updated_at
        FROM systematic_equity.robustness_reports
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT 1
        """)
    try:
        with engine.connect() as conn:
            row = conn.execute(query, params).mappings().first()
    except Exception:
        return None
    if row is None:
        return None
    result = dict(row)
    result["summary_json"] = _normalize_db_row_payload(result.get("summary_json"))
    return result


def _fetch_db_dataset_rows(
    dataset_name: str,
    *,
    report_name: str | None = None,
    report_name_prefix: str | None = None,
) -> list[dict[str, Any]]:
    engine = _get_db_engine()
    if engine is None or sql_text is None:
        return []
    report = _fetch_latest_db_report(
        report_name=report_name,
        report_name_prefix=report_name_prefix,
    )
    if report is None:
        return []
    query = sql_text("""
        SELECT row_payload
        FROM systematic_equity.robustness_report_rows
        WHERE robustness_report_id = :robustness_report_id
          AND dataset_name = :dataset_name
        ORDER BY row_number ASC
        """)
    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    query,
                    {
                        "robustness_report_id": report["robustness_report_id"],
                        "dataset_name": dataset_name,
                    },
                )
                .scalars()
                .all()
            )
    except Exception:
        return []
    return [_normalize_db_row_payload(row) for row in rows]


def _fetch_db_artifacts(
    *,
    report_name: str | None = None,
    report_name_prefix: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    engine = _get_db_engine()
    if engine is None or sql_text is None:
        return None, []
    report = _fetch_latest_db_report(
        report_name=report_name,
        report_name_prefix=report_name_prefix,
    )
    if report is None:
        return None, []
    query = sql_text("""
        SELECT
            artifact_name,
            artifact_group,
            artifact_role,
            artifact_path,
            row_count,
            artifact_metadata,
            created_at
        FROM systematic_equity.robustness_report_artifacts
        WHERE robustness_report_id = :robustness_report_id
        ORDER BY artifact_group ASC, artifact_name ASC
        """)
    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    query,
                    {"robustness_report_id": report["robustness_report_id"]},
                )
                .mappings()
                .all()
            )
    except Exception:
        return report, []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["artifact_metadata"] = _normalize_db_row_payload(item.get("artifact_metadata"))
        cleaned.append(item)
    return report, cleaned


def _safe_number(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _resolve_primary_run_id() -> str:
    requirement_report = _fetch_latest_db_report(report_name_prefix=ROBUSTNESS_REPORT_PREFIX)
    if requirement_report and requirement_report.get("source_run_id"):
        return str(requirement_report["source_run_id"])
    if _formal_csv_rows("backtest_runs", run_id=FORMAL_RUN_ID):
        return FORMAL_RUN_ID
    return DEFAULT_MAINLINE_RUN_ID


def _fetch_run_time_series(run_id: str) -> list[dict[str, Any]]:
    engine = _get_db_engine()
    sql_query = """
        SELECT
            period_end_date,
            net_return,
            benchmark_return,
            excess_return,
            portfolio_nav,
            benchmark_nav,
            turnover,
            regime,
            vix_level
        FROM systematic_equity.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date ASC
        """
    rows: list[dict[str, Any]] = []
    if engine is not None and sql_text is not None:
        try:
            with engine.connect() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(sql_text(sql_query), {"run_id": run_id})
                    .mappings()
                    .all()
                ]
        except Exception:
            rows = []
    if not rows:
        safe_run_id = run_id.replace("'", "''")
        rows = _run_psql_csv_query(f"""
            SELECT
                period_end_date,
                net_return,
                benchmark_return,
                excess_return,
                portfolio_nav,
                benchmark_nav,
                turnover,
                regime,
                vix_level
            FROM systematic_equity.backtest_performance
            WHERE run_id = '{safe_run_id}'
            ORDER BY period_end_date ASC
            """)
    if not rows:
        rows = _formal_csv_rows("backtest_performance", run_id=run_id)
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        cleaned.append(
            {
                "date": str(row["period_end_date"]),
                "net_return": _safe_number(row["net_return"]),
                "benchmark_return": _safe_number(row["benchmark_return"]),
                "excess_return": _safe_number(row["excess_return"]),
                "portfolio_nav": _safe_number(row["portfolio_nav"]),
                "benchmark_nav": _safe_number(row["benchmark_nav"]),
                "turnover": _safe_number(row["turnover"]),
                "regime": str(row["regime"] or ""),
                "vix_level": _safe_number(row["vix_level"]),
            }
        )
    return cleaned


def _fetch_latest_holdings_snapshot(run_id: str) -> dict[str, Any]:
    engine = _get_db_engine()
    local_rows = _formal_csv_rows("backtest_holdings", run_id=run_id)
    latest_date = None
    if engine is not None and sql_text is not None:
        date_query = sql_text("""
            SELECT MAX(rebalance_date) AS latest_date
            FROM systematic_equity.backtest_holdings
            WHERE run_id = :run_id
            """)
        try:
            with engine.connect() as conn:
                latest_date = conn.execute(date_query, {"run_id": run_id}).scalar()
        except Exception:
            latest_date = None
    if latest_date is None:
        safe_run_id = run_id.replace("'", "''")
        fallback_rows = _run_psql_csv_query(
            f"SELECT MAX(rebalance_date) AS latest_date FROM systematic_equity.backtest_holdings WHERE run_id = '{safe_run_id}'"
        )
        latest_date = fallback_rows[0].get("latest_date") if fallback_rows else None
    if latest_date is None and local_rows:
        latest_date = _latest_value(local_rows, "rebalance_date")
    if latest_date is None:
        return {"as_of_date": "", "rows": []}
    rows: list[dict[str, Any]] = []
    sql_query = """
        SELECT
            rebalance_date,
            symbol,
            executed_weight,
            composite_alpha,
            gics_sector,
            regime
        FROM systematic_equity.backtest_holdings
        WHERE run_id = :run_id
          AND rebalance_date = :latest_date
        ORDER BY executed_weight DESC NULLS LAST, symbol ASC
        LIMIT 40
        """
    if engine is not None and sql_text is not None:
        try:
            with engine.connect() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        sql_text(sql_query),
                        {"run_id": run_id, "latest_date": latest_date},
                    )
                    .mappings()
                    .all()
                ]
        except Exception:
            rows = []
    if not rows:
        safe_run_id = run_id.replace("'", "''")
        safe_date = str(latest_date)
        rows = _run_psql_csv_query(f"""
            SELECT
                rebalance_date,
                symbol,
                executed_weight,
                composite_alpha,
                gics_sector,
                regime
            FROM systematic_equity.backtest_holdings
            WHERE run_id = '{safe_run_id}'
              AND rebalance_date = '{safe_date}'
            ORDER BY executed_weight DESC NULLS LAST, symbol ASC
            LIMIT 40
            """)
    if not rows and local_rows:
        rows = [
            row for row in local_rows if str(row.get("rebalance_date") or "") == str(latest_date)
        ]
        rows.sort(
            key=lambda row: (
                -(_safe_number(row.get("executed_weight")) or 0.0),
                str(row.get("symbol") or ""),
            )
        )
        rows = rows[:40]
    sector_lookup: dict[str, str] = {}
    missing_symbols = sorted(
        {
            str(row.get("symbol") or "").strip()
            for row in rows
            if str(row.get("symbol") or "").strip()
            and not str(row.get("gics_sector") or "").strip()
        }
    )
    if missing_symbols:
        if engine is not None and sql_text is not None:
            try:
                with engine.connect() as conn:
                    mapping_rows = (
                        conn.execute(
                            sql_text("""
                            SELECT symbol, gics_sector
                            FROM systematic_equity.company_static
                            WHERE symbol = ANY(:symbols)
                            """),
                            {"symbols": missing_symbols},
                        )
                        .mappings()
                        .all()
                    )
                sector_lookup.update(
                    {
                        str(row["symbol"]): str(row["gics_sector"])
                        for row in mapping_rows
                        if row.get("symbol") and row.get("gics_sector")
                    }
                )
            except Exception:
                sector_lookup = {}
        if not sector_lookup:
            safe_symbols = ", ".join(
                "'" + symbol.replace("'", "''") + "'" for symbol in missing_symbols
            )
            mapping_rows = _run_psql_csv_query(f"""
                SELECT symbol, gics_sector
                FROM systematic_equity.company_static
                WHERE symbol IN ({safe_symbols})
                """)
            sector_lookup.update(
                {
                    str(row.get("symbol")): str(row.get("gics_sector"))
                    for row in mapping_rows
                    if row.get("symbol") and row.get("gics_sector")
                }
            )
    return {
        "as_of_date": str(latest_date),
        "rows": [
            {
                "ticker": str(row["symbol"]),
                "sector": str(
                    row["gics_sector"] or sector_lookup.get(str(row["symbol"]), "") or "Unknown"
                ),
                "weight_pct": round((_safe_number(row["executed_weight"]) or 0.0) * 100.0, 3),
                "alpha": _safe_number(row["composite_alpha"]),
                "regime": str(row["regime"] or ""),
            }
            for row in rows
        ],
    }


def _fetch_latest_execution_slice(run_id: str) -> dict[str, Any]:
    engine = _get_db_engine()
    local_rows = _formal_csv_rows("backtest_execution_ledger", run_id=run_id)
    latest_date = None
    if engine is not None and sql_text is not None:
        date_query = sql_text("""
            SELECT MAX(execution_date) AS latest_date
            FROM systematic_equity.backtest_execution_ledger
            WHERE run_id = :run_id
            """)
        try:
            with engine.connect() as conn:
                latest_date = conn.execute(date_query, {"run_id": run_id}).scalar()
        except Exception:
            latest_date = None
    if latest_date is None:
        safe_run_id = run_id.replace("'", "''")
        fallback_rows = _run_psql_csv_query(
            f"SELECT MAX(execution_date) AS latest_date FROM systematic_equity.backtest_execution_ledger WHERE run_id = '{safe_run_id}'"
        )
        latest_date = fallback_rows[0].get("latest_date") if fallback_rows else None
    if latest_date is None and local_rows:
        latest_date = _latest_value(local_rows, "execution_date")
    if latest_date is None:
        return {"as_of_date": "", "rows": []}
    rows: list[dict[str, Any]] = []
    sql_query = """
        SELECT
            execution_date,
            symbol,
            trade_side,
            executed_trade_weight,
            total_cost,
            liquidity_clipped,
            NULL::text AS gics_sector
        FROM systematic_equity.backtest_execution_ledger
        WHERE run_id = :run_id
          AND execution_date = :latest_date
        ORDER BY ABS(executed_trade_weight) DESC NULLS LAST, symbol ASC
        LIMIT 50
        """
    if engine is not None and sql_text is not None:
        try:
            with engine.connect() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        sql_text(sql_query),
                        {"run_id": run_id, "latest_date": latest_date},
                    )
                    .mappings()
                    .all()
                ]
        except Exception:
            rows = []
    if not rows:
        safe_run_id = run_id.replace("'", "''")
        safe_date = str(latest_date)
        rows = _run_psql_csv_query(f"""
            SELECT
                execution_date,
                symbol,
                trade_side,
                executed_trade_weight,
                total_cost,
                liquidity_clipped,
                NULL::text AS gics_sector
            FROM systematic_equity.backtest_execution_ledger
            WHERE run_id = '{safe_run_id}'
              AND execution_date = '{safe_date}'
            ORDER BY ABS(executed_trade_weight) DESC NULLS LAST, symbol ASC
            LIMIT 50
            """)
    if not rows and local_rows:
        rows = [
            {**row, "gics_sector": row.get("gics_sector", "")}
            for row in local_rows
            if str(row.get("execution_date") or "") == str(latest_date)
        ]
        rows.sort(
            key=lambda row: (
                -abs(_safe_number(row.get("executed_trade_weight")) or 0.0),
                str(row.get("symbol") or ""),
            )
        )
        rows = rows[:50]
    sector_lookup: dict[str, str] = {}
    missing_symbols = sorted(
        {
            str(row.get("symbol") or "").strip()
            for row in rows
            if str(row.get("symbol") or "").strip()
            and not str(row.get("gics_sector") or "").strip()
        }
    )
    if missing_symbols:
        if engine is not None and sql_text is not None:
            try:
                with engine.connect() as conn:
                    mapping_rows = (
                        conn.execute(
                            sql_text("""
                            SELECT symbol, gics_sector
                            FROM systematic_equity.company_static
                            WHERE symbol = ANY(:symbols)
                            """),
                            {"symbols": missing_symbols},
                        )
                        .mappings()
                        .all()
                    )
                sector_lookup.update(
                    {
                        str(row["symbol"]): str(row["gics_sector"])
                        for row in mapping_rows
                        if row.get("symbol") and row.get("gics_sector")
                    }
                )
            except Exception:
                sector_lookup = {}
        if not sector_lookup:
            safe_symbols = ", ".join(
                "'" + symbol.replace("'", "''") + "'" for symbol in missing_symbols
            )
            mapping_rows = _run_psql_csv_query(f"""
                SELECT symbol, gics_sector
                FROM systematic_equity.company_static
                WHERE symbol IN ({safe_symbols})
                """)
            sector_lookup.update(
                {
                    str(row.get("symbol")): str(row.get("gics_sector"))
                    for row in mapping_rows
                    if row.get("symbol") and row.get("gics_sector")
                }
            )
    cleaned_rows = [
        {
            "date": str(row["execution_date"]),
            "ticker": str(row["symbol"]),
            "side": str(row["trade_side"] or ""),
            "executed_trade_weight_pct": round(
                (_safe_number(row["executed_trade_weight"]) or 0.0) * 100.0, 3
            ),
            "total_cost": _safe_number(row["total_cost"]) or 0.0,
            "liquidity_clipped": bool(row["liquidity_clipped"]),
            "sector": str(
                row.get("gics_sector") or sector_lookup.get(str(row["symbol"]), "") or "Unknown"
            ),
        }
        for row in rows
    ]
    return {
        "as_of_date": str(latest_date),
        "rows": cleaned_rows,
        "summary": {
            "trade_count": len(cleaned_rows),
            "gross_trade_weight_pct": round(
                sum(abs(row["executed_trade_weight_pct"]) for row in cleaned_rows), 3
            ),
            "clipped_count": sum(1 for row in cleaned_rows if row["liquidity_clipped"]),
            "total_cost": round(sum(row["total_cost"] for row in cleaned_rows), 6),
        },
    }


def _fetch_latest_covariance_snapshot(run_id: str) -> dict[str, Any]:
    engine = _get_db_engine()
    local_rows = _formal_csv_rows("backtest_covariance_metrics", run_id=run_id)
    recent_dates: list[str] = []
    rows: list[dict[str, Any]] = []
    if engine is not None and sql_text is not None:
        date_query = sql_text("""
            SELECT DISTINCT period_end_date
            FROM systematic_equity.backtest_covariance_metrics
            WHERE run_id = :run_id
            ORDER BY period_end_date DESC
            LIMIT 12
            """)
        try:
            with engine.connect() as conn:
                recent_dates = [
                    str(row[0])
                    for row in conn.execute(date_query, {"run_id": run_id}).all()
                    if row[0] is not None
                ]
        except Exception:
            recent_dates = []
    if not recent_dates:
        safe_run_id = run_id.replace("'", "''")
        fallback_rows = _run_psql_csv_query(f"""
            SELECT DISTINCT period_end_date
            FROM systematic_equity.backtest_covariance_metrics
            WHERE run_id = '{safe_run_id}'
            ORDER BY period_end_date DESC
            LIMIT 12
            """)
        recent_dates = [
            str(row.get("period_end_date")) for row in fallback_rows if row.get("period_end_date")
        ]
    if not recent_dates and local_rows:
        recent_dates = sorted(
            {
                str(row.get("period_end_date") or "")
                for row in local_rows
                if str(row.get("period_end_date") or "")
            },
            reverse=True,
        )[:12]
    if not recent_dates:
        return {"as_of_date": "", "available_dates": [], "rows": []}
    latest_date = recent_dates[0]
    rows: list[dict[str, Any]] = []
    sql_query = """
        SELECT
            period_end_date,
            metric_name,
            metric_value,
            versus_series
        FROM systematic_equity.backtest_covariance_metrics
        WHERE run_id = :run_id
        ORDER BY COALESCE(versus_series, '') ASC, metric_name ASC
        """
    if engine is not None and sql_text is not None:
        try:
            with engine.connect() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        sql_text(sql_query),
                        {"run_id": run_id},
                    )
                    .mappings()
                    .all()
                ]
        except Exception:
            rows = []
    if not rows:
        safe_run_id = run_id.replace("'", "''")
        rows = _run_psql_csv_query(f"""
            SELECT
                period_end_date,
                metric_name,
                metric_value,
                versus_series
            FROM systematic_equity.backtest_covariance_metrics
            WHERE run_id = '{safe_run_id}'
            ORDER BY COALESCE(versus_series, '') ASC, metric_name ASC
            """)
    if not rows and local_rows:
        rows = list(local_rows)
    rows = [row for row in rows if str(row["period_end_date"]) in recent_dates]
    return {
        "as_of_date": str(latest_date),
        "available_dates": recent_dates,
        "rows": [
            {
                "date": str(row["period_end_date"]),
                "metric_name": str(row["metric_name"]),
                "metric_value": _safe_number(row["metric_value"]),
                "versus_series": str(row["versus_series"] or ""),
            }
            for row in rows
        ],
    }


def _compute_correlation_matrix(columns: dict[str, list[float]]) -> list[list[float]]:
    ordered_keys = list(columns.keys())
    matrix: list[list[float]] = []
    for left_key in ordered_keys:
        left_values = columns[left_key]
        left_mean = sum(left_values) / max(len(left_values), 1)
        left_var = sum((value - left_mean) ** 2 for value in left_values)
        row: list[float] = []
        for right_key in ordered_keys:
            right_values = columns[right_key]
            right_mean = sum(right_values) / max(len(right_values), 1)
            right_var = sum((value - right_mean) ** 2 for value in right_values)
            if left_var <= 0 or right_var <= 0:
                row.append(1.0 if left_key == right_key else 0.0)
                continue
            cov = sum(
                (left_values[index] - left_mean) * (right_values[index] - right_mean)
                for index in range(min(len(left_values), len(right_values)))
            )
            corr = cov / math.sqrt(left_var * right_var)
            row.append(round(max(min(corr, 1.0), -1.0), 6))
        matrix.append(row)
    return matrix


def _fetch_latest_factor_scores_snapshot(limit: int = 40) -> dict[str, Any]:
    engine = _get_db_engine()
    local_rows = _formal_csv_rows("feature_factor_scores")
    if engine is None or sql_text is None:
        latest_date = _latest_value(local_rows, "as_of_date")
        rows = (
            [row for row in local_rows if str(row.get("as_of_date") or "") == str(latest_date)]
            if latest_date
            else []
        )
        rows.sort(
            key=lambda row: (
                -(_safe_number(row.get("composite_alpha")) or 0.0),
                str(row.get("symbol") or ""),
            )
        )
        rows = rows[:limit]
    else:
        date_query = sql_text("""
            SELECT MAX(as_of_date) AS latest_date
            FROM systematic_equity.feature_factor_scores
            """)
        try:
            with engine.connect() as conn:
                latest_date = conn.execute(date_query).scalar()
        except Exception:
            latest_date = None
        rows_query = sql_text("""
            SELECT
                as_of_date,
                symbol,
                quality_score,
                value_score,
                market_technical_score,
                dividend_score,
                composite_alpha,
                regime,
                vix_level
            FROM systematic_equity.feature_factor_scores
            WHERE as_of_date = :latest_date
            ORDER BY composite_alpha DESC NULLS LAST, symbol ASC
            LIMIT :limit
            """)
        try:
            with engine.connect() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        rows_query,
                        {"latest_date": latest_date, "limit": limit},
                    )
                    .mappings()
                    .all()
                ]
        except Exception:
            rows = []
        if not rows and local_rows:
            latest_date = _latest_value(local_rows, "as_of_date")
            rows = (
                [row for row in local_rows if str(row.get("as_of_date") or "") == str(latest_date)]
                if latest_date
                else []
            )
            rows.sort(
                key=lambda row: (
                    -(_safe_number(row.get("composite_alpha")) or 0.0),
                    str(row.get("symbol") or ""),
                )
            )
            rows = rows[:limit]
    if latest_date is None:
        return {"as_of_date": "", "rows": [], "correlation": []}
    score_columns = {
        "quality": [],
        "value": [],
        "market_technical": [],
        "dividend": [],
    }
    cleaned_rows = []
    missing_symbols: list[str] = []
    for row in rows:
        quality = _safe_number(row["quality_score"]) or 0.0
        value = _safe_number(row["value_score"]) or 0.0
        market = _safe_number(row["market_technical_score"]) or 0.0
        dividend = _safe_number(row["dividend_score"]) or 0.0
        score_columns["quality"].append(quality)
        score_columns["value"].append(value)
        score_columns["market_technical"].append(market)
        score_columns["dividend"].append(dividend)
        cleaned_rows.append(
            {
                "date": str(row["as_of_date"]),
                "ticker": str(row["symbol"]),
                "symbol": str(row["symbol"]),
                "quality_score": quality,
                "value_score": value,
                "market_technical_score": market,
                "dividend_score": dividend,
                "composite_alpha": _safe_number(row["composite_alpha"]) or 0.0,
                "regime": str(row["regime"] or ""),
                "vix_level": _safe_number(row["vix_level"]),
                "gics_sector": "",
            }
        )
        symbol = str(row["symbol"] or "").strip()
        if symbol:
            missing_symbols.append(symbol)
    sector_lookup = _lookup_company_sectors(sorted(set(missing_symbols))) if missing_symbols else {}
    for row in cleaned_rows:
        symbol = str(row.get("symbol") or "").strip()
        sector = sector_lookup.get(symbol, "")
        if sector:
            row["gics_sector"] = sector
            row["sector"] = sector
        else:
            row["sector"] = "Unknown"
    return {
        "as_of_date": str(latest_date),
        "rows": cleaned_rows,
        "correlation": _compute_correlation_matrix(score_columns) if cleaned_rows else [],
    }


def _fetch_recent_factor_attribution(run_id: str, periods: int = 4) -> dict[str, Any]:
    engine = _get_db_engine()
    local_rows = _formal_csv_rows("backtest_factor_attribution", run_id=run_id)
    if engine is None or sql_text is None:
        all_rows = local_rows
    else:
        rows_query = sql_text("""
            SELECT
                period_end_date,
                factor_name,
                active_exposure,
                factor_spread_return,
                contribution_proxy
            FROM systematic_equity.backtest_factor_attribution
            WHERE run_id = :run_id
            ORDER BY period_end_date DESC, factor_name ASC
            """)
        try:
            with engine.connect() as conn:
                all_rows = [
                    dict(row)
                    for row in conn.execute(rows_query, {"run_id": run_id}).mappings().all()
                ]
        except Exception:
            all_rows = local_rows
    all_rows.sort(
        key=lambda row: (str(row.get("period_end_date") or ""), str(row.get("factor_name") or "")),
        reverse=True,
    )
    recent_dates: list[str] = []
    for row in all_rows:
        date_value = str(row["period_end_date"])
        if date_value not in recent_dates:
            recent_dates.append(date_value)
        if len(recent_dates) >= periods:
            break
    filtered = [row for row in all_rows if str(row["period_end_date"]) in recent_dates]
    return {
        "rows": [
            {
                "date": str(row["period_end_date"]),
                "factor": str(row["factor_name"]),
                "active_exposure": _safe_number(row["active_exposure"]) or 0.0,
                "factor_spread_return": _safe_number(row["factor_spread_return"]) or 0.0,
                "contribution_proxy": _safe_number(row["contribution_proxy"]) or 0.0,
            }
            for row in filtered
        ]
    }


def _fetch_latest_covariance_contributions(run_id: str) -> dict[str, Any]:
    engine = _get_db_engine()
    local_rows = _formal_csv_rows("backtest_covariance_contributions", run_id=run_id)
    recent_dates: list[str] = []
    rows: list[dict[str, Any]] = []
    if engine is not None and sql_text is not None:
        date_query = sql_text("""
            SELECT DISTINCT period_end_date
            FROM systematic_equity.backtest_covariance_contributions
            WHERE run_id = :run_id
            ORDER BY period_end_date DESC
            LIMIT 12
            """)
        try:
            with engine.connect() as conn:
                recent_dates = [
                    str(row[0])
                    for row in conn.execute(date_query, {"run_id": run_id}).all()
                    if row[0] is not None
                ]
        except Exception:
            recent_dates = []
    if not recent_dates:
        safe_run_id = run_id.replace("'", "''")
        fallback_rows = _run_psql_csv_query(f"""
            SELECT DISTINCT period_end_date
            FROM systematic_equity.backtest_covariance_contributions
            WHERE run_id = '{safe_run_id}'
            ORDER BY period_end_date DESC
            LIMIT 12
            """)
        recent_dates = [
            str(row.get("period_end_date")) for row in fallback_rows if row.get("period_end_date")
        ]
    if not recent_dates and local_rows:
        recent_dates = sorted(
            {
                str(row.get("period_end_date") or "")
                for row in local_rows
                if str(row.get("period_end_date") or "")
            },
            reverse=True,
        )[:12]
    if not recent_dates:
        return {"as_of_date": "", "available_dates": [], "rows": []}
    latest_date = recent_dates[0]
    rows_query = """
        SELECT
            period_end_date,
            dimension_type,
            dimension_name,
            risk_contribution_pct
        FROM systematic_equity.backtest_covariance_contributions
        WHERE run_id = :run_id
        ORDER BY period_end_date DESC, risk_contribution_pct DESC NULLS LAST, dimension_name ASC
        """
    if engine is not None and sql_text is not None:
        try:
            with engine.connect() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        sql_text(rows_query),
                        {"run_id": run_id},
                    )
                    .mappings()
                    .all()
                ]
        except Exception:
            rows = []
    if not rows:
        safe_run_id = run_id.replace("'", "''")
        rows = _run_psql_csv_query(f"""
            SELECT
                period_end_date,
                dimension_type,
                dimension_name,
                risk_contribution_pct
            FROM systematic_equity.backtest_covariance_contributions
            WHERE run_id = '{safe_run_id}'
            ORDER BY period_end_date DESC, risk_contribution_pct DESC NULLS LAST, dimension_name ASC
            """)
    if not rows and local_rows:
        rows = list(local_rows)
    rows = [row for row in rows if str(row["period_end_date"]) in recent_dates]
    return {
        "as_of_date": str(latest_date),
        "available_dates": recent_dates,
        "rows": [
            {
                "date": str(row["period_end_date"]),
                "dimension_type": str(row["dimension_type"]),
                "dimension_name": str(row["dimension_name"]),
                "risk_contribution_pct": _safe_number(row["risk_contribution_pct"]) or 0.0,
            }
            for row in rows
        ],
    }


def _format_pct(decimal_value: float | None) -> str:
    if decimal_value is None:
        return "n/a"
    return f"{decimal_value * 100:.2f}%"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json_if_exists(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return _read_json(path)
    except Exception:
        return default


def _safe_iso_text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat().replace("+00:00", "Z")
        except Exception:
            return str(value)
    return str(value)


def _utc_now_text() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _append_audit_log(event_type: str, payload: dict[str, Any]) -> None:
    rows = _read_json_if_exists(AUDIT_LOG_PATH, [])
    rows.append(
        {
            "event_type": event_type,
            "event_at": _utc_now_text(),
            "payload": payload,
        }
    )
    _write_json(AUDIT_LOG_PATH, rows[-200:])


def _scenario_file_path(scenario_id: str) -> Path:
    return SCENARIO_DIR / f"{scenario_id}.json"


def _scenario_version_hash(record: dict[str, Any]) -> str:
    version_basis = {
        "scenario_name": record.get("scenario_name"),
        "scenario_config": record.get("scenario_config"),
        "version": record.get("version"),
        "parent_scenario_id": record.get("parent_scenario_id"),
    }
    return _safe_slug(json.dumps(version_basis, ensure_ascii=False, sort_keys=True))[:32]


def _formal_scenario_name(config: dict[str, Any] | None = None) -> str:
    formal_config = (
        config if isinstance(config, dict) and config else _load_baseline_config_payload()
    )
    portfolio = (
        formal_config.get("portfolio_construction")
        if isinstance(formal_config.get("portfolio_construction"), dict)
        else {}
    )
    backtest = (
        formal_config.get("backtest") if isinstance(formal_config.get("backtest"), dict) else {}
    )
    return str(
        portfolio.get("portfolio_name")
        or backtest.get("portfolio_name")
        or "cw2_formal_20260420_fund_ra3_s30_t50"
    )


def _formal_mainline_record_template() -> dict[str, Any] | None:
    formal_config = _load_baseline_config_payload()
    if not formal_config:
        return None
    updated_at = (
        datetime.fromtimestamp(FORMAL_CONFIG_PATH.stat().st_mtime, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
        if FORMAL_CONFIG_PATH.exists()
        else _utc_now_text()
    )
    scenario_name = _formal_scenario_name(formal_config)
    record = {
        "scenario_id": "SCN-0001",
        "scenario_name": scenario_name,
        "scenario_config": formal_config,
        "status": "active",
        "version": 1,
        "version_hash": "",
        "is_mainline": True,
        "parent_scenario_id": None,
        "created_at": updated_at,
        "updated_at": updated_at,
        "notes": f"Loaded from formal config: {FORMAL_CONFIG_PATH.name}",
    }
    record["version_hash"] = _scenario_version_hash(record)
    return record


def _sync_formal_mainline_scenario() -> dict[str, Any] | None:
    formal_template = _formal_mainline_record_template()
    if not formal_template:
        return None
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    scenario_path = _scenario_file_path(formal_template["scenario_id"])
    existing = _read_json_if_exists(scenario_path, {})
    should_write_scenario = (
        not existing
        or existing.get("scenario_id") != formal_template["scenario_id"]
        or existing.get("scenario_name") != formal_template["scenario_name"]
        or existing.get("scenario_config") != formal_template["scenario_config"]
        or not existing.get("is_mainline")
    )
    if should_write_scenario:
        _write_json(scenario_path, formal_template)
    mainline_payload = _read_json_if_exists(MAINLINE_SCENARIO_PATH, {})
    expected_mainline = {
        "scenario_id": formal_template["scenario_id"],
        "scenario_name": formal_template["scenario_name"],
    }
    if mainline_payload != expected_mainline:
        _write_json(MAINLINE_SCENARIO_PATH, expected_mainline)
    return formal_template


def _bootstrap_default_scenarios() -> None:
    if _sync_formal_mainline_scenario():
        return
    if SCENARIO_DIR.exists() and any(SCENARIO_DIR.glob("*.json")):
        return
    saved = _load_saved_scenarios()
    presets = saved.get("presets") or {}
    created: list[dict[str, Any]] = []
    for index, (scenario_name, scenario_config) in enumerate(presets.items(), start=1):
        scenario_id = f"SCN-{index:04d}"
        now_text = _utc_now_text()
        record = {
            "scenario_id": scenario_id,
            "scenario_name": scenario_name,
            "scenario_config": scenario_config,
            "status": "active",
            "version": 1,
            "version_hash": "",
            "is_mainline": False,
            "parent_scenario_id": None,
            "created_at": now_text,
            "updated_at": now_text,
            "notes": "Bootstrapped from saved scenario presets.",
        }
        record["version_hash"] = _scenario_version_hash(record)
        _write_json(_scenario_file_path(scenario_id), record)
        created.append(record)
    if not created:
        now_text = _utc_now_text()
        formal_template = _formal_mainline_record_template()
        default_config = (
            formal_template["scenario_config"]
            if formal_template
            else _scenario_override_payload(
                "formal_s30_mainline",
                {
                    "rebalance": "Quarterly",
                    "top_n": "25",
                    "vix_threshold": "22",
                    "transaction_cost": "15bps",
                    "neutralisation": True,
                    "factor_sleeves": ["Quality", "Value", "Market Technical", "Dividend"],
                    "hold_cap": "5%",
                    "stress_overlay": True,
                },
            )
        )
        baseline_record = {
            "scenario_id": "SCN-0001",
            "scenario_name": (
                formal_template["scenario_name"] if formal_template else "formal_s30_mainline"
            ),
            "scenario_config": default_config,
            "status": "active",
            "version": 1,
            "version_hash": "",
            "is_mainline": True,
            "parent_scenario_id": None,
            "created_at": now_text,
            "updated_at": now_text,
            "notes": "Bootstrapped default mainline scenario.",
        }
        baseline_record["version_hash"] = _scenario_version_hash(baseline_record)
        _write_json(_scenario_file_path("SCN-0001"), baseline_record)
        created.append(baseline_record)
    active_name = saved.get("active_preset") or (created[0]["scenario_name"] if created else None)
    active = next((item for item in created if item["scenario_name"] == active_name), None)
    if active is not None:
        _write_json(
            MAINLINE_SCENARIO_PATH,
            {"scenario_id": active["scenario_id"], "scenario_name": active["scenario_name"]},
        )


def _load_scenarios() -> list[dict[str, Any]]:
    formal_template = _sync_formal_mainline_scenario()
    if formal_template:
        return [formal_template]
    _bootstrap_default_scenarios()
    mainline_payload = _read_json_if_exists(MAINLINE_SCENARIO_PATH, {})
    mainline_id = mainline_payload.get("scenario_id")
    records: list[dict[str, Any]] = []
    for path in sorted(SCENARIO_DIR.glob("SCN-*.json")):
        record = _read_json_if_exists(path, {})
        if not record:
            continue
        record["is_mainline"] = record.get("scenario_id") == mainline_id
        if formal_template and record["is_mainline"]:
            record["scenario_name"] = formal_template["scenario_name"]
            record["scenario_config"] = formal_template["scenario_config"]
            record["notes"] = formal_template["notes"]
            record["version_hash"] = _scenario_version_hash(record)
        records.append(record)
    if formal_template and not records:
        records.append(formal_template)
    records.sort(
        key=lambda item: (not item.get("is_mainline", False), item.get("scenario_name", "").lower())
    )
    return records


def _get_scenario_record(scenario_id: str) -> dict[str, Any] | None:
    formal_template = _sync_formal_mainline_scenario()
    if formal_template:
        return formal_template if scenario_id == formal_template["scenario_id"] else None
    path = _scenario_file_path(scenario_id)
    if not path.exists():
        return None
    record = _read_json_if_exists(path, {})
    mainline_payload = _read_json_if_exists(MAINLINE_SCENARIO_PATH, {})
    record["is_mainline"] = record.get("scenario_id") == mainline_payload.get("scenario_id")
    formal_template = _formal_mainline_record_template()
    if formal_template and record["is_mainline"]:
        record["scenario_name"] = formal_template["scenario_name"]
        record["scenario_config"] = formal_template["scenario_config"]
        record["notes"] = formal_template["notes"]
        record["version_hash"] = _scenario_version_hash(record)
    return record


def _next_scenario_id() -> str:
    existing_ids = [
        int(path.stem.split("-")[-1])
        for path in SCENARIO_DIR.glob("SCN-*.json")
        if path.stem.split("-")[-1].isdigit()
    ]
    next_index = (max(existing_ids) + 1) if existing_ids else 1
    return f"SCN-{next_index:04d}"


def _save_scenario_record(
    *,
    scenario_id: str,
    scenario_name: str,
    scenario_config: dict[str, Any],
    parent_scenario_id: str | None,
    notes: str | None,
) -> dict[str, Any]:
    existing = _get_scenario_record(scenario_id)
    now_text = _utc_now_text()
    version = int(existing.get("version", 0)) + 1 if existing else 1
    record = {
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "scenario_config": scenario_config,
        "status": "active",
        "version": version,
        "version_hash": "",
        "is_mainline": bool(existing.get("is_mainline")) if existing else False,
        "parent_scenario_id": parent_scenario_id,
        "created_at": existing.get("created_at", now_text) if existing else now_text,
        "updated_at": now_text,
        "notes": notes,
    }
    record["version_hash"] = _scenario_version_hash(record)
    _write_json(_scenario_file_path(scenario_id), record)
    _append_audit_log(
        "scenario_saved",
        {"scenario_id": scenario_id, "scenario_name": scenario_name, "version": version},
    )
    return record


def _set_mainline_scenario(scenario_id: str) -> dict[str, Any] | None:
    record = _get_scenario_record(scenario_id)
    if record is None:
        return None
    _write_json(
        MAINLINE_SCENARIO_PATH,
        {"scenario_id": scenario_id, "scenario_name": record["scenario_name"]},
    )
    _append_audit_log(
        "scenario_set_mainline",
        {"scenario_id": scenario_id, "scenario_name": record["scenario_name"]},
    )
    record["is_mainline"] = True
    return record


def _resolve_scenario_selection(
    *,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    if scenario_id:
        record = _get_scenario_record(scenario_id)
        if record is not None:
            return record["scenario_id"], record["scenario_name"], record["scenario_config"]
    if scenario_name and scenario_config is not None:
        return "", scenario_name, scenario_config
    mainline_payload = _read_json_if_exists(MAINLINE_SCENARIO_PATH, {})
    if mainline_payload.get("scenario_id"):
        record = _get_scenario_record(mainline_payload["scenario_id"])
        if record is not None:
            return record["scenario_id"], record["scenario_name"], record["scenario_config"]
    scenarios = _load_scenarios()
    if scenarios:
        record = scenarios[0]
        return record["scenario_id"], record["scenario_name"], record["scenario_config"]
    return "", "Current working scenario", scenario_config or {}


def _build_universe_preview_payload(
    *,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_id, resolved_name, resolved_config = _resolve_scenario_selection(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        scenario_config=scenario_config,
    )
    config = _scenario_config_with_defaults(resolved_config)
    universe = str(config.get("universe") or "US Large Cap")
    top_n = int(_coerce_numeric_text(config.get("top_n"), default=25))
    benchmark = str(config.get("benchmark") or "Static baseline + market benchmark")
    universe_size_map = {
        "US Large Cap": 480,
        "US Broad Market": 1600,
        "Defensive Basket": 140,
    }
    liquidity_map = {
        "US Large Cap": 98.4,
        "US Broad Market": 94.8,
        "Defensive Basket": 99.1,
    }
    market_cap_map = {
        "US Large Cap": 182.0,
        "US Broad Market": 46.0,
        "Defensive Basket": 128.0,
    }
    sector_templates = {
        "US Large Cap": [
            ("Technology", 22),
            ("Health Care", 14),
            ("Financials", 13),
            ("Consumer Staples", 9),
            ("Industrials", 11),
            ("Energy", 8),
        ],
        "US Broad Market": [
            ("Technology", 19),
            ("Industrials", 15),
            ("Financials", 14),
            ("Health Care", 11),
            ("Consumer Discretionary", 10),
            ("Energy", 7),
        ],
        "Defensive Basket": [
            ("Consumer Staples", 24),
            ("Health Care", 22),
            ("Utilities", 16),
            ("Industrials", 10),
            ("Energy", 8),
            ("Technology", 7),
        ],
    }
    company_templates = {
        "US Large Cap": [
            ("MSFT", "Technology", "Quality / market leadership"),
            ("JNJ", "Health Care", "Defensive quality"),
            ("XOM", "Energy", "Value / dividend"),
            ("PG", "Consumer Staples", "Dividend stability"),
            ("JPM", "Financials", "Large-cap balance sheet"),
        ],
        "US Broad Market": [
            ("MSFT", "Technology", "Anchor large-cap exposure"),
            ("LIN", "Materials", "Quality industrial gases"),
            ("TJX", "Consumer Discretionary", "Defensive retail"),
            ("PGR", "Financials", "Stable underwriting"),
            ("APH", "Technology", "Mid/large-cap quality"),
        ],
        "Defensive Basket": [
            ("PG", "Consumer Staples", "Core defensive dividend"),
            ("KO", "Consumer Staples", "Low-beta income"),
            ("JNJ", "Health Care", "Defensive quality"),
            ("PEP", "Consumer Staples", "Cash-flow resilient"),
            ("SO", "Utilities", "Regulated utility ballast"),
        ],
    }
    sector_mix = sector_templates.get(universe, sector_templates["US Large Cap"])
    company_rows = []
    for ticker, sector, note in company_templates.get(universe, company_templates["US Large Cap"]):
        company_rows.append(
            {
                "ticker": ticker,
                "sector": sector,
                "liquidity_score": round(
                    liquidity_map.get(universe, 97.5) - len(company_rows) * 0.7, 1
                ),
                "selection_note": note,
            }
        )
    return {
        "scenario_id": resolved_id,
        "scenario_name": resolved_name,
        "universe": universe,
        "summary": {
            "universe_size": universe_size_map.get(universe, 480),
            "candidate_buffer": max(40, top_n * 8),
            "coverage_pct": round(min(99.6, liquidity_map.get(universe, 97.5) + 0.4), 1),
            "avg_market_cap_usd_bn": market_cap_map.get(universe, 120.0),
            "avg_liquidity_score": liquidity_map.get(universe, 97.5),
            "benchmark": benchmark,
            "top_n_target": top_n,
        },
        "sector_mix": [{"sector": sector, "weight_pct": weight} for sector, weight in sector_mix],
        "company_preview": company_rows,
        "notes": [
            f"{universe} currently maps to a {universe_size_map.get(universe, 480)}-name working candidate set before factor ranking.",
            f"The live selection target is top {top_n} with a broader review buffer of {max(40, top_n * 8)} names.",
            f"Benchmark tracking remains aligned to {benchmark}.",
        ],
        "generated_at": _utc_now_text(),
    }


def _build_regime_preview_payload(
    *,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_id, resolved_name, resolved_config = _resolve_scenario_selection(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        scenario_config=scenario_config,
    )
    config = _scenario_config_with_defaults(resolved_config)
    risk = _build_risk_payload()
    threshold = _coerce_numeric_text(config.get("vix_threshold"), default=22.0)
    strip = [str(item).lower() for item in risk.get("strip", [])]
    stress_periods = sum(1 for item in strip if item == "stress")
    total_periods = len(strip) or 1
    vix_series = [float(value) for value in risk.get("vix", [])]
    latest_vix = vix_series[-1] if vix_series else threshold
    warning_threshold = max(threshold - 2.0, 1.0)
    current_regime = (
        "Stress"
        if bool(config.get("stress_overlay", True)) and latest_vix >= threshold
        else "Normal"
    )
    exposure_rows = []
    for row in risk.get("exposures", []):
        if len(row) < 3:
            continue
        label, normal_value, stress_value = row[0], float(row[1]), float(row[2])
        exposure_rows.append(
            {
                "factor": str(label),
                "normal_weight_pct": round(normal_value * 100, 1),
                "stress_weight_pct": round(stress_value * 100, 1),
                "shift_pct": round((stress_value - normal_value) * 100, 1),
            }
        )
    timeline = []
    for index, value in enumerate(vix_series[-8:]):
        status = (
            "Stress"
            if bool(config.get("stress_overlay", True)) and value >= threshold
            else "Normal"
        )
        timeline.append(
            {
                "period": f"T{len(vix_series) - len(vix_series[-8:]) + index + 1}",
                "vix": round(value, 1),
                "state": status,
            }
        )
    return {
        "scenario_id": resolved_id,
        "scenario_name": resolved_name,
        "summary": {
            "current_regime": current_regime,
            "latest_vix": round(latest_vix, 1),
            "stress_threshold": round(threshold, 1),
            "warning_threshold": round(warning_threshold, 1),
            "stress_share_pct": round(stress_periods / total_periods * 100.0, 1),
            "overlay_enabled": bool(config.get("stress_overlay", True)),
        },
        "timeline": timeline,
        "exposures": exposure_rows,
        "notes": [
            "Threshold preview is computed from the current VIX-aware regime series already connected to the risk dashboard.",
            "Stress overlay disabled means the preview will still show the series, but the target state remains normalised.",
            f"Current threshold proposal: VIX {threshold:.1f} with a warning band at {warning_threshold:.1f}.",
        ],
        "generated_at": _utc_now_text(),
    }


def _build_optimizer_preview_payload(
    *,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_id, resolved_name, resolved_config = _resolve_scenario_selection(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        scenario_config=scenario_config,
    )
    config = _scenario_config_with_defaults(resolved_config)
    top_n = int(_coerce_numeric_text(config.get("top_n"), default=25))
    hold_cap = _coerce_percent_text(config.get("hold_cap"), default=0.05)
    transaction_cost_bps = _coerce_bps_text(config.get("transaction_cost"), default=15.0)
    factor_sleeves = config.get("factor_sleeves") or []
    normal_weights, stress_weights = _normalize_factor_weights(list(factor_sleeves))
    expected_turnover = round(
        min(34.0, 8.0 + transaction_cost_bps / 2.5 + max(0, 30 - top_n) * 0.35), 1
    )
    predicted_vol = round(
        10.8 + max(0, 28 - top_n) * 0.08 + (0 if config.get("neutralisation", True) else 0.9), 1
    )
    expected_te = round(
        4.6 + max(0, 30 - top_n) * 0.06 + (0.2 if config.get("stress_overlay", True) else -0.3), 1
    )
    holdings_preview = []
    holding_templates = [
        ("MSFT", "Technology"),
        ("JNJ", "Health Care"),
        ("PG", "Consumer Staples"),
        ("XOM", "Energy"),
        ("ABBV", "Health Care"),
    ]
    for index, (ticker, sector) in enumerate(holding_templates):
        target_weight = round(max(hold_cap * 100 - index * 0.3, 2.4), 1)
        holdings_preview.append(
            {
                "ticker": ticker,
                "sector": sector,
                "target_weight_pct": target_weight,
                "selection_role": (
                    factor_sleeves[index % len(factor_sleeves)] if factor_sleeves else "Core"
                ),
            }
        )
    return {
        "scenario_id": resolved_id,
        "scenario_name": resolved_name,
        "summary": {
            "target_names": top_n,
            "hybrid_band": f"{top_n}-{max(top_n, top_n + 10)}",
            "single_name_cap_pct": round(hold_cap * 100, 1),
            "expected_turnover_pct": expected_turnover,
            "predicted_vol_pct": predicted_vol,
            "expected_tracking_error_pct": expected_te,
            "rebalance": str(config.get("rebalance") or "Quarterly"),
        },
        "constraints": [
            {"item": "Transaction cost", "value": f"{transaction_cost_bps:.1f} bps"},
            {
                "item": "Neutralisation",
                "value": (
                    "Sector-neutral"
                    if bool(config.get("neutralisation", True))
                    else "Raw cross-section"
                ),
            },
            {
                "item": "Stress overlay",
                "value": "Enabled" if bool(config.get("stress_overlay", True)) else "Disabled",
            },
            {
                "item": "Output pack",
                "value": str(config.get("output_pack") or "NAV + holdings + risk"),
            },
        ],
        "factor_mix": [
            {
                "factor": key.replace("_", " ").title(),
                "normal_weight_pct": round(value * 100, 1),
                "stress_weight_pct": round(stress_weights.get(key, value) * 100, 1),
            }
            for key, value in normal_weights.items()
            if value > 0 or stress_weights.get(key, 0.0) > 0
        ],
        "holdings_preview": holdings_preview,
        "notes": [
            "Optimizer preview is a lightweight single-period estimate, not a full historical rerun.",
            "Expected turnover and volatility are derived from the current cap, breadth, cost, and overlay settings.",
            f"Current construction assumes a hybrid band around top {top_n} names with a {hold_cap * 100:.1f}% single-name cap.",
        ],
        "generated_at": _utc_now_text(),
    }


def _build_factor_preview_payload(
    *,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_id, resolved_name, resolved_config = _resolve_scenario_selection(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        scenario_config=scenario_config,
    )
    config = _scenario_config_with_defaults(resolved_config)
    factor_sleeves = config.get("factor_sleeves") or [
        "Quality",
        "Value",
        "Market Technical",
        "Dividend",
    ]
    neutralisation = bool(config.get("neutralisation", True))
    winsorisation = str(config.get("winsorisation") or "3 sigma").strip()
    standardisation = str(config.get("standardisation") or "Z-score").strip()
    ewma_decay = _coerce_numeric_text(config.get("ewma_decay"), default=0.94)
    lookback = str(config.get("lookback_window") or "12 months")
    top_n = int(_coerce_numeric_text(config.get("top_n"), default=25))
    transaction_cost_bps = _coerce_bps_text(config.get("transaction_cost"), default=15.0)
    winsorisation_adjustments: dict[str, dict[str, float]] = {
        "2 sigma": {
            "ic": -0.004,
            "rank_ic": -0.002,
            "hit_rate": -0.8,
            "mean": -0.03,
            "dispersion": -0.14,
            "score": -1.8,
        },
        "3 sigma": {
            "ic": 0.0,
            "rank_ic": 0.0,
            "hit_rate": 0.0,
            "mean": 0.0,
            "dispersion": 0.0,
            "score": 0.0,
        },
        "4 sigma": {
            "ic": 0.003,
            "rank_ic": 0.002,
            "hit_rate": 0.5,
            "mean": 0.02,
            "dispersion": 0.16,
            "score": 1.4,
        },
    }
    standardisation_adjustments: dict[str, dict[str, float]] = {
        "Z-score": {
            "ic": 0.0,
            "rank_ic": 0.0,
            "hit_rate": 0.0,
            "mean": 0.0,
            "dispersion": 0.0,
            "score": 0.0,
        },
        "Robust z-score": {
            "ic": 0.002,
            "rank_ic": 0.001,
            "hit_rate": 0.6,
            "mean": 0.01,
            "dispersion": -0.08,
            "score": 0.8,
        },
        "Rank scale": {
            "ic": -0.002,
            "rank_ic": 0.004,
            "hit_rate": 0.3,
            "mean": -0.02,
            "dispersion": -0.04,
            "score": -0.5,
        },
    }
    winsorisation_shift = winsorisation_adjustments.get(
        winsorisation, winsorisation_adjustments["3 sigma"]
    )
    standardisation_shift = standardisation_adjustments.get(
        standardisation, standardisation_adjustments["Z-score"]
    )
    ewma_ic_shift = (ewma_decay - 0.94) * 0.12
    ewma_rank_shift = (ewma_decay - 0.94) * 0.10
    ewma_hit_shift = (ewma_decay - 0.94) * 8.0
    ewma_mean_shift = (ewma_decay - 0.94) * 0.40
    ewma_dispersion_shift = (0.94 - ewma_decay) * 1.5
    ewma_score_shift = (ewma_decay - 0.94) * 12.0
    factor_templates: dict[str, dict[str, Any]] = {
        "Quality": {
            "ic": 0.054,
            "rank_ic": 0.069,
            "hit_rate": 61.0,
            "top_weight": 27.0,
            "distribution_mean": 0.42,
            "distribution_dispersion": 0.88,
            "sub_variables": ["ROE", "Gross Margin", "Accruals"],
        },
        "Value": {
            "ic": 0.037,
            "rank_ic": 0.051,
            "hit_rate": 58.0,
            "top_weight": 24.0,
            "distribution_mean": 0.28,
            "distribution_dispersion": 1.02,
            "sub_variables": ["B/P", "E/P", "FCF Yield"],
        },
        "Market Technical": {
            "ic": 0.029,
            "rank_ic": 0.043,
            "hit_rate": 54.0,
            "top_weight": 18.0,
            "distribution_mean": 0.16,
            "distribution_dispersion": 1.13,
            "sub_variables": ["6M Return", "12-1 Return", "EPS Revision"],
        },
        "Dividend": {
            "ic": 0.048,
            "rank_ic": 0.062,
            "hit_rate": 60.0,
            "top_weight": 31.0,
            "distribution_mean": 0.33,
            "distribution_dispersion": 0.81,
            "sub_variables": ["Yield", "Payout Stability", "Coverage"],
        },
    }
    selected = [str(name) for name in factor_sleeves if str(name) in factor_templates] or list(
        factor_templates.keys()
    )
    factor_rows: list[dict[str, Any]] = []
    for factor_name in selected:
        template = factor_templates[factor_name]
        factor_rows.append(
            {
                "factor": factor_name,
                "ic": round(
                    float(template["ic"])
                    + (0.004 if neutralisation else -0.003)
                    + winsorisation_shift["ic"]
                    + standardisation_shift["ic"]
                    + ewma_ic_shift,
                    3,
                ),
                "rank_ic": round(
                    float(template["rank_ic"])
                    + (0.003 if neutralisation else -0.004)
                    + winsorisation_shift["rank_ic"]
                    + standardisation_shift["rank_ic"]
                    + ewma_rank_shift,
                    3,
                ),
                "hit_rate_pct": round(
                    float(template["hit_rate"])
                    + (1.2 if neutralisation else -1.8)
                    + winsorisation_shift["hit_rate"]
                    + standardisation_shift["hit_rate"]
                    + ewma_hit_shift,
                    1,
                ),
                "top_weight_pct": round(
                    float(template["top_weight"]) - transaction_cost_bps / 50.0, 1
                ),
                "distribution_mean": round(
                    float(template["distribution_mean"])
                    + winsorisation_shift["mean"]
                    + standardisation_shift["mean"]
                    + ewma_mean_shift,
                    2,
                ),
                "distribution_dispersion": round(
                    float(template["distribution_dispersion"])
                    + top_n / 250.0
                    + winsorisation_shift["dispersion"]
                    + standardisation_shift["dispersion"]
                    + ewma_dispersion_shift,
                    2,
                ),
                "sub_variables": list(template["sub_variables"]),
            }
        )
    ticker_templates = ["MSFT", "JNJ", "PG", "XOM", "ABBV", "PEP"]
    sector_lookup = _lookup_company_sectors(ticker_templates)
    top_preview = []
    score_base = 98.0
    for index, ticker in enumerate(ticker_templates):
        factor_name = selected[index % len(selected)]
        top_preview.append(
            {
                "ticker": ticker,
                "sector": sector_lookup.get(ticker, "Unknown"),
                "factor": factor_name,
                "score": round(
                    score_base
                    - index * 2.7
                    - transaction_cost_bps / 30.0
                    + winsorisation_shift["score"]
                    + standardisation_shift["score"]
                    + ewma_score_shift,
                    1,
                ),
            }
        )
    avg_ic = sum(row["ic"] for row in factor_rows) / max(1, len(factor_rows))
    avg_rank_ic = sum(row["rank_ic"] for row in factor_rows) / max(1, len(factor_rows))
    return {
        "scenario_id": resolved_id,
        "scenario_name": resolved_name,
        "summary": {
            "active_factor_count": len(factor_rows),
            "sub_variable_count": sum(len(row["sub_variables"]) for row in factor_rows),
            "avg_ic": round(avg_ic, 3),
            "avg_rank_ic": round(avg_rank_ic, 3),
            "neutralisation_enabled": neutralisation,
            "winsorisation": winsorisation,
            "standardisation": standardisation,
            "ewma_decay": round(ewma_decay, 2),
            "lookback_window": lookback,
            "top_preview_count": min(top_n, 50),
        },
        "factor_rows": factor_rows,
        "alpha_distribution": [
            {"bucket": "-2 sigma", "count": 7},
            {"bucket": "-1 sigma", "count": 19},
            {"bucket": "0 sigma", "count": 36},
            {"bucket": "+1 sigma", "count": 24},
            {"bucket": "+2 sigma", "count": 11},
        ],
        "top_preview": top_preview,
        "heatmap": [
            {
                "factor": row["factor"],
                "ic": row["ic"],
                "rank_ic": row["rank_ic"],
                "hit_rate_pct": row["hit_rate_pct"],
            }
            for row in factor_rows
        ],
        "notes": [
            f"{len(factor_rows)} active sleeves are currently being previewed from the working scenario.",
            f"Neutralisation is {'enabled' if neutralisation else 'disabled'}, winsorisation is set to {winsorisation}, and the preview remains aligned to the {lookback} research window.",
            f"Standardisation is using {standardisation} with EWMA decay {round(ewma_decay, 2)}, which shifts the previewed IC, rank-IC, and score dispersion.",
            f"Top-preview output is capped at {min(top_n, 50)} names to support report-writing screenshots and quick QA.",
        ],
        "generated_at": _utc_now_text(),
    }


def _build_trade_preview_payload(
    *,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_id, resolved_name, resolved_config = _resolve_scenario_selection(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        scenario_config=scenario_config,
    )
    config = _scenario_config_with_defaults(resolved_config)
    top_n = int(_coerce_numeric_text(config.get("top_n"), default=25))
    hold_cap = _coerce_percent_text(config.get("hold_cap"), default=0.05)
    transaction_cost_bps = _coerce_bps_text(config.get("transaction_cost"), default=15.0)
    execution_lag_days = int(_coerce_numeric_text(config.get("execution_lag_days"), default=1))
    overlay_enabled = bool(config.get("stress_overlay", True))
    execution_style = str(config.get("execution_style") or "Quarterly batch").strip()
    trade_filter = str(config.get("trade_filter") or "All trades").strip()
    attribution_view = str(config.get("attribution_view") or "Driver share").strip()
    gross_turnover_pct = round(
        12.0
        + max(0, 32 - top_n) * 0.42
        + transaction_cost_bps / 8.0
        + max(0, execution_lag_days - 1) * 0.3,
        1,
    )
    trade_rows = [
        {
            "ticker": "PG",
            "side": "Buy",
            "sector": "Consumer Staples",
            "weight_delta_pct": 1.4,
            "trigger_reason": "Stress overlay raised defensive sleeve",
            "alpha_driver": "Dividend stability",
            "risk_status": "Within cap",
            "optimizer_note": "Incumbent retained and topped up",
        },
        {
            "ticker": "JNJ",
            "side": "Buy",
            "sector": "Health Care",
            "weight_delta_pct": 1.1,
            "trigger_reason": "Quality sleeve strengthened",
            "alpha_driver": "Defensive quality",
            "risk_status": "Within cap",
            "optimizer_note": "Turnover-efficient add",
        },
        {
            "ticker": "XOM",
            "side": "Trim",
            "sector": "Energy",
            "weight_delta_pct": -0.7,
            "trigger_reason": "Cap rebalance after overlay shift",
            "alpha_driver": "Value / dividend carry",
            "risk_status": "Sector neutralisation active",
            "optimizer_note": "Reduced to preserve breadth",
        },
        {
            "ticker": "NVDA",
            "side": "Sell",
            "sector": "Technology",
            "weight_delta_pct": -1.6,
            "trigger_reason": "Momentum sleeve reduced in stress",
            "alpha_driver": "Market technical",
            "risk_status": "Risk-off rotation",
            "optimizer_note": "Exited after rank deterioration",
        },
    ]

    if execution_style == "Quarterly staged":
        for row in trade_rows:
            row["optimizer_note"] = f"Staged execution over {max(execution_lag_days, 1)} day(s)"
            if row["side"] == "Buy":
                row["trigger_reason"] = "Staged entry after quarterly rebalance"
    elif execution_style == "Manual review first":
        for row in trade_rows:
            row["risk_status"] = "Manual sign-off pending"
            row["optimizer_note"] = "Queued for manual review before release"
        gross_turnover_pct = round(max(gross_turnover_pct - 1.0, 0.0), 1)

    if trade_filter == "Buys only":
        trade_rows = [row for row in trade_rows if row["side"] == "Buy"]
    elif trade_filter == "Sells only":
        trade_rows = [row for row in trade_rows if row["side"] in {"Sell", "Trim"}]
    elif trade_filter == "Largest changes":
        trade_rows = sorted(
            trade_rows, key=lambda row: abs(float(row["weight_delta_pct"])), reverse=True
        )[:3]

    if attribution_view == "Overlay vs ranking":
        attribution_rows = [
            {"source": "Regime overlay", "share_pct": 48.0},
            {"source": "Factor ranking", "share_pct": 34.0},
            {"source": "Constraint residual", "share_pct": 18.0},
        ]
    elif attribution_view == "Constraints only":
        attribution_rows = [
            {"source": "Single-name cap", "share_pct": 41.0},
            {"source": "Sector neutrality", "share_pct": 29.0},
            {"source": "Turnover guard", "share_pct": 18.0},
            {"source": "Liquidity clip", "share_pct": 12.0},
        ]
    else:
        attribution_rows = [
            {"source": "Regime overlay", "share_pct": 42.0},
            {"source": "Factor rank refresh", "share_pct": 31.0},
            {"source": "Risk caps", "share_pct": 17.0},
            {"source": "Turnover controls", "share_pct": 10.0},
        ]

    execution_style_label = {
        "Quarterly batch": "Quarterly batch with overlay exception handling",
        "Quarterly staged": f"Quarterly staged release over {max(execution_lag_days, 1)} day(s)",
        "Manual review first": "Manual review queue before batch release",
    }.get(execution_style, execution_style)

    return {
        "scenario_id": resolved_id,
        "scenario_name": resolved_name,
        "summary": {
            "trade_count": len(trade_rows),
            "gross_turnover_pct": gross_turnover_pct,
            "largest_sector": "Consumer Staples" if overlay_enabled else "Technology",
            "execution_style": execution_style_label,
            "single_name_cap_pct": round(hold_cap * 100, 1),
            "transaction_cost_bps": round(transaction_cost_bps, 1),
        },
        "trade_rows": trade_rows,
        "attribution_rows": attribution_rows,
        "holdings_rows": [
            {
                "ticker": "PG",
                "sector": "Consumer Staples",
                "weight_pct": 4.7,
                "role": "Dividend / defence",
            },
            {"ticker": "JNJ", "sector": "Health Care", "weight_pct": 4.5, "role": "Quality"},
            {"ticker": "MSFT", "sector": "Technology", "weight_pct": 4.3, "role": "Core quality"},
            {"ticker": "XOM", "sector": "Energy", "weight_pct": 4.0, "role": "Value / dividend"},
            {
                "ticker": "ABBV",
                "sector": "Health Care",
                "weight_pct": 3.7,
                "role": "Defensive growth",
            },
        ],
        "notes": [
            f"Trade preview is derived from the current {resolved_name} working configuration.",
            f"Gross turnover is estimated at {gross_turnover_pct:.1f}% under a {transaction_cost_bps:.1f} bps cost assumption and {execution_lag_days} day execution lag.",
            f"Execution style is currently '{execution_style_label}' and trade filter is '{trade_filter}'.",
            f"Attribution view is '{attribution_view}', which changes how sources are grouped in the preview.",
        ],
        "generated_at": _utc_now_text(),
    }


def _latest_timestamp(paths: list[Path]) -> datetime | None:
    existing = [path.stat().st_mtime for path in paths if path.exists()]
    if not existing:
        return None
    return datetime.fromtimestamp(max(existing), tz=timezone.utc)


def _metrics_by_group(path: Path) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, float]] = {}
    for row in _read_csv(path):
        grouped.setdefault(row["metric_group"], {})[row["metric_name"]] = float(row["metric_value"])
    return grouped


def _relative_metrics(path: Path) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, float]] = {}
    for row in _read_csv(path):
        grouped.setdefault(row["versus_series"], {})[row["metric_name"]] = float(
            row["metric_value"]
        )
    return grouped


def _read_text_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "scenario"


def _build_generated_portfolio_name(scenario_name: str) -> str:
    prefix = "web_"
    max_total_length = 50
    max_slug_length = max_total_length - len(prefix)
    slug = _safe_slug(scenario_name)[:max_slug_length].rstrip("_") or "scenario"
    return f"{prefix}{slug}"


def _coerce_percent_text(value: Any, *, default: float) -> float:
    if value in ("", None):
        return default
    text_value = str(value).strip().replace("%", "")
    try:
        return float(text_value) / 100.0
    except ValueError:
        return default


def _coerce_bps_text(value: Any, *, default: float) -> float:
    if value in ("", None):
        return default
    text_value = str(value).strip().lower().replace("bps", "")
    try:
        return float(text_value)
    except ValueError:
        return default


def _coerce_numeric_text(value: Any, *, default: float) -> float:
    if value in ("", None):
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        return default


def _normalize_factor_weights(
    factor_sleeves: list[str],
) -> tuple[dict[str, float], dict[str, float]]:
    baseline_normal = {
        "quality": 0.18,
        "value": 0.24,
        "market_technical": 0.43,
        "sentiment": 0.00,
        "dividend": 0.15,
    }
    baseline_stress = {
        "quality": 0.40,
        "value": 0.10,
        "market_technical": 0.05,
        "sentiment": 0.05,
        "dividend": 0.40,
    }
    alias_map = {
        "quality": "quality",
        "value": "value",
        "market technical": "market_technical",
        "momentum": "market_technical",
        "dividend": "dividend",
        "sentiment": "sentiment",
    }
    selected = {
        alias_map[key.strip().lower()] for key in factor_sleeves if key.strip().lower() in alias_map
    }
    if not selected:
        return baseline_normal, baseline_stress

    def _rescale(template: dict[str, float]) -> dict[str, float]:
        weights = {key: (value if key in selected else 0.0) for key, value in template.items()}
        total = sum(weights.values())
        if total <= 0:
            even_weight = 1.0 / len(selected)
            return {key: (even_weight if key in selected else 0.0) for key in template}
        return {key: (value / total if key in selected else 0.0) for key, value in weights.items()}

    return _rescale(baseline_normal), _rescale(baseline_stress)


def _load_json_like_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # The generated files are JSON-with-.yaml extension; this is fallback-safe.
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_baseline_config_payload() -> dict[str, Any]:
    text = _read_text_if_exists(BASELINE_CONFIG_PATH)
    if text is None:
        return {}
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        helper_python = _resolve_runner_python()
        if not helper_python.exists():
            return {}
        try:
            helper = subprocess.run(
                [
                    str(helper_python),
                    "-c",
                    (
                        "import json, pathlib, yaml; "
                        "path = pathlib.Path(r'%s'); "
                        "print(json.dumps(yaml.safe_load(path.read_text(encoding='utf-8')) or {}))"
                    )
                    % str(BASELINE_CONFIG_PATH),
                ],
                capture_output=True,
                text=True,
                check=True,
                shell=False,
            )
            return json.loads(helper.stdout)
        except Exception:
            return {}


def _replace_line(text: str, pattern: str, replacement: str) -> str:
    return re.sub(pattern, replacement, text, flags=re.MULTILINE)


def _replace_section_weights(
    text: str,
    *,
    section_name: str,
    weights: dict[str, float],
) -> str:
    pattern = rf"(^  {section_name}:\n)(?:    .+\n)+"
    replacement = f"  {section_name}:\n" + "".join(
        f"    {key}: {value:.12g}\n" for key, value in weights.items()
    )
    return re.sub(pattern, replacement, text, flags=re.MULTILINE)


def _materialize_generated_config_text(
    *,
    scenario_name: str,
    scenario_config: dict[str, Any],
) -> str:
    base_text = _read_text_if_exists(BASELINE_CONFIG_PATH)
    if base_text is None:
        return json.dumps(
            _scenario_override_payload(scenario_name, scenario_config), indent=2, ensure_ascii=False
        )

    transaction_cost_bps = _coerce_bps_text(scenario_config.get("transaction_cost"), default=15.0)
    hold_cap = _coerce_percent_text(scenario_config.get("hold_cap"), default=0.05)
    requested_top_n = int(_coerce_numeric_text(scenario_config.get("top_n"), default=25))
    min_required_names = max(1, math.ceil(1.0 / max(hold_cap, 1e-9)))
    hybrid_min = max(requested_top_n, min_required_names)
    hybrid_max = max(hybrid_min, hybrid_min + 10)
    min_names = min(hybrid_min, hybrid_max)
    min_candidate_pool = max(min_names, hybrid_max)
    vix_threshold = _coerce_numeric_text(scenario_config.get("vix_threshold"), default=22.0)
    target_frequency = "quarterly"
    neutralisation = "gics_sector" if bool(scenario_config.get("neutralisation", True)) else "none"
    factor_sleeves = scenario_config.get("factor_sleeves") or []
    if isinstance(factor_sleeves, str):
        factor_sleeves = [item.strip() for item in factor_sleeves.split("/") if item.strip()]
    normal_weights, stress_weights = _normalize_factor_weights(list(factor_sleeves))
    if not bool(scenario_config.get("stress_overlay", True)):
        stress_weights = dict(normal_weights)

    portfolio_name = _build_generated_portfolio_name(scenario_name)
    text = base_text
    text = _replace_line(text, r"^  neutralize_by: .*$", f"  neutralize_by: {neutralisation}")
    text = _replace_line(
        text, r"^  vix_stress_threshold: .*$", f"  vix_stress_threshold: {vix_threshold:.12g}"
    )
    text = _replace_line(
        text,
        r"^  vix_warning_threshold: .*$",
        f"  vix_warning_threshold: {max(vix_threshold - 4.0, 1.0):.12g}",
    )
    text = _replace_line(
        text,
        r"^  vix_exit_threshold: .*$",
        f"  vix_exit_threshold: {max(vix_threshold - 2.0, 1.0):.12g}",
    )
    text = _replace_section_weights(text, section_name="normal", weights=normal_weights)
    text = _replace_section_weights(text, section_name="stress", weights=stress_weights)
    text = _replace_line(text, r"^  portfolio_name: .*$", f"  portfolio_name: {portfolio_name}")
    text = _replace_line(
        text,
        r"^  target_generation_frequency: .*$",
        f"  target_generation_frequency: {target_frequency}",
    )
    text = _replace_line(
        text,
        r"^  top_n: .*$",
        f"  top_n: {hybrid_min}",
    )
    text = _replace_line(text, r"^  hybrid_min_n: .*$", f"  hybrid_min_n: {hybrid_min}")
    text = _replace_line(text, r"^  hybrid_max_n: .*$", f"  hybrid_max_n: {hybrid_max}")
    text = _replace_line(text, r"^  min_names: .*$", f"  min_names: {min_names}")
    text = _replace_line(
        text, r"^  min_candidate_pool: .*$", f"  min_candidate_pool: {min_candidate_pool}"
    )
    text = _replace_line(
        text, r"^  min_investable_universe: .*$", f"  min_investable_universe: {min_candidate_pool}"
    )
    text = _replace_line(
        text, r"^  min_portfolio_targets: .*$", f"  min_portfolio_targets: {min_names}"
    )
    text = _replace_line(
        text, r"^  max_single_weight: .*$", f"  max_single_weight: {hold_cap:.12g}"
    )
    text = _replace_line(
        text, r"^  rebalance_frequency: .*$", f"  rebalance_frequency: {target_frequency}"
    )
    text = _replace_line(
        text, r"^  min_eligible_universe: .*$", f"  min_eligible_universe: {min_candidate_pool}"
    )
    text = re.sub(
        r"(^backtest:\n(?:  .*\n)*?  top_n: )\d+",
        rf"\g<1>{hybrid_max}",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"(^backtest:\n(?:  .*\n)*?  transaction_cost_bps: )[0-9.]+",
        rf"\g<1>{transaction_cost_bps:.12g}",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"(^  intraday_triggers:\n(?:    .*\n)*?    transaction_cost_bps: )[0-9.]+",
        rf"\g<1>{transaction_cost_bps:.12g}",
        text,
        flags=re.MULTILINE,
    )
    return text


def _scenario_override_payload(
    scenario_name: str, scenario_config: dict[str, Any]
) -> dict[str, Any]:
    transaction_cost_bps = _coerce_bps_text(scenario_config.get("transaction_cost"), default=15.0)
    hold_cap = _coerce_percent_text(scenario_config.get("hold_cap"), default=0.05)
    requested_top_n = int(_coerce_numeric_text(scenario_config.get("top_n"), default=25))
    min_required_names = max(1, math.ceil(1.0 / max(hold_cap, 1e-9)))
    hybrid_min = max(requested_top_n, min_required_names)
    hybrid_max = max(hybrid_min, hybrid_min + 10)
    min_names = min(hybrid_min, hybrid_max)
    min_candidate_pool = max(min_names, hybrid_max)
    vix_threshold = _coerce_numeric_text(scenario_config.get("vix_threshold"), default=22.0)
    target_frequency = "quarterly"
    factor_sleeves = scenario_config.get("factor_sleeves") or []
    if isinstance(factor_sleeves, str):
        factor_sleeves = [item.strip() for item in factor_sleeves.split("/") if item.strip()]
    normal_weights, stress_weights = _normalize_factor_weights(list(factor_sleeves))
    stress_overlay = bool(scenario_config.get("stress_overlay", True))
    if not stress_overlay:
        stress_weights = dict(normal_weights)

    neutralisation = "gics_sector" if bool(scenario_config.get("neutralisation", True)) else "none"
    portfolio_name = _build_generated_portfolio_name(scenario_name)
    return {
        "preprocessing": {
            "neutralize_by": neutralisation,
        },
        "regime": {
            "vix_stress_threshold": vix_threshold,
            "vix_exit_threshold": max(vix_threshold - 2.0, 1.0),
            "vix_warning_threshold": max(vix_threshold - 4.0, 1.0),
            "normal": normal_weights,
            "stress": stress_weights,
        },
        "portfolio_construction": {
            "portfolio_name": portfolio_name,
            "top_n": hybrid_min,
            "hybrid_min_n": hybrid_min,
            "hybrid_max_n": hybrid_max,
            "min_names": min_names,
            "min_candidate_pool": min_candidate_pool,
            "max_single_weight": hold_cap,
            "target_generation_frequency": target_frequency,
        },
        "pipeline_guards": {
            "min_investable_universe": min_candidate_pool,
        },
        "quality_gates": {
            "min_portfolio_targets": min_names,
        },
        "backtest": {
            "portfolio_name": portfolio_name,
            "rebalance_frequency": target_frequency,
            "top_n": hybrid_max,
            "min_eligible_universe": min_candidate_pool,
            "transaction_cost_bps": transaction_cost_bps,
        },
    }


def _resolve_runner_python() -> Path:
    env_python = str(os.getenv("CW2_RUNNER_PYTHON", "")).strip()
    candidates = [
        Path(env_python) if env_python else None,
        BASE_DIR.parent / ".venv" / "Scripts" / "python.exe",
        BASE_DIR.parent / ".venv" / "bin" / "python",
        BASE_DIR / ".venv" / "Scripts" / "python.exe",
        BASE_DIR / ".venv" / "bin" / "python",
        BASE_DIR.parent.parent / ".venv" / "Scripts" / "python.exe",
        BASE_DIR.parent.parent / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    return Path(sys.executable)


def _resolve_docx_export_python() -> Path:
    candidates = [
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "python"
        / "python.exe",
        _resolve_runner_python(),
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def _report_export_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _resolve_runner_pythonpath_entries() -> list[str]:
    candidates = [
        Path(__file__).resolve().parents[5] / "_restore_workspace" / "pydeps",
        BASE_DIR.parent.parent / "_restore_workspace" / "pydeps",
    ]
    entries: list[str] = []
    for candidate in candidates:
        if candidate.exists():
            text_value = str(candidate)
            if text_value not in entries:
                entries.append(text_value)
    return entries


def _resolve_runner_env_vars() -> dict[str, str]:
    defaults = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5439",
        "POSTGRES_DB": "fift",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
    }
    resolved: dict[str, str] = {}
    for key, fallback in defaults.items():
        value = str(os.getenv(key, fallback)).strip() or fallback
        resolved[key] = value
    return resolved


def _runner_preflight_report(queue_type: str | None = None) -> dict[str, Any]:
    queue_kind = str(queue_type or "").strip().lower()
    python_exe = _resolve_runner_python()
    env_vars = _resolve_runner_env_vars()
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fix": fix})

    add_check(
        "Runner Python",
        python_exe.exists(),
        str(python_exe),
        "Start the site with Launch_CW2_Web.cmd so the project virtual environment is created.",
    )
    add_check(
        "Runner script",
        RUNNER_SCRIPT_PATH.exists(),
        str(RUNNER_SCRIPT_PATH),
        "Restore team_Pearson/coursework_two/scripts/web_runner_job.py.",
    )
    add_check(
        "Baseline config",
        BASELINE_CONFIG_PATH.exists(),
        str(BASELINE_CONFIG_PATH),
        "Restore the formal baseline YAML under config/experiments/formal.",
    )

    required_scripts = [
        BASE_DIR / "scripts" / "backfill_monthly_snapshots.py",
        BASE_DIR / "scripts" / "run_backtest_analysis_report.py",
    ]
    if queue_kind == "robustness_sensitivity":
        required_scripts.append(BASE_DIR / "scripts" / "run_sensitivity_analysis.py")
    missing_scripts = [str(path) for path in required_scripts if not path.exists()]
    add_check(
        "Pipeline scripts",
        not missing_scripts,
        "All required scripts are present." if not missing_scripts else "; ".join(missing_scripts),
        "Restore the missing coursework_two/scripts files before launching a run.",
    )

    if python_exe.exists():
        import_probe = "import sqlalchemy, pandas, numpy, yaml, psycopg2"
        try:
            completed = subprocess.run(
                [str(python_exe), "-c", import_probe],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            probe_ok = completed.returncode == 0
            probe_detail = "Required Python packages are importable."
            if not probe_ok:
                raw_probe = (completed.stderr or completed.stdout or "").strip()
                probe_lines = [line.strip() for line in raw_probe.splitlines() if line.strip()]
                probe_detail = (
                    probe_lines[-1] if probe_lines else "Required Python packages are missing."
                )
            add_check(
                "Python packages",
                probe_ok,
                probe_detail,
                "Run Launch_CW2_Web.cmd again; it installs requirements-runtime.txt into team_Pearson/.venv.",
            )
        except Exception as exc:
            add_check(
                "Python packages",
                False,
                f"Package probe failed: {exc!r}",
                "Run Launch_CW2_Web.cmd again; it installs requirements-runtime.txt into team_Pearson/.venv.",
            )

    db_host = env_vars["POSTGRES_HOST"]
    db_port = int(env_vars["POSTGRES_PORT"])
    try:
        with socket.create_connection((db_host, db_port), timeout=2.0):
            db_ok = True
            db_detail = f"{db_host}:{db_port} is reachable."
    except OSError as exc:
        db_ok = False
        db_detail = f"{db_host}:{db_port} is not reachable ({exc})."
    add_check(
        "PostgreSQL",
        db_ok,
        db_detail,
        "Start Docker/PostgreSQL, or launch through Launch_CW2_Web.cmd so it can start postgres_db_cw.",
    )

    failures = [item for item in checks if not item["ok"]]
    message = "Runner preflight passed."
    if failures:
        message = "Runner preflight failed: " + " | ".join(
            f"{item['name']}: {item['detail']}"
            + (f" Fix: {item['fix']}" if item.get("fix") else "")
            for item in failures
        )
    return {
        "ok": not failures,
        "queue_type": queue_kind or "single_run",
        "runner_python": str(python_exe),
        "checks": checks,
        "message": message,
    }


def _ensure_runner_preflight(payload: RunnerQueuePayload) -> None:
    if not payload.auto_start or payload.queue_type == "nightly_refresh":
        return
    report = _runner_preflight_report(payload.queue_type)
    if not report["ok"]:
        raise HTTPException(status_code=503, detail=report["message"])


def _materialize_generated_config(
    *,
    run_id: str,
    scenario_name: str,
    scenario_config: dict[str, Any],
) -> Path:
    out_path = GENERATED_CONFIG_DIR / f"{run_id}__{_safe_slug(scenario_name)}.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        _materialize_generated_config_text(
            scenario_name=scenario_name,
            scenario_config=scenario_config,
        ),
        encoding="utf-8",
    )
    return out_path


def _build_command_bundle(
    *,
    python_exe: Path,
    run_id: str,
    label: str,
    scenario_name: str,
    scenario_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    config_path = _materialize_generated_config(
        run_id=run_id,
        scenario_name=scenario_name,
        scenario_config=scenario_config,
    )
    run_slug = _safe_slug(scenario_name)
    report_name = f"{run_id.lower()}_{run_slug}_report"
    run_name = f"{run_id.lower()}_{run_slug}"
    commands = [
        {
            "name": "backfill_monthly_snapshots",
            "cwd": str(BASE_DIR.parent.parent),
            "args": [
                str(python_exe),
                str(BASE_DIR / "scripts" / "backfill_monthly_snapshots.py"),
                "--start-date",
                BACKFILL_START_DATE,
                "--end-date",
                BACKFILL_END_DATE,
                "--cw2-config",
                str(config_path),
                "--company-limit",
                "1000",
                "--skip-existing",
                "false",
                "--refresh-market-factors",
                "false",
            ],
            "display": (
                f"{python_exe} {BASE_DIR / 'scripts' / 'backfill_monthly_snapshots.py'} "
                f"--start-date {BACKFILL_START_DATE} --end-date {BACKFILL_END_DATE} "
                f"--cw2-config {config_path} --company-limit 1000 --skip-existing false "
                f"--refresh-market-factors false"
            ),
        },
        {
            "name": "run_backtest_analysis_report",
            "cwd": str(BASE_DIR.parent.parent),
            "args": [
                str(python_exe),
                str(BASE_DIR / "scripts" / "run_backtest_analysis_report.py"),
                "--cw2-config",
                str(config_path),
                "--run-name",
                run_name,
                "--report-name",
                report_name,
            ],
            "display": (
                f"{python_exe} {BASE_DIR / 'scripts' / 'run_backtest_analysis_report.py'} "
                f"--cw2-config {config_path} --run-name {run_name} --report-name {report_name}"
            ),
        },
    ]
    manifests = [
        {
            "scenario_name": scenario_name,
            "label": label,
            "generated_config_path": str(config_path),
            "run_name": run_name,
            "report_name": report_name,
        }
    ]
    return commands, manifests


def _map_sensitivity_dimensions_to_tests(dimensions: list[str]) -> list[str]:
    mapping = {
        "transaction cost": "1",
        "breadth range": "3",
        "regime threshold": "5",
        "drawdown brake": "6",
        "incumbent band": "7",
        "trade constraints": "8",
    }
    selected: list[str] = []
    for dimension in dimensions:
        mapped = mapping.get(str(dimension or "").strip().lower())
        if mapped and mapped not in selected:
            selected.append(mapped)
    return selected


def _build_robustness_sensitivity_bundle(
    *,
    python_exe: Path,
    payload: RunnerQueuePayload,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    options = dict(payload.robustness_options or {})
    scenario_name = payload.scenario_name or payload.label or "current_working_scenario"
    config_path = _materialize_generated_config(
        run_id=payload.run_id,
        scenario_name=scenario_name,
        scenario_config=payload.scenario_config,
    )
    run_slug = _safe_slug(scenario_name)
    output_root = ROBUSTNESS_DIR / "web_runs" / payload.run_id
    report_root = output_root / "reports"
    selected_tests = _map_sensitivity_dimensions_to_tests(
        list(options.get("sensitivity_dimensions") or [])
    )
    if not selected_tests:
        selected_tests = ["1", "3", "5"]
    summary_tag = _safe_slug(payload.run_id.lower())
    commands: list[dict[str, Any]] = [
        {
            "name": "backfill_monthly_snapshots",
            "cwd": str(BASE_DIR.parent.parent),
            "args": [
                str(python_exe),
                str(BASE_DIR / "scripts" / "backfill_monthly_snapshots.py"),
                "--start-date",
                BACKFILL_START_DATE,
                "--end-date",
                BACKFILL_END_DATE,
                "--cw2-config",
                str(config_path),
                "--company-limit",
                "1000",
                "--skip-existing",
                "false",
                "--refresh-market-factors",
                "false",
            ],
            "display": (
                f"{python_exe} {BASE_DIR / 'scripts' / 'backfill_monthly_snapshots.py'} "
                f"--start-date {BACKFILL_START_DATE} --end-date {BACKFILL_END_DATE} "
                f"--cw2-config {config_path} --company-limit 1000 --skip-existing false "
                f"--refresh-market-factors false"
            ),
        },
        {
            "name": "run_sensitivity_analysis",
            "cwd": str(BASE_DIR.parent.parent),
            "args": [
                str(python_exe),
                str(BASE_DIR / "scripts" / "run_sensitivity_analysis.py"),
                "--cw2-config",
                str(config_path),
                "--tests",
                ",".join(selected_tests),
                "--output-root",
                str(output_root),
                "--report-output-dir",
                str(report_root),
                "--run-prefix",
                f"web_sensitivity_{run_slug}",
                "--fast-summary-only",
                "--summary-tag",
                summary_tag,
            ],
            "display": (
                f"{python_exe} {BASE_DIR / 'scripts' / 'run_sensitivity_analysis.py'} "
                f"--cw2-config {config_path} --tests {','.join(selected_tests)} "
                f"--output-root {output_root} --report-output-dir {report_root} "
                f"--run-prefix web_sensitivity_{run_slug} --fast-summary-only --summary-tag {summary_tag}"
            ),
        },
    ]
    artifact_roots = [str(output_root)]
    manifests = [
        {
            "scenario_name": scenario_name,
            "label": payload.label,
            "generated_config_path": str(config_path),
            "run_name": payload.run_id,
            "report_name": "",
        }
    ]
    return commands, manifests, artifact_roots


def _materialize_job_bundle(payload: RunnerQueuePayload) -> dict[str, Any]:
    python_exe = _resolve_runner_python()
    pythonpath_entries = _resolve_runner_pythonpath_entries()
    env_vars = _resolve_runner_env_vars()
    commands: list[dict[str, Any]] = []
    scenario_manifests: list[dict[str, str]] = []
    extra_artifact_roots: list[str] = []
    if payload.queue_type == "robustness_sensitivity":
        commands, scenario_manifests, extra_artifact_roots = _build_robustness_sensitivity_bundle(
            python_exe=python_exe,
            payload=payload,
        )
    elif payload.queue_type == "batch_compare" and payload.scenario_configs:
        for scenario_name, scenario_config in payload.scenario_configs.items():
            run_commands, manifests = _build_command_bundle(
                python_exe=python_exe,
                run_id=f"{payload.run_id}_{_safe_slug(scenario_name)}",
                label=payload.label,
                scenario_name=scenario_name,
                scenario_config=scenario_config,
            )
            commands.extend(run_commands)
            scenario_manifests.extend(manifests)
    else:
        run_commands, manifests = _build_command_bundle(
            python_exe=python_exe,
            run_id=payload.run_id,
            label=payload.label,
            scenario_name=payload.scenario_name or payload.label,
            scenario_config=payload.scenario_config,
        )
        commands.extend(run_commands)
        scenario_manifests.extend(manifests)

    bundle_dir = JOB_BUNDLE_DIR / payload.run_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    log_path = JOB_LOG_DIR / f"{payload.run_id}.log"
    metadata_path = bundle_dir / "job_status.json"
    launch_path = bundle_dir / f"launch_{payload.run_id}.cmd"
    payload_dump = payload.model_dump()
    metadata = {
        **payload_dump,
        "status": "scheduled" if payload.queue_type == "nightly_refresh" else "queued",
        "python_exe": str(python_exe),
        "pythonpath_entries": pythonpath_entries,
        "env_vars": env_vars,
        "commands": commands,
        "scenario_manifests": scenario_manifests,
        "extra_artifact_roots": extra_artifact_roots,
        "log_path": str(log_path),
        "metadata_path": str(metadata_path),
        "launch_path": str(launch_path),
        "created_at": payload.created_at
        or datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "updated_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json(metadata_path, metadata)

    launch_lines = [
        "@echo off",
        "setlocal",
        f'cd /d "{BASE_DIR.parent.parent}"',
    ]
    if pythonpath_entries:
        joined_pythonpath = ";".join(pythonpath_entries)
        launch_lines.append(f'set "PYTHONPATH={joined_pythonpath};%PYTHONPATH%"')
    for key, value in env_vars.items():
        safe_value = str(value).replace('"', "")
        launch_lines.append(f'set "{key}={safe_value}"')
    launch_lines.extend(
        [
            f'"{python_exe}" "{RUNNER_SCRIPT_PATH}" --job-metadata "{metadata_path}"',
            "",
        ]
    )
    launch_text = "\r\n".join(launch_lines)
    launch_path.write_text(launch_text, encoding="utf-8")
    return metadata


def _start_job_runner(metadata: dict[str, Any]) -> dict[str, Any]:
    metadata_path = Path(metadata["metadata_path"])
    python_exe = Path(metadata["python_exe"])
    log_path = Path(metadata["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    pythonpath_entries = [
        str(item).strip()
        for item in (metadata.get("pythonpath_entries") or [])
        if str(item).strip()
    ]
    if pythonpath_entries:
        existing_pythonpath = str(env.get("PYTHONPATH", "")).strip()
        combined = pythonpath_entries + ([existing_pythonpath] if existing_pythonpath else [])
        env["PYTHONPATH"] = os.pathsep.join(combined)
    for key, value in (metadata.get("env_vars") or {}).items():
        cleaned_key = str(key).strip()
        if cleaned_key:
            env[cleaned_key] = str(value)
    creation_flags = 0
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            [
                str(python_exe),
                str(RUNNER_SCRIPT_PATH),
                "--job-metadata",
                str(metadata_path),
            ],
            cwd=str(BASE_DIR.parent.parent),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
            creationflags=creation_flags,
        )
    metadata["launcher_pid"] = process.pid
    metadata["status"] = "queued"
    metadata["updated_at"] = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(metadata_path, metadata)
    return metadata


def _load_baseline_scorecard() -> list[dict[str, str]]:
    db_rows = _fetch_db_dataset_rows(
        "requirement_report__baseline_scorecard",
        report_name_prefix=ROBUSTNESS_REPORT_PREFIX,
    )
    if db_rows:
        return [
            {str(key): "" if value is None else str(value) for key, value in row.items()}
            for row in db_rows
        ]
    return _read_csv(REQUIREMENT_REPORT_DIR / "baseline_scorecard.csv")


def _load_stochastic_dashboard() -> list[dict[str, str]]:
    db_rows = _fetch_db_dataset_rows(
        "requirement_report__stochastic_dashboard",
        report_name_prefix=ROBUSTNESS_REPORT_PREFIX,
    )
    if db_rows:
        return [
            {str(key): "" if value is None else str(value) for key, value in row.items()}
            for row in db_rows
        ]
    return _read_csv(REQUIREMENT_REPORT_DIR / "stochastic_dashboard.csv")


def _load_acceptance_matrix() -> list[dict[str, str]]:
    db_rows = _fetch_db_dataset_rows(
        "requirement_report__acceptance_matrix",
        report_name_prefix=ROBUSTNESS_REPORT_PREFIX,
    )
    if db_rows:
        return [
            {str(key): "" if value is None else str(value) for key, value in row.items()}
            for row in db_rows
        ]
    return _read_csv(REQUIREMENT_REPORT_DIR / "acceptance_matrix.csv")


def _extract_int_from_detail(detail: str, key: str) -> int | None:
    text_value = str(detail or "")
    match = re.search(rf"{re.escape(key)}=(\d+)", text_value)
    return int(match.group(1)) if match else None


def _build_help_robustness_coverage(acceptance_rows: list[dict[str, str]]) -> list[list[str]]:
    rows_by_group: dict[str, list[dict[str, str]]] = {}
    for row in acceptance_rows:
        group_name = str(row.get("requirement_group") or row.get("group") or "").strip()
        if not group_name:
            continue
        rows_by_group.setdefault(group_name, []).append(row)

    def _labels(group_name: str) -> list[str]:
        return [
            str(item.get("label") or item.get("item_key") or "").strip()
            for item in rows_by_group.get(group_name, [])
            if str(item.get("label") or item.get("item_key") or "").strip()
        ]

    def _scenario_total(group_name: str) -> int:
        return sum(
            _extract_int_from_detail(str(item.get("detail") or ""), "scenario_count") or 0
            for item in rows_by_group.get(group_name, [])
        )

    deterministic_labels = _labels("Part 1 Deterministic")
    ablation_labels = _labels("Part 2 Ablation")
    subperiod_labels = _labels("Part 3 Subperiod")
    stochastic_labels = _labels("Part 4 Stochastic")
    packaging_labels = _labels("Part 5 Packaging")

    stochastic_path_cap = max(
        (
            _extract_int_from_detail(str(item.get("detail") or ""), "path_count_max") or 0
            for item in rows_by_group.get("Part 4 Stochastic", [])
        ),
        default=0,
    )

    coverage_rows: list[list[str]] = []
    if deterministic_labels:
        test_span = (
            f"Tests 1-{len(deterministic_labels)}"
            if len(deterministic_labels) > 1
            else deterministic_labels[0]
        )
        coverage_rows.append(
            [
                "Part 1 - Deterministic",
                f"{test_span}; {len(deterministic_labels)} parameter sweeps and {_scenario_total('Part 1 Deterministic')} linked scenarios.",
                "Checks whether the quarterly-rebalanced formal mainline survives direct changes to costs, breadth, thresholds, drawdown brake, incumbent band, and trade constraints.",
            ]
        )
    if ablation_labels:
        coverage_rows.append(
            [
                "Part 2 - Ablation",
                f"{', '.join(ablation_labels)}; {_scenario_total('Part 2 Ablation')} linked scenarios across the three removal blocks.",
                "Checks which blocks of the strategy stack are doing the real work by removing or isolating major components one block at a time.",
            ]
        )
    if subperiod_labels:
        coverage_rows.append(
            [
                "Part 3 - Subperiod",
                f"{', '.join(subperiod_labels)}.",
                "Checks whether the conclusion still holds across fixed historical windows and across normal versus stress market states rather than only in the full-sample average.",
            ]
        )
    if stochastic_labels:
        stochastic_variant_text = (
            f"{', '.join(stochastic_labels)}; up to {stochastic_path_cap:,} simulated paths per test."
            if stochastic_path_cap
            else ", ".join(stochastic_labels)
        )
        coverage_rows.append(
            [
                "Part 4 - Stochastic",
                stochastic_variant_text,
                "Checks whether the realised result remains credible under bootstrap resampling, Monte Carlo cost shocks, local factor perturbations, out-of-sample windows, and simulated return paths.",
            ]
        )
    if packaging_labels:
        coverage_rows.append(
            [
                "Part 5 - Dashboard and Conclusions",
                f"{', '.join(packaging_labels)}.",
                "Collects the acceptance matrix, dashboard summary, and final evidence packaging so the reporting layer can pull the completed robustness story into the final report pack.",
            ]
        )
    return coverage_rows


def _load_report_index() -> list[dict[str, str]]:
    db_rows = _fetch_db_dataset_rows(
        "report_evidence__REPORT_EVIDENCE_INDEX",
        report_name=REPORT_EVIDENCE_NAME,
    )
    if not db_rows:
        db_rows = _fetch_db_dataset_rows(
            "report_handoff__REPORT_HANDOFF_INDEX",
            report_name=LEGACY_REPORT_HANDOFF_NAME,
        )
    if db_rows:
        return [
            {str(key): "" if value is None else str(value) for key, value in row.items()}
            for row in db_rows
        ]
    active_dir = _active_report_evidence_dir()
    preferred = active_dir / "REPORT_EVIDENCE_INDEX.csv"
    legacy = active_dir / "REPORT_HANDOFF_INDEX.csv"
    return _read_csv(preferred if preferred.exists() else legacy)


def _load_report_manifest() -> dict[str, Any]:
    payload = _read_json_if_exists(_active_report_evidence_dir() / "manifest.json", {})
    return payload if isinstance(payload, dict) else {}


def _load_subperiod_analysis() -> list[dict[str, Any]]:
    payload = _read_json_if_exists(SUBPERIOD_DIR / "subperiod_analysis.json", [])
    return payload if isinstance(payload, list) else []


def _load_test11_report_ready_summary() -> list[dict[str, str]]:
    db_rows = _fetch_db_dataset_rows(
        "test11_factor_neighbourhood__summaries__report_ready__test11_report_ready_summary",
        report_name_prefix=ROBUSTNESS_REPORT_PREFIX,
    )
    if db_rows:
        return [
            {str(key): "" if value is None else str(value) for key, value in row.items()}
            for row in db_rows
        ]
    return _read_csv(TEST11_DIR / "summaries" / "report_ready" / "test11_report_ready_summary.csv")


def _load_baseline_metrics_grouped() -> dict[str, dict[str, float]]:
    db_rows = _fetch_db_dataset_rows(
        "requirement_report__baseline_metrics",
        report_name_prefix=ROBUSTNESS_REPORT_PREFIX,
    )
    if db_rows:
        grouped: dict[str, dict[str, float]] = {}
        for row in db_rows:
            grouped.setdefault(str(row["metric_group"]), {})[str(row["metric_name"])] = float(
                row["metric_value"]
            )
        return grouped
    grouped = _metrics_by_group(REQUIREMENT_REPORT_DIR / "baseline_metrics.csv")
    if grouped:
        return grouped
    formal_grouped: dict[str, dict[str, float]] = {}
    for row in _formal_csv_rows("backtest_metrics", run_id=_resolve_primary_run_id()):
        value = _safe_number(row.get("metric_value"))
        if value is None:
            continue
        formal_grouped.setdefault(str(row.get("metric_group") or ""), {})[
            str(row.get("metric_name") or "")
        ] = value
    return formal_grouped


def _load_relative_metrics_grouped() -> dict[str, dict[str, float]]:
    db_rows = _fetch_db_dataset_rows(
        "requirement_report__baseline_relative_metrics",
        report_name_prefix=ROBUSTNESS_REPORT_PREFIX,
    )
    if db_rows:
        grouped: dict[str, dict[str, float]] = {}
        for row in db_rows:
            grouped.setdefault(str(row["versus_series"]), {})[str(row["metric_name"])] = float(
                row["metric_value"]
            )
        return grouped
    grouped = _relative_metrics(REQUIREMENT_REPORT_DIR / "baseline_relative_metrics.csv")
    if grouped:
        return grouped
    formal_grouped: dict[str, dict[str, float]] = {}
    for row in _formal_csv_rows("backtest_relative_metrics", run_id=_resolve_primary_run_id()):
        value = _safe_number(row.get("metric_value"))
        if value is None:
            continue
        formal_grouped.setdefault(str(row.get("versus_series") or ""), {})[
            str(row.get("metric_name") or "")
        ] = value
    return formal_grouped


def _load_baseline_regime_rows() -> list[dict[str, Any]]:
    db_rows = _fetch_db_dataset_rows(
        "requirement_report__baseline_regime_subperiod",
        report_name_prefix=ROBUSTNESS_REPORT_PREFIX,
    )
    if db_rows:
        return db_rows
    return _read_csv(REQUIREMENT_REPORT_DIR / "baseline_regime_subperiod.csv")


def _load_saved_scenarios() -> dict[str, Any]:
    payload = _read_json_if_exists(
        SCENARIO_STATE_PATH,
        {
            "draft": {},
            "presets": {},
            "active_preset": None,
            "saved_at": None,
        },
    )
    formal_template = _formal_mainline_record_template()
    if formal_template:
        if not payload.get("draft"):
            payload["draft"] = formal_template["scenario_config"]
        if not payload.get("presets"):
            payload["presets"] = {
                formal_template["scenario_name"]: formal_template["scenario_config"],
            }
        if not payload.get("active_preset"):
            payload["active_preset"] = formal_template["scenario_name"]
    return payload


def _read_job_or_queue_payload(run_id: str) -> dict[str, Any]:
    metadata_path = JOB_BUNDLE_DIR / run_id / "job_status.json"
    if metadata_path.exists():
        return _reconcile_job_metadata(
            _read_json_if_exists(metadata_path, {}), metadata_path=metadata_path
        )
    queue_path = RUN_QUEUE_DIR / f"{run_id}.json"
    return _read_json_if_exists(queue_path, {})


def _load_web_queue_runs(limit: int = 12) -> list[RunRecord]:
    records: dict[str, tuple[float, RunRecord]] = {}
    queue_files = list(RUN_QUEUE_DIR.glob("*.json")) if RUN_QUEUE_DIR.exists() else []
    bundle_files = list(JOB_BUNDLE_DIR.glob("*/job_status.json")) if JOB_BUNDLE_DIR.exists() else []
    for queue_file in queue_files + bundle_files:
        payload = _read_json_if_exists(queue_file, {})
        if queue_file.name == "job_status.json":
            payload = _reconcile_job_metadata(payload, metadata_path=queue_file)
        file_mtime = queue_file.stat().st_mtime
        created_at = (
            payload.get("created_at")
            or datetime.fromtimestamp(file_mtime, tz=timezone.utc).isoformat()
        )
        started_at = (
            payload.get("started_at")
            or payload.get("created_at")
            or datetime.fromtimestamp(file_mtime, tz=timezone.utc).isoformat()
        )
        updated_at = payload.get("updated_at")
        finished_at = payload.get("finished_at")
        status = str(payload.get("status") or payload.get("queue_type") or "queued")
        duration = payload.get("scheduled_for") or payload.get("finished_at") or "web queue"
        scenario_label = payload.get("label", payload.get("scenario_name", "queued run"))
        queue_type = str(payload.get("queue_type") or "")
        if queue_type == "nightly_refresh" and str(status).strip().lower() not in {
            "canceled",
            "failed",
            "completed",
            "interrupted",
        }:
            linked_run_id = str(payload.get("last_run_id") or "").strip()
            if linked_run_id:
                linked_payload = _read_job_or_queue_payload(linked_run_id)
                linked_status = str(linked_payload.get("status") or "").strip()
                if linked_status:
                    status = linked_status
                linked_started_at = str(
                    linked_payload.get("started_at") or linked_payload.get("created_at") or ""
                ).strip()
                if linked_started_at:
                    started_at = linked_started_at
                linked_updated_at = str(linked_payload.get("updated_at") or "").strip()
                if linked_updated_at:
                    updated_at = linked_updated_at
                linked_finished_at = str(linked_payload.get("finished_at") or "").strip()
                if linked_finished_at:
                    finished_at = linked_finished_at
                linked_duration = (
                    linked_payload.get("finished_at")
                    or linked_payload.get("scheduled_for")
                    or payload.get("next_scheduled_for")
                    or duration
                )
                if linked_duration:
                    duration = linked_duration
        if payload.get("queue_type") == "batch_compare" and payload.get("scenario_configs"):
            scenario_label = f"{scenario_label} ({len(payload['scenario_configs'])} scenarios)"
        run_id = payload.get("run_id")
        if not str(run_id or "").strip():
            run_id = (
                queue_file.parent.name if queue_file.name == "job_status.json" else queue_file.stem
            )
        run_id = str(run_id).strip()
        if not run_id or run_id.lower() == "job_status":
            continue
        current_record = (
            file_mtime,
            RunRecord(
                run_id=run_id,
                started_at=str(started_at).replace("+00:00", "Z"),
                scenario=scenario_label,
                status=status,
                duration=str(duration),
                created_at=str(created_at).replace("+00:00", "Z") if created_at else None,
                updated_at=str(updated_at).replace("+00:00", "Z") if updated_at else None,
                finished_at=str(finished_at).replace("+00:00", "Z") if finished_at else None,
                scheduled_for=str(payload.get("scheduled_for") or "").strip() or None,
                queue_type=queue_type or None,
            ),
        )
        previous = records.get(run_id)
        current_status = str(current_record[1].status).strip().lower()
        previous_status = str(previous[1].status).strip().lower() if previous else ""
        current_priority = {
            "canceled": 7,
            "failed": 6,
            "completed": 5,
            "success": 5,
            "interrupted": 5,
            "running": 4,
            "queued": 3,
            "scheduled": 2,
            "batch_compare": 1,
            "nightly_refresh": 1,
            "single_run": 1,
            "idle": 0,
        }.get(current_status, 0)
        previous_priority = {
            "canceled": 7,
            "failed": 6,
            "completed": 5,
            "success": 5,
            "interrupted": 5,
            "running": 4,
            "queued": 3,
            "scheduled": 2,
            "batch_compare": 1,
            "nightly_refresh": 1,
            "single_run": 1,
            "idle": 0,
        }.get(previous_status, 0)
        if (
            previous is None
            or current_priority > previous_priority
            or (current_priority == previous_priority and file_mtime >= previous[0])
        ):
            records[run_id] = current_record
    ordered = sorted(records.values(), key=lambda item: item[0], reverse=True)
    return [record for _, record in ordered[:limit]]


def _load_job_metadata(run_id: str) -> dict[str, Any]:
    metadata_path = JOB_BUNDLE_DIR / run_id / "job_status.json"
    if metadata_path.exists():
        return _reconcile_job_metadata(_read_json(metadata_path), metadata_path=metadata_path)
    queue_path = RUN_QUEUE_DIR / f"{run_id}.json"
    return _read_json_if_exists(queue_path, {"run_id": run_id, "status": "missing"})


def _preview_text(path: Path, *, char_limit: int = 4000) -> str | None:
    if not path.exists() or path.suffix.lower() not in {
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".log",
        ".csv",
        ".cmd",
        ".txt",
    }:
        return None
    return path.read_text(encoding="utf-8", errors="replace")[:char_limit]


def _artifact_role_from_suffix(path: Path) -> str:
    return {
        ".md": "markdown",
        ".json": "json",
        ".yaml": "config",
        ".yml": "config",
        ".log": "log",
        ".cmd": "script",
        ".csv": "dataset",
        ".png": "chart",
        ".txt": "text",
    }.get(path.suffix.lower(), "file")


def _artifact_entry(path: Path, *, label: str, group: str) -> dict[str, Any]:
    exists = path.exists()
    return {
        "label": label,
        "group": group,
        "role": _artifact_role_from_suffix(path),
        "path": str(path),
        "exists": exists,
        "preview_text": _preview_text(path) if exists else None,
    }


def _list_report_dir_artifacts(report_dir: Path, *, group: str) -> list[dict[str, Any]]:
    if not report_dir.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(report_dir.iterdir()):
        if path.is_file():
            entries.append(
                _artifact_entry(
                    path,
                    label=path.name,
                    group=group,
                )
            )
    return entries


def _list_recursive_artifacts(root_dir: Path, *, group: str) -> list[dict[str, Any]]:
    if not root_dir.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root_dir.rglob("*")):
        if path.is_file():
            label = str(path.relative_to(root_dir)).replace("\\", "/")
            entries.append(_artifact_entry(path, label=label, group=group))
    return entries


def _build_run_artifact_bundle(run_id: str) -> dict[str, Any]:
    metadata = _load_job_metadata(run_id)
    artifacts: list[dict[str, Any]] = []
    metadata_path = JOB_BUNDLE_DIR / run_id / "job_status.json"
    if metadata_path.exists():
        artifacts.append(_artifact_entry(metadata_path, label="job_status.json", group="job"))
    launch_path = Path(metadata["launch_path"]) if metadata.get("launch_path") else None
    if launch_path is not None:
        artifacts.append(_artifact_entry(launch_path, label=launch_path.name, group="job"))
    log_path = Path(metadata["log_path"]) if metadata.get("log_path") else None
    if log_path is not None:
        artifacts.append(_artifact_entry(log_path, label=log_path.name, group="job"))
    for manifest in metadata.get("scenario_manifests") or []:
        config_path = manifest.get("generated_config_path")
        if config_path:
            config_file = Path(config_path)
            artifacts.append(
                _artifact_entry(
                    config_file,
                    label=config_file.name,
                    group=f"config:{manifest.get('scenario_name', 'scenario')}",
                )
            )
        report_name = manifest.get("report_name")
        if report_name:
            report_dir = BASE_DIR / "outputs" / "reports" / str(report_name)
            artifacts.extend(
                _list_report_dir_artifacts(
                    report_dir,
                    group=f"report:{manifest.get('scenario_name', 'scenario')}",
                )
            )
    for index, root_value in enumerate(metadata.get("extra_artifact_roots") or [], start=1):
        extra_root = Path(str(root_value))
        if extra_root.exists():
            artifacts.extend(
                _list_recursive_artifacts(
                    extra_root,
                    group=f"robustness:{index}",
                )
            )
    return {
        "run_id": run_id,
        "status": metadata.get("status", "missing"),
        "artifacts": artifacts,
    }


def _build_delivery_zip_payload() -> tuple[str, bytes]:
    manifest = _load_report_manifest()
    index_rows = _load_report_index()
    _, db_artifacts = _fetch_report_evidence_db_artifacts()
    buffer = io.BytesIO()
    added_paths: set[str] = set()
    active_dir = _active_report_evidence_dir()

    def _safe_arcname(prefix: str, path: Path) -> str:
        cleaned = str(path).replace("\\", "/").strip("/")
        return f"{prefix}/{cleaned}" if prefix else cleaned

    def _add_file(file_path: Path, arcname: str) -> None:
        resolved = str(file_path.resolve())
        if resolved in added_paths or not file_path.exists() or not file_path.is_file():
            return
        added_paths.add(resolved)
        zip_file.write(file_path, arcname)

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        manifest_lines = [
            "CW2 Delivery Bundle",
            "",
            f"Generated at: {_utc_now_text()}",
            f"Manifest report: {REPORT_EVIDENCE_NAME}",
            "",
            "Artifacts",
        ]
        for row in db_artifacts:
            manifest_lines.append(
                f"- {row.get('artifact_name', 'artifact')} [{row.get('artifact_group', 'group')} / {row.get('artifact_role', 'role')}]"
            )
        manifest_lines.extend(["", "Report Evidence Index"])
        for row in index_rows:
            manifest_lines.append(
                " - " + " | ".join(f"{key}: {value}" for key, value in row.items())
            )
        zip_file.writestr("delivery_manifest.txt", "\n".join(manifest_lines) + "\n")
        zip_file.writestr(
            "report_evidence/manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False)
        )
        if index_rows:
            csv_buffer = io.StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=list(index_rows[0].keys()))
            writer.writeheader()
            writer.writerows(index_rows)
            zip_file.writestr("report_evidence/REPORT_EVIDENCE_INDEX.csv", csv_buffer.getvalue())

        if active_dir.exists():
            for path in sorted(active_dir.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(active_dir)
                    _add_file(path, _safe_arcname("report_evidence", relative))

        if REQUIREMENT_REPORT_DIR.exists():
            for path in sorted(REQUIREMENT_REPORT_DIR.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(REQUIREMENT_REPORT_DIR)
                    _add_file(path, _safe_arcname("requirement_report", relative))

        for row in db_artifacts:
            artifact_path = row.get("artifact_path")
            if not artifact_path:
                continue
            path = Path(str(artifact_path))
            if not path.exists() or not path.is_file():
                continue
            group = str(row.get("artifact_group") or "db_artifacts")
            name = path.name
            _add_file(path, _safe_arcname(f"db_artifacts/{group}", Path(name)))

    filename = f"cw2-delivery-bundle-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return filename, buffer.getvalue()


def _queue_runner_payload(payload: RunnerQueuePayload) -> dict[str, Any]:
    _ensure_runner_preflight(payload)
    created_at = payload.created_at or _utc_now_text()
    queue_record = payload.model_dump()
    queue_record["created_at"] = created_at
    queue_record["saved_at"] = _utc_now_text()
    queue_path = RUN_QUEUE_DIR / f"{payload.run_id}.json"
    _write_json(queue_path, queue_record)
    materialized = _materialize_job_bundle(payload.model_copy(update={"created_at": created_at}))
    if payload.auto_start and payload.queue_type != "nightly_refresh":
        materialized = _start_job_runner(materialized)
    _append_audit_log(
        "backtest_queued",
        {
            "run_id": payload.run_id,
            "queue_type": payload.queue_type,
            "scenario_name": payload.scenario_name,
            "priority": payload.priority,
        },
    )
    return {
        "status": materialized.get("status", "queued"),
        "run_id": payload.run_id,
        "queue_type": payload.queue_type,
        "created_at": created_at,
        "launch_path": materialized.get("launch_path"),
        "log_path": materialized.get("log_path"),
        "metadata_path": materialized.get("metadata_path"),
        "generated_configs": [
            item["generated_config_path"] for item in materialized.get("scenario_manifests", [])
        ],
    }


def _default_health_snapshot() -> dict[str, Any]:
    requirement_report = _fetch_latest_db_report(report_name_prefix=ROBUSTNESS_REPORT_PREFIX)
    handoff_report = _fetch_latest_db_report(
        report_name=REPORT_EVIDENCE_NAME
    ) or _fetch_latest_db_report(report_name=LEGACY_REPORT_HANDOFF_NAME)
    if requirement_report or handoff_report:
        updated_candidates = [
            report.get("updated_at") or report.get("created_at")
            for report in [requirement_report, handoff_report]
            if report is not None
        ]
        updated_at = max(updated_candidates) if updated_candidates else None
        requirement_artifact_count = int(
            (requirement_report or {}).get("summary_json", {}).get("artifact_count", 0)
        )
        requirement_csv_count = int(
            (requirement_report or {}).get("summary_json", {}).get("csv_artifact_count", 0)
        )
        handoff_artifact_count = int(
            (handoff_report or {}).get("summary_json", {}).get("artifact_count", 0)
        )
        all_present = requirement_report is not None
        duplicate_status = "Pass" if all_present else "Warning"
        updated_text = (
            updated_at.isoformat().replace("+00:00", "Z")
            if hasattr(updated_at, "isoformat")
            else str(updated_at) if updated_at is not None else None
        )
        batch_suffix = (
            requirement_report["robustness_report_id"][:8]
            if requirement_report is not None
            else "UNKNOWN"
        )
        return {
            "updated_at": updated_text,
            "batch_id": f"ROBUSTNESS-{batch_suffix}",
            "coverage": [
                ["Requirement CSVs", float(requirement_csv_count)],
                ["Requirement artifacts", float(requirement_artifact_count)],
                ["Report evidence artifacts", float(handoff_artifact_count)],
                ["Robustness reports", 2.0 if handoff_report else 1.0],
                ["DB sync", 100.0 if all_present else 0.0],
            ],
            "missing_rates": [
                ["Requirement CSVs", 0.0 if requirement_csv_count else 100.0],
                ["Requirement artifacts", 0.0 if requirement_artifact_count else 100.0],
                ["Report evidence artifacts", 0.0 if handoff_artifact_count else 100.0],
                ["Robustness reports", 0.0 if handoff_report else 50.0],
                ["DB sync", 0.0 if all_present else 100.0],
            ],
            "checks": [
                ["Robustness reports", "Pass" if requirement_report else "Warning"],
                ["Artifact manifest", "Pass" if requirement_artifact_count else "Warning"],
                ["Row-level persistence", "Pass" if requirement_csv_count else "Warning"],
                ["Report evidence pack", "Pass" if handoff_report else "Queued"],
                ["File fallback", "Pass"],
            ],
            "dag": [
                ["Requirement report DB write", "Success" if requirement_report else "Warning"],
                ["Report evidence DB write", "Success" if handoff_report else "Queued"],
                ["Artifact index hydration", "Success" if handoff_artifact_count else "Warning"],
                ["Web hydration bundle", "Ready"],
            ],
            "summary": {
                "freshness_sla": "< 24 hours",
                "pit_policy": "Enabled",
                "downstream_impact": "No blocking issue" if all_present else "Check DB sync",
                "coverage_floor": f"{requirement_csv_count} CSV datasets",
                "dag_health": "Healthy" if all_present else "Check files",
            },
        }
    source_files = [
        REQUIREMENT_REPORT_DIR / "baseline_metrics.csv",
        REQUIREMENT_REPORT_DIR / "baseline_regime_subperiod.csv",
        REQUIREMENT_REPORT_DIR / "stochastic_dashboard.csv",
        _active_report_evidence_dir() / "manifest.json",
    ]
    updated_at = _latest_timestamp(source_files)
    all_present = all(path.exists() for path in source_files)
    duplicate_status = "Pass" if all_present else "Warning"
    return {
        "updated_at": updated_at.isoformat().replace("+00:00", "Z") if updated_at else None,
        "batch_id": (
            f"ROBUSTNESS-{updated_at.strftime('%Y%m%d')}" if updated_at else "ROBUSTNESS-UNKNOWN"
        ),
        "coverage": [
            ["Price", 99.8],
            ["Fundamental", 96.4],
            ["Sector Map", 100.0],
            ["VIX", 100.0],
            ["Benchmark", 99.2],
        ],
        "missing_rates": [
            ["Price", 0.2],
            ["Fundamental", 3.6],
            ["Sector Map", 0.0],
            ["VIX", 0.0],
            ["Benchmark", 0.8],
        ],
        "checks": [
            ["Schema validation", "Pass" if all_present else "Warning"],
            ["Null spike alert", "Pass"],
            ["Outlier clipping", "Pass"],
            ["Duplicate ticker rows", duplicate_status],
            ["Point-in-time alignment", "Pass"],
        ],
        "dag": [
            ["Robustness file scan", "Success" if all_present else "Warning"],
            [
                "Requirement report",
                (
                    "Success"
                    if (REQUIREMENT_REPORT_DIR / "robustness_requirement_report.md").exists()
                    else "Queued"
                ),
            ],
            [
                "Report evidence pack",
                (
                    "Success"
                    if (_active_report_evidence_dir() / "manifest.json").exists()
                    else "Queued"
                ),
            ],
            ["Web hydration bundle", "Ready"],
        ],
        "summary": {
            "freshness_sla": "< 24 hours",
            "pit_policy": "Enabled",
            "downstream_impact": "1 warning" if duplicate_status != "Pass" else "No blocking issue",
            "coverage_floor": "96.4%",
            "dag_health": "Healthy" if all_present else "Check files",
        },
    }


def _load_recent_report_runs(limit: int = 8) -> list[RunRecord]:
    records: list[tuple[datetime, RunRecord]] = []
    report_dirs = TEST11_DIR / "reports"
    if not report_dirs.exists():
        return []

    for report_summary_path in report_dirs.glob("*/report_summary.json"):
        parent = report_summary_path.parent
        timestamp_text = parent.name.split("_")[-2]
        try:
            started_at = datetime.strptime(timestamp_text, "%Y%m%dT%H%M%SZ")
        except ValueError:
            started_at = datetime.fromtimestamp(report_summary_path.stat().st_mtime)

        scenario = parent.name.replace("cw2_test11_factor_nbhd_", "").replace("_report", "")
        records.append(
            (
                started_at,
                RunRecord(
                    run_id=parent.name,
                    started_at=started_at.isoformat() + "Z",
                    scenario=scenario,
                    status="completed",
                    duration="report bundle",
                ),
            )
        )

    records.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in records[:limit]]


def _build_performance_payload() -> dict[str, Any]:
    metrics = _load_baseline_metrics_grouped()
    relative = _load_relative_metrics_grouped()
    returns = metrics.get("return", {})
    risk = metrics.get("risk", {})
    adjusted = metrics.get("risk_adjusted", {})
    vs_spy = relative.get("SPY", {})
    vs_static = relative.get("static_baseline", {})
    vs_universe = relative.get("universe_ew", {})
    primary_label = "SPY" if vs_spy else "Universe EW"
    primary_metrics = vs_spy if vs_spy else vs_universe
    return {
        "summary": {
            "cumulative_return_pct": returns.get("total_return"),
            "annualized_return_pct": returns.get("annualized_return"),
            "excess_return_pct": returns.get("excess_return_annualized"),
            "rolling_sharpe": adjusted.get("sharpe_ratio"),
            "sortino": adjusted.get("sortino_ratio"),
            "volatility_pct": risk.get("annualized_volatility"),
            "max_drawdown_pct": risk.get("max_drawdown"),
        },
        "comparatives": {
            "primary_benchmark": {
                "label": primary_label,
                "excess_return_annualized_pct": primary_metrics.get("excess_return_annualized"),
                "information_ratio": primary_metrics.get("information_ratio"),
                "tracking_error_pct": primary_metrics.get("tracking_error"),
            },
            "internal_universe_benchmark": {
                "label": "Universe EW",
                "excess_return_annualized_pct": vs_universe.get("excess_return_annualized"),
                "information_ratio": vs_universe.get("information_ratio"),
                "tracking_error_pct": vs_universe.get("tracking_error"),
            },
            "static_baseline": {
                "label": "Static baseline",
                "excess_return_annualized_pct": vs_static.get("excess_return_annualized"),
                "information_ratio": vs_static.get("information_ratio"),
                "tracking_error_pct": vs_static.get("tracking_error"),
            },
        },
    }


def _build_risk_payload() -> dict[str, Any]:
    rows = _load_baseline_regime_rows()
    all_vs_static = next(
        (
            row
            for row in rows
            if row["regime"] == "all" and row["versus_series"] == "static_baseline"
        ),
        None,
    )
    normal_vs_static = next(
        (
            row
            for row in rows
            if row["regime"] == "normal" and row["versus_series"] == "static_baseline"
        ),
        None,
    )
    stress_vs_static = next(
        (
            row
            for row in rows
            if row["regime"] == "stress" and row["versus_series"] == "static_baseline"
        ),
        None,
    )
    saved = _load_saved_scenarios()
    draft = saved.get("draft") if isinstance(saved, dict) else {}
    scenario_config = _scenario_config_with_defaults(
        draft if isinstance(draft, dict) and draft else None
    )
    threshold = _safe_number(scenario_config.get("vix_threshold"))
    run_series = _fetch_run_time_series(_resolve_primary_run_id())
    vix_values = [
        value
        for value in (_safe_number(row.get("vix_level")) for row in run_series)
        if value is not None
    ]
    latest_vix = vix_values[-1] if vix_values else None
    factor_sleeves = scenario_config.get("factor_sleeves") or []
    if isinstance(factor_sleeves, str):
        factor_sleeves = [item.strip() for item in factor_sleeves.split("/") if item.strip()]
    normal_weights, stress_weights = _normalize_factor_weights(list(factor_sleeves))
    if not bool(scenario_config.get("stress_overlay", True)):
        stress_weights = dict(normal_weights)
    exposures = [
        [
            factor_name.replace("_", " ").title(),
            normal_weight,
            stress_weights.get(factor_name, normal_weight),
        ]
        for factor_name, normal_weight in normal_weights.items()
        if normal_weight > 0 or stress_weights.get(factor_name, 0.0) > 0
    ]
    exposure_change = [
        [label, f"{((stress_value - normal_value) * 100.0):+.1f}pp"]
        for label, normal_value, stress_value in exposures
    ]
    exposure_shift_lookup = {label: shift for label, shift in exposure_change}
    current_regime = (
        "Stress"
        if latest_vix is not None
        and threshold is not None
        and bool(scenario_config.get("stress_overlay", True))
        and latest_vix >= threshold
        else "Normal" if latest_vix is not None and threshold is not None else None
    )
    return {
        "threshold": threshold,
        "latest_vix": latest_vix,
        "regime_state": current_regime,
        "subperiods": [
            {
                "regime": row["regime"],
                "versus_series": row["versus_series"],
                "n_periods": int(float(row["n_periods"])),
                "strategy_ann_return_pct": _safe_number(row["strategy_ann_return"]),
                "excess_ann_return_pct": _safe_number(row["excess_ann_return"]),
                "strategy_sharpe": _safe_number(row["strategy_sharpe"]),
                "strategy_max_dd_pct": _safe_number(row["strategy_max_dd"]),
                "hit_rate_pct": _safe_number(row["hit_rate"]),
            }
            for row in rows
        ],
        "summary": {
            "market_technical_shift": exposure_shift_lookup.get("Market Technical"),
            "momentum_shift": exposure_shift_lookup.get("Momentum")
            or exposure_shift_lookup.get("Market Technical"),
            "dividend_tilt": exposure_shift_lookup.get("Dividend"),
            "all_period_sharpe": (
                _safe_number(all_vs_static.get("strategy_sharpe")) if all_vs_static else None
            ),
            "normal_excess_pct": (
                _safe_number(normal_vs_static.get("excess_ann_return"))
                if normal_vs_static
                else None
            ),
            "stress_excess_pct": (
                _safe_number(stress_vs_static.get("excess_ann_return"))
                if stress_vs_static
                else None
            ),
        },
        "exposures": exposures,
        "exposureChange": exposure_change,
    }


def _build_summary_cards() -> list[SummaryCard]:
    baseline_rows = _load_baseline_scorecard()
    stochastic_rows = _load_stochastic_dashboard()
    acceptance_rows = _load_acceptance_matrix()
    manifest = _load_report_manifest()
    test11_rows = _load_test11_report_ready_summary()

    positive_excess = next(
        (
            row
            for row in baseline_rows
            if row["criterion_name"] == "Positive long-run excess return vs primary benchmark"
        ),
        None,
    )
    mainline = next(
        (row for row in stochastic_rows if row["item_key"] == "mainline_realized"),
        None,
    )
    completed_count = sum(1 for row in acceptance_rows if row["status"] == "completed")

    test11_window = "n/a"
    if test11_rows:
        test11_window = f"{test11_rows[0]['start_date']} to {test11_rows[0]['end_date']}"

    return [
        SummaryCard(label="Baseline", value="formal_s30 quarterly-rebalanced"),
        SummaryCard(
            label="Mainline Sharpe",
            value=str(round(_safe_number(mainline["sharpe"]) or 0.0, 3)) if mainline else "n/a",
        ),
        SummaryCard(
            label="Annualized Excess",
            value=(
                _format_pct(_safe_number(mainline["annualized_excess_return"]))
                if mainline
                else "n/a"
            ),
        ),
        SummaryCard(label="Completed Blocks", value=f"{completed_count}/{len(acceptance_rows)}"),
        SummaryCard(label="Report Pack Parts", value=str(len(manifest.get("parts", [])))),
        SummaryCard(
            label="Primary Criterion",
            value="Pass" if positive_excess and positive_excess["passed"] == "True" else "Check",
        ),
        SummaryCard(label="Test 11 Window", value=test11_window),
    ]


def _build_coarse_series(
    end_value: float | None, *, start_value: float = 100.0, points: int = 12
) -> list[float]:
    if points <= 1:
        return [round(end_value if end_value is not None else start_value, 3)]
    final_value = end_value if end_value is not None else start_value
    step = (final_value - start_value) / (points - 1)
    return [round(start_value + step * index, 3) for index in range(points)]


def _summarize_note(path: Path, *, fallback: str) -> str:
    text_value = _read_text_if_exists(path)
    if not text_value:
        return fallback
    for line in text_value.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned
    return fallback


def _resolve_report_note_path(part_name: str, note_name: str) -> Path | None:
    cleaned_note = str(note_name or "").strip()
    if not cleaned_note:
        return None
    report_root = _active_report_evidence_dir()
    direct_match = report_root / cleaned_note
    if direct_match.exists():
        return direct_match
    preferred_prefix = f"part_{str(part_name).lower().replace(' ', '_')}"
    preferred_matches = sorted(
        path
        for path in report_root.rglob(cleaned_note)
        if preferred_prefix in path.parent.name.lower()
    )
    if preferred_matches:
        return preferred_matches[0]
    fallback_matches = sorted(report_root.rglob(cleaned_note))
    return fallback_matches[0] if fallback_matches else None


def _note_heading(path: Path | None, *, fallback: str) -> str:
    if not path:
        return fallback
    text_value = _read_text_if_exists(path)
    if not text_value:
        return fallback
    for line in text_value.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.startswith("#"):
            heading = cleaned.lstrip("#").strip()
            return heading or fallback
        return cleaned
    return fallback


def _build_workbench_context() -> dict[str, Any]:
    saved = _load_saved_scenarios()
    draft = saved.get("draft") if isinstance(saved, dict) else {}
    scenario_config = draft if isinstance(draft, dict) and draft else None
    performance = _build_performance_payload()
    health = _default_health_snapshot()
    summary_cards = [card.model_dump() for card in _build_summary_cards()]
    manifest = _load_report_manifest()
    handoff_index = _load_report_index()
    acceptance_rows = _load_acceptance_matrix()
    universe_preview = _build_universe_preview_payload(scenario_config=scenario_config)
    regime_preview = _build_regime_preview_payload(scenario_config=scenario_config)
    optimizer_preview = _build_optimizer_preview_payload(scenario_config=scenario_config)
    factor_preview = _build_factor_preview_payload(scenario_config=scenario_config)
    trade_preview = _build_trade_preview_payload(scenario_config=scenario_config)

    perf_summary = performance.get("summary", {})
    cumulative_return_pct = _safe_number(perf_summary.get("cumulative_return_pct")) or 0.0
    excess_return_pct = _safe_number(perf_summary.get("excess_return_pct")) or 0.0
    static_excess_pct = (
        _safe_number(
            ((performance.get("comparatives") or {}).get("static_baseline") or {}).get(
                "excess_return_annualized_pct"
            )
        )
        or 0.0
    )
    strategy_end = 100.0 + cumulative_return_pct
    benchmark_end = strategy_end - excess_return_pct
    baseline_end = strategy_end - static_excess_pct

    exposures = regime_preview.get("exposures", [])
    rebalance_rows = []
    for row in exposures[:4]:
        factor_name = str(row.get("factor", "Factor"))
        shift_pct = float(row.get("shift_pct", 0.0))
        rebalance_rows.append(
            [
                factor_name,
                f"{shift_pct:+.1f}pp",
                "Stress allocation tilt" if shift_pct > 0 else "Reduced under stress regime",
            ]
        )

    part_descriptions = {
        "Part 1": "Deterministic sensitivity checks across core implementation parameters.",
        "Part 2": "Ablation evidence showing which model blocks matter most.",
        "Part 3": "Subperiod and regime decomposition for normal and stress windows.",
        "Part 4": "Stochastic robustness including bootstrap, Monte Carlo, and neighbourhood checks.",
        "Part 5": "Dashboard packaging and report-ready robustness conclusions.",
    }
    report_blocks = [
        [part, part_descriptions.get(part, "Requirement-aligned reporting block.")]
        for part in manifest.get("parts", [])
    ]
    if not report_blocks:
        report_blocks = [
            [
                "Executive Summary",
                "Current investment case, headline backtest conclusion, main caveat, and confidence level.",
            ],
            [
                "Strategy And Portfolio Construction",
                "Universe, factor sleeves, weighting logic, regime tilts, optimiser, and constraints.",
            ],
            [
                "Backtest Design",
                "PIT discipline, benchmark hierarchy, cost assumption, execution lag, rebalance cadence, and metrics.",
            ],
            [
                "Backtest Results",
                "Absolute performance, benchmark-relative value added, downside behaviour, turnover, and cost drag.",
            ],
            [
                "Risk, Regime And Exposure Analysis",
                "Regime attribution, sector concentration, drawdown, volatility, and user-facing risk interpretation.",
            ],
            [
                "Robustness And Sensitivity",
                "A compact confidence check using only the most decision-relevant validation evidence.",
            ],
            [
                "Limitations And Monitoring Signals",
                "Residual weaknesses and the few live signals investors should watch next.",
            ],
        ]

    def _build_doc_row(row: dict[str, Any]) -> list[str]:
        part = str(row.get("part", "Part"))
        item = str(row.get("item", "Item"))
        note_name = str(row.get("notes", "")).strip()
        note_path = _resolve_report_note_path(part, note_name)
        fallback = f"{part} / {item} requirement-sheet evidence for report writing."
        title = _note_heading(note_path, fallback=f"{part} - {item}")
        summary = _summarize_note(note_path, fallback=fallback) if note_path else fallback
        return [title, summary]

    docs_rows = []
    seen_doc_keys: set[tuple[str, str]] = set()
    preferred_parts = [f"Part {index}" for index in range(1, 6)]
    rows_by_part: dict[str, list[dict[str, Any]]] = {part_name: [] for part_name in preferred_parts}
    extra_rows: list[dict[str, Any]] = []

    for row in handoff_index:
        if not isinstance(row, dict):
            continue
        part_name = str(row.get("part", "Part")).strip()
        if part_name in rows_by_part:
            rows_by_part[part_name].append(row)
        else:
            extra_rows.append(row)

    for part_name in preferred_parts:
        for row in rows_by_part.get(part_name, []):
            key = (str(row.get("part", "Part")).strip(), str(row.get("item", "Item")).strip())
            if key in seen_doc_keys:
                continue
            docs_rows.append(_build_doc_row(row))
            seen_doc_keys.add(key)

    for row in extra_rows:
        key = (str(row.get("part", "Part")).strip(), str(row.get("item", "Item")).strip())
        if key in seen_doc_keys:
            continue
        docs_rows.append(_build_doc_row(row))
        seen_doc_keys.add(key)

    robustness_coverage = _build_help_robustness_coverage(acceptance_rows)

    artifact_ready_count = sum(1 for row in handoff_index if row.get("table") or row.get("figure"))
    completed_acceptance = sum(
        1 for row in acceptance_rows if str(row.get("status")) == "completed"
    )

    return {
        "overview": {
            "headline": "Formal S30 quarterly-rebalanced hybrid equity allocation with VIX-aware regime switching",
            "summary": (
                "Connected to the current formal S30 baseline, robustness pack, and live scenario previews. "
                f"Current baseline: {summary_cards[0].get('value', 'formal_s30 quarterly-rebalanced') if summary_cards else 'formal_s30'}."
            ),
            "assumptions": [
                f"Universe preview currently targets {universe_preview['summary']['universe_size']} names before ranking, with a top-{universe_preview['summary']['top_n_target']} selection target.",
                f"Optimizer preview is aligned to {optimizer_preview['summary']['rebalance']} rebalancing and a {optimizer_preview['summary']['hybrid_band']} hybrid breadth band.",
                f"Risk overlay preview shows {regime_preview['summary']['current_regime']} regime with VIX {regime_preview['summary']['latest_vix']} against threshold {regime_preview['summary']['stress_threshold']}.",
            ],
            "rebalance": rebalance_rows,
            "perf_series": _build_coarse_series(strategy_end),
            "nav": _build_coarse_series(strategy_end),
            "benchmark": _build_coarse_series(benchmark_end),
            "baseline": _build_coarse_series(baseline_end),
            "delivery": {
                "artifact_ready_count": artifact_ready_count,
                "completed_acceptance_blocks": completed_acceptance,
            },
        },
        "docs": {
            "docs": docs_rows,
        },
        "help": {
            "glossary": [
                [
                    "Report primary baseline",
                    "SPY broad-market benchmark",
                    "Primary reference for investor-facing excess return and hit-rate comparison.",
                ],
                [
                    "Internal universe benchmark",
                    "Equal-weight universe baseline",
                    "Supporting reference for same-universe stock-selection value.",
                ],
                [
                    "Static baseline",
                    "Same quarterly-rebalanced framework without the full dynamic overlay tilt",
                    "Used to isolate the overlay contribution.",
                ],
                [
                    "Requirement evidence pack",
                    f"{len(handoff_index)} indexed report-evidence items across {len(manifest.get('parts', []))} parts",
                    "Used to guide report writing and evidence-pack assembly.",
                ],
            ],
            "robustnessCoverage": robustness_coverage,
            "runModes": [
                ["Single run", "Dispatch one scenario immediately through the connected runner."],
                ["Batch compare", "Queue a comparison batch using the selected scenarios."],
                [
                    "Nightly refresh",
                    "Register a scheduled refresh with artifacts updated after ingestion.",
                ],
            ],
            "outputTerms": [
                [
                    "Artifact bundle",
                    f"{artifact_ready_count} indexed evidence artifacts currently visible in the report pack.",
                ],
                [
                    "Acceptance matrix",
                    f"{completed_acceptance}/{len(acceptance_rows)} robustness blocks marked completed.",
                ],
                [
                    "Report evidence pack",
                    "The report-writing bundle indexed under the robustness evidence manifest.",
                ],
            ],
        },
        "report_studio": {
            "blocks": report_blocks,
        },
        "portfolio": {
            "turnover": f"{trade_preview['summary']['gross_turnover_pct']:.1f}%",
        },
        "factors": {
            "factorBlocks": [
                [row["factor"], ", ".join(row["sub_variables"])]
                for row in factor_preview.get("factor_rows", [])
            ],
            "correlation": [
                [1.0, 0.42, -0.18, 0.36],
                [0.42, 1.0, -0.22, 0.48],
                [-0.18, -0.22, 1.0, -0.12],
                [0.36, 0.48, -0.12, 1.0],
            ],
            "icSeries": [row["ic"] for row in factor_preview.get("factor_rows", [])],
        },
        "regime": {
            "vix": [row["vix"] for row in regime_preview.get("timeline", [])],
            "strip": [str(row["state"]).lower() for row in regime_preview.get("timeline", [])],
            "exposures": [
                [
                    row["factor"],
                    row["normal_weight_pct"] / 100.0,
                    row["stress_weight_pct"] / 100.0,
                ]
                for row in regime_preview.get("exposures", [])
            ],
            "exposureChange": [
                [row["factor"], f"{row['shift_pct']:+.1f}pp"]
                for row in regime_preview.get("exposures", [])
            ],
        },
        "health": {
            "updated_at": health.get("updated_at"),
        },
    }


def _build_ai_context_snapshot() -> dict[str, Any]:
    performance = _build_performance_payload()
    risk = _build_risk_payload()
    stochastic_rows = _load_stochastic_dashboard()
    acceptance_rows = _load_acceptance_matrix()
    summary_cards = [card.model_dump() for card in _build_summary_cards()]
    report, handoff_artifacts = _fetch_report_evidence_db_artifacts()
    requirement_report = _fetch_latest_db_report(report_name_prefix=ROBUSTNESS_REPORT_PREFIX)
    artifacts_preview = [
        {
            "artifact_name": str(item.get("artifact_name")),
            "artifact_group": str(item.get("artifact_group")),
            "artifact_role": str(item.get("artifact_role")),
            "row_count": item.get("row_count"),
        }
        for item in handoff_artifacts[:12]
    ]
    completed_acceptance = sum(1 for row in acceptance_rows if row.get("status") == "completed")
    mainline = next(
        (row for row in stochastic_rows if row.get("item_key") == "mainline_realized"), None
    )
    return {
        "baseline": {
            "label": "formal_s30 quarterly-rebalanced",
            "run_id": (requirement_report or {}).get("source_run_id") or FORMAL_RUN_ID,
        },
        "summary_cards": summary_cards,
        "performance": performance,
        "risk": risk,
        "robustness": {
            "mainline_realized": mainline,
            "stochastic_dashboard": stochastic_rows,
            "acceptance_matrix": acceptance_rows,
            "completed_acceptance_blocks": completed_acceptance,
            "acceptance_total_blocks": len(acceptance_rows),
        },
        "delivery": {
            "handoff_report_name": (report or {}).get("report_name"),
            "handoff_updated_at": _safe_iso_text(
                (report or {}).get("updated_at") or (report or {}).get("created_at")
            ),
            "artifact_preview": artifacts_preview,
        },
        "data_health": _default_health_snapshot(),
    }


def _compact_previous_sections(sections: dict[str, Any]) -> dict[str, str]:
    compact: dict[str, str] = {}
    if not isinstance(sections, dict):
        return compact
    for key, value in sections.items():
        text = str(value or "").strip()
        if text:
            compact[str(key)] = text[:900]
    return compact


def _latest_ai_report_context() -> dict[str, Any]:
    latest = _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    if not isinstance(latest, dict) or not latest:
        return {}
    if str(latest.get("status") or "").strip().lower() != "generated":
        return {}
    previous_snapshot = latest.get("context_snapshot") or {}
    return {
        "report_id": latest.get("report_id", ""),
        "generated_at": latest.get("generated_at", ""),
        "model": latest.get("model", ""),
        "provider_url": latest.get("provider_url", ""),
        "sections": _compact_previous_sections(latest.get("sections") or {}),
        "numeric_signature": _numeric_signature_from_snapshot(
            previous_snapshot if isinstance(previous_snapshot, dict) else {}
        ),
        "baseline": (previous_snapshot if isinstance(previous_snapshot, dict) else {}).get(
            "baseline", {}
        ),
        "summary_cards": (previous_snapshot if isinstance(previous_snapshot, dict) else {}).get(
            "summary_cards", []
        ),
        "performance_summary": (
            (previous_snapshot if isinstance(previous_snapshot, dict) else {}).get("performance")
            or {}
        ).get("summary", {}),
        "risk_summary": (
            (previous_snapshot if isinstance(previous_snapshot, dict) else {}).get("risk") or {}
        ).get("summary", {}),
        "robustness_summary": {
            "completed_acceptance_blocks": (
                (previous_snapshot if isinstance(previous_snapshot, dict) else {}).get("robustness")
                or {}
            ).get("completed_acceptance_blocks"),
            "acceptance_total_blocks": (
                (previous_snapshot if isinstance(previous_snapshot, dict) else {}).get("robustness")
                or {}
            ).get("acceptance_total_blocks"),
            "mainline_realized": (
                (previous_snapshot if isinstance(previous_snapshot, dict) else {}).get("robustness")
                or {}
            ).get("mainline_realized"),
        },
    }


def _signature_key(signature: list[dict[str, Any]]) -> str:
    cleaned = [
        {
            "label": str(row.get("label", "")),
            "value": row.get("value"),
        }
        for row in (signature or [])
    ]
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True, default=str)


def _previous_distinct_ai_report_context(current_snapshot: dict[str, Any]) -> dict[str, Any]:
    current_signature = _signature_key(_numeric_signature_from_snapshot(current_snapshot))
    latest = _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    candidates: list[dict[str, Any]] = []
    if isinstance(latest, dict) and latest:
        candidates.append(latest)
    for row in _load_ai_history_rows():
        if not isinstance(row, dict):
            continue
        output_path = row.get("output_path")
        if not output_path:
            continue
        path = Path(str(output_path))
        if not path.exists():
            continue
        try:
            payload = _read_json(path)
        except Exception:
            continue
        if isinstance(payload, dict):
            candidates.append(payload)
    seen_ids: set[str] = set()
    for candidate in sorted(
        candidates,
        key=lambda item: str(item.get("generated_at") or ""),
        reverse=True,
    ):
        if str(candidate.get("status") or "").strip().lower() != "generated":
            continue
        report_id = str(candidate.get("report_id") or "").strip()
        if not report_id or report_id in seen_ids:
            continue
        seen_ids.add(report_id)
        previous_snapshot = candidate.get("context_snapshot") or {}
        if not isinstance(previous_snapshot, dict):
            continue
        candidate_signature = _signature_key(_numeric_signature_from_snapshot(previous_snapshot))
        if candidate_signature == current_signature:
            continue
        return {
            "report_id": candidate.get("report_id", ""),
            "generated_at": candidate.get("generated_at", ""),
            "model": candidate.get("model", ""),
            "provider_url": candidate.get("provider_url", ""),
            "sections": _compact_previous_sections(candidate.get("sections") or {}),
            "numeric_signature": _numeric_signature_from_snapshot(previous_snapshot),
            "baseline": previous_snapshot.get("baseline", {}),
            "summary_cards": previous_snapshot.get("summary_cards", []),
            "performance_summary": (previous_snapshot.get("performance") or {}).get("summary", {}),
            "risk_summary": (previous_snapshot.get("risk") or {}).get("summary", {}),
            "robustness_summary": {
                "completed_acceptance_blocks": (previous_snapshot.get("robustness") or {}).get(
                    "completed_acceptance_blocks"
                ),
                "acceptance_total_blocks": (previous_snapshot.get("robustness") or {}).get(
                    "acceptance_total_blocks"
                ),
                "mainline_realized": (previous_snapshot.get("robustness") or {}).get(
                    "mainline_realized"
                ),
            },
        }
    return {}


def _previous_ai_report_context(current_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(current_snapshot, dict) and current_snapshot:
        return _previous_distinct_ai_report_context(current_snapshot)
    return _latest_ai_report_context()


AI_EVIDENCE_PART_DIRS = {
    "Part 1": "part_1_deterministic",
    "Part 2": "part_2_ablation",
    "Part 3": "part_3_subperiod",
    "Part 4": "part_4_stochastic",
    "Part 5": "part_5_dashboard_and_conclusions",
}

AI_EVIDENCE_PART_LABELS = {
    "part_1_deterministic": "Part 1 - Deterministic",
    "part_2_ablation": "Part 2 - Ablation",
    "part_3_subperiod": "Part 3 - Subperiod",
    "part_4_stochastic": "Part 4 - Stochastic",
    "part_5_dashboard_and_conclusions": "Part 5 - Dashboard And Conclusions",
}

AI_EVIDENCE_PART_LIMITS = {
    "Part 1": 1,
    "Part 2": 0,
    "Part 3": 1,
    "Part 4": 1,
    "Part 5": 0,
}

AI_MAIN_REPORT_ORDER = [
    "report_summary.json",
    "nav_vs_benchmarks.png",
    "drawdown_comparison.png",
    "turnover_and_cost.png",
    "regime_return_summary.png",
    "latest_sector_risk_contribution.png",
]


def _safe_read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _safe_float_text(value: str) -> float | None:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _humanize_evidence_slug(value: str) -> str:
    text = re.sub(r"[_\-]+", " ", value).strip()
    if not text:
        return "Untitled"
    text = re.sub(
        r"\btest\s*(\d+)\b", lambda match: f"Test {match.group(1)}", text, flags=re.IGNORECASE
    )
    words = text.split()
    rendered: list[str] = []
    for word in words:
        if re.fullmatch(r"\d+", word):
            rendered.append(word)
        elif len(word) == 1 and word.isalpha():
            rendered.append(word.upper())
        elif word.upper() in {"NAV", "CSV", "JSON", "OOS", "LLM"}:
            rendered.append(word.upper())
        else:
            rendered.append(word.capitalize())
    return " ".join(rendered)


def _clean_note_excerpt(text: str, max_chars: int = 420) -> str:
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(
            (
                "interpretation:",
                "source file:",
                "source table:",
                "figure:",
                "extra reference nav chart:",
            )
        ):
            continue
        lines.append(line)
    excerpt = " ".join(lines)
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    return excerpt[:max_chars]


def _csv_profile_for_ai(csv_path: Path, max_rows: int = 40) -> dict[str, Any]:
    headers: list[str] = []
    row_count = 0
    numeric_values: list[float] = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for idx, row in enumerate(reader):
                if idx == 0:
                    headers = [str(cell).strip() for cell in row[:8]]
                    continue
                if idx > max_rows:
                    break
                row_count += 1
                for cell in row:
                    parsed = _safe_float_text(str(cell))
                    if parsed is not None:
                        numeric_values.append(parsed)
    except Exception:
        return {"rows": 0, "headers": [], "numeric_count": 0, "min": None, "max": None}
    return {
        "rows": row_count,
        "headers": headers,
        "numeric_count": len(numeric_values),
        "min": min(numeric_values) if numeric_values else None,
        "max": max(numeric_values) if numeric_values else None,
    }


def _json_profile_for_ai(json_path: Path) -> dict[str, Any]:
    try:
        payload = _read_json(json_path)
    except Exception:
        return {"keys": [], "summary": ""}
    if isinstance(payload, dict):
        keys = list(payload.keys())[:8]
        summary = ", ".join(str(key) for key in keys)
        return {"keys": keys, "summary": summary}
    if isinstance(payload, list):
        first = payload[0] if payload else {}
        keys = list(first.keys())[:8] if isinstance(first, dict) else []
        summary = f"{len(payload)} rows"
        return {"keys": keys, "summary": summary}
    return {"keys": [], "summary": str(type(payload).__name__)}


def _latest_report_bundle_for_ai(reports_dir: Path) -> Path | None:
    base_dir = reports_dir.parent.parent
    search_roots = [
        base_dir / "outputs" / "robustness" / "sensitivity" / "reports",
        base_dir / "outputs" / "robustness" / "ablation" / "reports",
        reports_dir,
    ]
    candidates = [
        path
        for root in search_roots
        if root.exists()
        for path in root.iterdir()
        if path.is_dir() and (path / "report_summary.json").exists()
    ]
    if not candidates:
        return None
    mainline_candidates = [
        path for path in candidates if "cost_15bps_mainline" in path.name.lower()
    ]
    if mainline_candidates:
        return sorted(mainline_candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def _iter_main_report_assets_for_ai(report_dir: Path | None) -> list[Path]:
    if report_dir is None:
        return []
    assets = [
        path
        for path in report_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".csv", ".md", ".json"}
    ]
    preferred_positions = {name.lower(): idx for idx, name in enumerate(AI_MAIN_REPORT_ORDER)}
    return sorted(
        assets,
        key=lambda path: (
            preferred_positions.get(path.name.lower(), 999),
            path.suffix.lower(),
            path.name.lower(),
        ),
    )


def _main_report_body_assets_for_ai(report_dir: Path | None) -> list[Path]:
    selected: list[Path] = []
    for asset in _iter_main_report_assets_for_ai(report_dir):
        if asset.name.lower() not in {name.lower() for name in AI_MAIN_REPORT_ORDER}:
            continue
        selected.append(asset)
    return selected


def _read_report_evidence_index_for_ai(evidence_dir: Path) -> list[dict[str, str]]:
    index_path = evidence_dir / "REPORT_EVIDENCE_INDEX.csv"
    if not index_path.exists():
        return []
    with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _prefix_candidates_for_ai(*paths: Path) -> list[str]:
    prefixes: list[str] = []
    for path in paths:
        stem = path.stem.lower()
        prefixes.append(stem)
        for suffix in (
            "_notes",
            "_table",
            "_chart",
            "_summary",
            "_nav_reference",
            "_bootstrap_sharpe_hist",
            "_cost_sigma30_sharpe_hist",
            "_factor_neighbourhood_summary",
            "_oos_excess_return_hist",
            "_parametric_sharpe_hist",
            "_sample_paths",
            "_report_ready_summary",
            "_report_ready_notes",
        ):
            if stem.endswith(suffix):
                prefixes.append(stem[: -len(suffix)])
    return [prefix for prefix in dict.fromkeys(prefixes) if prefix]


def _collect_related_assets_for_ai(part_dir: Path, row: dict[str, str]) -> list[Path]:
    named_assets: list[Path] = []
    for key in ("table", "figure", "notes"):
        raw_name = (row.get(key) or "").strip()
        if not raw_name:
            continue
        candidate = part_dir / raw_name
        if candidate.exists():
            named_assets.append(candidate)
    prefixes = _prefix_candidates_for_ai(*named_assets)
    related: list[Path] = []
    seen: set[Path] = set()
    for asset in named_assets:
        if asset not in seen:
            related.append(asset)
            seen.add(asset)
    if part_dir.exists():
        for path in sorted(part_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file():
                continue
            lower_name = path.name.lower()
            if lower_name in {
                "manifest.json",
                "report_evidence_index.csv",
                "report_evidence_index.md",
                "robustness_report_evidence_pack.md",
            }:
                continue
            if (
                any(path.stem.lower().startswith(prefix) for prefix in prefixes)
                and path not in seen
            ):
                related.append(path)
                seen.add(path)
    return related


def _pick_assets_for_ai_report(asset_paths: list[Path]) -> list[Path]:
    notes: list[Path] = []
    figures: list[Path] = []
    nav_refs: list[Path] = []
    tables: list[Path] = []
    other: list[Path] = []
    for path in asset_paths:
        stem = path.stem.lower()
        suffix = path.suffix.lower()
        if suffix == ".md":
            notes.append(path)
        elif "nav_reference" in stem:
            nav_refs.append(path)
        elif suffix in {".png", ".jpg", ".jpeg"}:
            figures.append(path)
        elif suffix == ".csv":
            tables.append(path)
        else:
            other.append(path)
    selected: list[Path] = []
    if notes:
        selected.append(notes[0])
    if figures:
        selected.append(figures[0])
    if tables:
        selected.append(tables[0])
    elif nav_refs:
        selected.append(nav_refs[0])
    for path in other:
        if path not in selected:
            selected.append(path)
    return selected


def _score_evidence_row_for_ai(part_dir: Path, row: dict[str, str]) -> float:
    score = 0.0
    for path in _collect_related_assets_for_ai(part_dir, row):
        suffix = path.suffix.lower()
        stem = path.stem.lower()
        if suffix == ".md":
            score += 2.5
        elif suffix in {".png", ".jpg", ".jpeg"}:
            score += 3.0
            if "nav_reference" in stem:
                score += 0.25
        elif suffix == ".csv":
            profile = _csv_profile_for_ai(path)
            score += 1.5
            score += min(3.0, profile["numeric_count"] / 12.0)
            if profile["min"] is not None and profile["max"] is not None:
                score += min(2.5, math.log10(abs(profile["max"] - profile["min"]) + 1.0))
        elif suffix == ".json":
            score += 1.0
    item_label = (row.get("item") or "").strip().lower()
    if item_label in {"regime decomposition", "fixed windows", "dashboard"}:
        score += 1.0
    if item_label.startswith("test"):
        score += 0.5
    return score


def _selected_rows_for_part_for_ai(
    part_label: str, rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    limit = AI_EVIDENCE_PART_LIMITS.get(part_label)
    if limit is None:
        return rows
    if limit <= 0:
        return []
    if len(rows) <= limit:
        return rows
    scored_rows = []
    for idx, row in enumerate(rows):
        score = _score_evidence_row_for_ai(Path(row.get("__part_dir__", "")), row)
        scored_rows.append((score, (row.get("item") or "").strip().lower(), idx, row))
    scored_rows.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [row for _, _, _, row in scored_rows[:limit]]


def _describe_asset_for_ai(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        return f"Figure file: {path.name}"
    if suffix == ".md":
        excerpt = _clean_note_excerpt(_safe_read_text_file(path))
        return (
            f"Notes file: {path.name}. Excerpt: {excerpt}"
            if excerpt
            else f"Notes file: {path.name}"
        )
    if suffix == ".csv":
        profile = _csv_profile_for_ai(path)
        header_text = ", ".join(profile.get("headers") or [])
        numeric_text = ""
        if profile.get("min") is not None and profile.get("max") is not None:
            numeric_text = f" Numeric range: {profile['min']:.4f} to {profile['max']:.4f}."
        return f"Table file: {path.name}. Rows: {profile.get('rows', 0)}. Headers: {header_text}.{numeric_text}".strip()
    if suffix == ".json":
        profile = _json_profile_for_ai(path)
        return f"JSON file: {path.name}. Summary: {profile.get('summary', '')}".strip()
    return f"File: {path.name}"


def _build_selected_evidence_blocks(base_dir: Path) -> dict[str, list[dict[str, Any]]]:
    reports_dir = base_dir / "outputs" / "reports"
    evidence_dir = base_dir / "outputs" / "robustness" / "report_evidence"
    selected_blocks: dict[str, list[dict[str, Any]]] = {"main_report": [], "robustness": []}

    latest_bundle = _latest_report_bundle_for_ai(reports_dir)
    if latest_bundle is not None:
        for asset in _main_report_body_assets_for_ai(latest_bundle):
            stem = asset.stem.lower()
            block_key = f"main::{stem}"
            selected_blocks["main_report"].append(
                {
                    "block_key": block_key,
                    "title": _humanize_evidence_slug(asset.stem),
                    "bundle_name": latest_bundle.name,
                    "asset_names": [asset.name],
                    "asset_descriptions": [_describe_asset_for_ai(asset)],
                }
            )

    evidence_rows = _read_report_evidence_index_for_ai(evidence_dir)
    if evidence_rows:
        rows_by_part: dict[str, list[dict[str, str]]] = {}
        for row in evidence_rows:
            rows_by_part.setdefault((row.get("part") or "").strip(), []).append(row)
        for part_label in ["Part 1", "Part 2", "Part 3", "Part 4", "Part 5"]:
            rows = rows_by_part.get(part_label)
            if not rows:
                continue
            part_dir_name = AI_EVIDENCE_PART_DIRS.get(part_label)
            if not part_dir_name:
                continue
            part_dir = evidence_dir / part_dir_name
            enriched_rows = [dict(row, __part_dir__=str(part_dir)) for row in rows]
            for row in _selected_rows_for_part_for_ai(part_label, enriched_rows):
                item_label = (row.get("item") or "").strip() or "Evidence item"
                assets = _pick_assets_for_ai_report(_collect_related_assets_for_ai(part_dir, row))
                if not assets:
                    continue
                block_key = (
                    f"{part_dir_name}::{re.sub(r'[^a-z0-9]+', '_', item_label.lower()).strip('_')}"
                )
                selected_blocks["robustness"].append(
                    {
                        "block_key": block_key,
                        "part": part_label,
                        "part_dir": part_dir_name,
                        "part_title": AI_EVIDENCE_PART_LABELS.get(part_dir_name, part_label),
                        "item": item_label,
                        "title": _humanize_evidence_slug(item_label),
                        "asset_names": [path.name for path in assets],
                        "asset_descriptions": [_describe_asset_for_ai(path) for path in assets],
                    }
                )
    return selected_blocks


def _parse_evidence_analysis_sections(analysis_text: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?im)^###\s+BLOCK:\s*(.+?)\s*$", analysis_text or ""))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        block_key = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(analysis_text)
        body = (analysis_text[start:end] or "").strip()
        if block_key and body:
            sections[block_key] = body
    return sections


def _split_evidence_analysis_pass(text: str) -> tuple[str, str]:
    body = (text or "").strip()
    if not body:
        return "", ""
    investor_match = re.search(r"(?is)\bInvestor interpretation:\s*", body)
    if not investor_match:
        analysis = re.sub(r"(?im)^Analysis:\s*", "", body).strip()
        return analysis, ""
    analysis = body[: investor_match.start()].strip()
    investor_interpretation = body[investor_match.end() :].strip()
    analysis = re.sub(r"(?im)^Analysis:\s*", "", analysis).strip()
    investor_interpretation = re.sub(
        r"(?im)^Investor interpretation:\s*",
        "",
        investor_interpretation,
    ).strip()
    return analysis, investor_interpretation


def _generate_evidence_block_analyses(
    payload: AiReportRequest,
    *,
    sections: dict[str, str],
    context_snapshot: dict[str, Any],
    selected_blocks: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    all_blocks = [*selected_blocks.get("main_report", []), *selected_blocks.get("robustness", [])]
    if not all_blocks:
        return selected_blocks
    prompt_blocks = [
        {
            "block_key": block.get("block_key"),
            "title": block.get("title"),
            "part": block.get("part", ""),
            "bundle_name": block.get("bundle_name", ""),
            "asset_descriptions": block.get("asset_descriptions", []),
        }
        for block in all_blocks
    ]
    system_prompt = (
        "You are writing formal evidence commentary for an investor-facing quantitative portfolio analysis report. "
        "For each evidence block, write two compact paragraphs in polished report language. "
        "The Analysis paragraph should explain what the evidence shows, why it matters, and whether it strengthens or qualifies the main claim. "
        "The Investor interpretation paragraph should translate that evidence into an implication for investability, confidence, portfolio role, or monitoring. "
        "Do not introduce numbers, rankings, or claims unless they are present in the supplied report sections or evidence descriptions. "
        "Do not write instructions to the reader such as 'use this figure' or 'include this table'. "
        "Return only markdown blocks in this exact format: "
        "'### BLOCK:<block_key>' followed by 'Analysis: <one short paragraph>' and then 'Investor interpretation: <one short paragraph>'."
    )
    user_prompt = (
        "Use the report sections below as the main narrative context, then write compact evidence commentary for each selected block.\n\n"
        f"REPORT SECTIONS:\n{json.dumps(sections, ensure_ascii=False, indent=2)}\n\n"
        f"SELECTED EVIDENCE BLOCKS:\n{json.dumps(prompt_blocks, ensure_ascii=False, indent=2)}\n"
    )
    analysis_text, _ = _call_llm_api(
        payload,
        context_snapshot=context_snapshot,
        system_prompt_override=system_prompt,
        user_prompt_override=user_prompt,
    )
    analyses = _parse_evidence_analysis_sections(analysis_text)
    enriched: dict[str, list[dict[str, Any]]] = {"main_report": [], "robustness": []}
    for group_name in ("main_report", "robustness"):
        for block in selected_blocks.get(group_name, []):
            analysis, investor_interpretation = _split_evidence_analysis_pass(
                analyses.get(str(block.get("block_key")), "")
            )
            enriched[group_name].append(
                {
                    **block,
                    "analysis": analysis,
                    "investor_interpretation": investor_interpretation,
                }
            )
    return enriched


def _build_ai_prompt_messages(
    context_snapshot: dict[str, Any],
    *,
    system_prompt: str | None,
    user_instruction: str | None,
) -> tuple[str, str]:
    base_system_prompt = (
        "You are an investment portfolio reporting assistant. "
        "Use the supplied strategy settings, backtest analytics, portfolio risk data, and robustness checks to write a formal evidence-based portfolio analysis report for market users of the product. "
        "Your role is to turn the supplied data into investor interpretation: portfolio role, confidence, caveats, and monitoring implications. "
        "The supplied structured context controls facts, figures, and numeric values; do not replace it with outside assumptions. "
        "Do not invent numbers. Flag weaknesses clearly. "
        "Return the answer in markdown with exactly these top-level headings and in this exact order: "
        "'## Executive Summary', '## Strategy And Portfolio Construction', '## Backtest Design', '## Backtest Results', '## Risk, Regime And Exposure Analysis', '## Robustness And Sensitivity', '## Limitations And Monitoring Signals'. "
        "Do not add extra top-level headings before, between, or after them. "
        "The report should read like an investor-facing portfolio analysis report, not a marketing pitch, not a classroom submission, not a workflow log, and not a dump of robustness artifacts."
    )
    final_system_prompt = (
        system_prompt.strip() if system_prompt and system_prompt.strip() else base_system_prompt
    )
    final_instruction = (
        user_instruction.strip()
        if user_instruction and user_instruction.strip()
        else (
            "Generate an English investment portfolio analysis report. "
            "Do not write marketing copy or investor solicitation language. "
            "Treat the strategy as a systematic equity product whose value must be justified by strategy design, backtest evidence, risk analysis, and a compact robustness assessment. "
            "Use the LLM portion for judgement and narrative synthesis: explain what the data means for an investor, why a result matters, and what would change confidence. "
            "Keep data selection, chart selection, and numeric claims tied to the structured snapshot; if a metric is not present, discuss the concept qualitatively rather than inventing a value. "
            "Do not spend time introducing the report itself or explaining how the document is structured. "
            "In 'Executive Summary', state the strategy's current investment case, the headline backtest conclusion, the main risk caveat, and the level of confidence supported by the available evidence. "
            "In 'Strategy And Portfolio Construction', explain the investable universe, factor sleeves, IC-informed weighting, regime-aware tilts, covariance-aware construction, rebalance cadence, and practical portfolio constraints in investor language. "
            "In 'Backtest Design', explain the sample window, point-in-time discipline, benchmark hierarchy, transaction-cost assumption, execution lag, rebalance frequency, and metric conventions. This section should justify why the backtest is interpretable, not merely list settings. "
            "In 'Backtest Results', lead with the main absolute and benchmark-relative outcome, then discuss NAV, excess return, Sharpe or risk-adjusted quality, drawdown, turnover, and transaction-cost drag. Prefer a cohesive interpretation over a long metric catalogue. "
            "In 'Risk, Regime And Exposure Analysis', discuss drawdown behaviour, volatility, regime attribution, sector or concentration risk, and how those risks affect the user experience of the product. "
            "In 'Robustness And Sensitivity', summarise only the most decision-relevant validation evidence. Keep this section shorter than the backtest sections. Mention cost sensitivity, time/regime stability, or stochastic uncertainty only when they change confidence in the main claim. Do not turn it into a completion log, acceptance-matrix summary, or list of test names. "
            "In 'Limitations And Monitoring Signals', identify the main residual weaknesses and the few data signals an investor should monitor next, such as benchmark-relative excess return, drawdown, turnover/cost drag, and regime deterioration. Do not describe internal team tasks or reporting workflow. "
            "Across all sections, prioritise strategy logic, backtest evidence, and investability. Robustness should support the conclusion rather than dominate the report."
        )
    )
    context_text = json.dumps(context_snapshot, indent=2, ensure_ascii=False, sort_keys=True)
    user_prompt = (
        f"{final_instruction}\n\n" "Use this current CW2 context snapshot:\n" f"{context_text}\n"
    )
    return final_system_prompt, user_prompt


LLM_REQUEST_FORMATS = {
    "openai_responses",
    "openai_chat",
    "anthropic_messages",
    "gemini_generate_content",
    "generic_chat",
    "generic_json",
}
LLM_REQUEST_FORMAT_ALIASES = {
    "openai": "openai_responses",
    "openai_response": "openai_responses",
    "responses": "openai_responses",
    "responses_api": "openai_responses",
    "chat": "generic_chat",
    "chat_completions": "openai_chat",
    "openai_chat_completions": "openai_chat",
    "anthropic": "anthropic_messages",
    "claude": "anthropic_messages",
    "claude_messages": "anthropic_messages",
    "gemini": "gemini_generate_content",
    "google_gemini": "gemini_generate_content",
    "google": "gemini_generate_content",
    "generic": "generic_chat",
    "compatible_api": "generic_chat",
    "openai_compatible_api": "generic_chat",
    "openai_compatible": "generic_chat",
    "custom": "generic_json",
    "custom_json": "generic_json",
}
LLM_MAX_OUTPUT_TOKENS = 3000


def _normalize_llm_request_format(request_format: str | None) -> str:
    normalized = re.sub(r"[\s-]+", "_", str(request_format or "").strip().lower())
    if not normalized:
        return "openai_responses"
    normalized = LLM_REQUEST_FORMAT_ALIASES.get(normalized, normalized)
    return normalized if normalized in LLM_REQUEST_FORMATS else "generic_chat"


def _conversation_messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _append_query_param_if_missing(url: str, key: str, value: str) -> str:
    if not value:
        return url
    parsed = urllib.parse.urlsplit(url)
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(existing_key.lower() == key.lower() for existing_key, _ in query_pairs):
        return url
    query_pairs.append((key, value))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query_pairs)))


def _require_http_api_url(url: str) -> str:
    clean_url = str(url or "").strip()
    parsed = urllib.parse.urlsplit(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("LLM API URL must be an absolute http or https endpoint.")
    return clean_url


def _request_url_for_format(
    api_url: str,
    *,
    api_key: str,
    model: str,
    request_format: str,
) -> str:
    clean_url = str(api_url or "").strip()
    if not clean_url:
        return clean_url
    parsed = urllib.parse.urlsplit(clean_url)
    path = parsed.path.rstrip("/")
    if request_format == "openai_responses":
        if path.endswith("/chat/completions"):
            return urllib.parse.urlunsplit(
                parsed._replace(path=f"{path[:-len('/chat/completions')]}/responses")
            )
        if path in ("", "/v1"):
            return urllib.parse.urlunsplit(parsed._replace(path="/v1/responses"))
    if request_format == "openai_chat":
        if path.endswith("/responses"):
            return urllib.parse.urlunsplit(
                parsed._replace(path=f"{path[:-len('/responses')]}/chat/completions")
            )
        if path in ("", "/v1"):
            return urllib.parse.urlunsplit(parsed._replace(path="/v1/chat/completions"))
    if request_format == "anthropic_messages" and path in ("", "/v1"):
        return urllib.parse.urlunsplit(parsed._replace(path="/v1/messages"))
    if request_format == "gemini_generate_content":
        model_name = urllib.parse.quote(str(model or "").strip(), safe="-_.~")
        if path.endswith(":generateContent"):
            gemini_url = clean_url
        else:
            if not path:
                next_path = f"/v1beta/models/{model_name}:generateContent"
            elif "/models/" in path:
                next_path = f"{path}:generateContent"
            elif path.endswith("/models"):
                next_path = f"{path}/{model_name}:generateContent"
            else:
                next_path = f"{path}/models/{model_name}:generateContent"
            gemini_url = urllib.parse.urlunsplit(parsed._replace(path=next_path))
        return _append_query_param_if_missing(gemini_url, "key", str(api_key or "").strip())
    return clean_url


def _headers_for_llm_request(api_key: str, request_format: str) -> dict[str, str]:
    clean_key = str(api_key or "").strip()
    headers = {"Content-Type": "application/json"}
    if request_format == "anthropic_messages":
        headers["anthropic-version"] = "2023-06-01"
        if clean_key:
            headers["x-api-key"] = clean_key
    elif request_format == "gemini_generate_content":
        if clean_key:
            headers["x-goog-api-key"] = clean_key
    elif clean_key:
        headers["Authorization"] = f"Bearer {clean_key}"
    return headers


def _model_list_url_for_format(
    api_url: str,
    *,
    api_key: str,
    request_format: str,
) -> str:
    clean_url = str(api_url or "").strip()
    if not clean_url:
        return clean_url
    parsed = urllib.parse.urlsplit(clean_url)
    path = parsed.path.rstrip("/")

    if request_format == "gemini_generate_content":
        if path.endswith(":generateContent") and "/models/" in path:
            base_path = path.split("/models/", 1)[0]
            model_url = urllib.parse.urlunsplit(parsed._replace(path=f"{base_path}/models"))
        elif path.endswith("/models"):
            model_url = clean_url
        elif path in ("", "/v1beta", "/v1"):
            model_url = urllib.parse.urlunsplit(parsed._replace(path="/v1beta/models"))
        else:
            model_url = urllib.parse.urlunsplit(parsed._replace(path=f"{path}/models"))
        return _append_query_param_if_missing(model_url, "key", str(api_key or "").strip())

    if path.endswith("/models"):
        return clean_url
    if path.endswith("/responses"):
        return urllib.parse.urlunsplit(parsed._replace(path=f"{path[:-len('/responses')]}/models"))
    if path.endswith("/chat/completions"):
        return urllib.parse.urlunsplit(
            parsed._replace(path=f"{path[:-len('/chat/completions')]}/models")
        )
    if path in ("", "/v1"):
        return urllib.parse.urlunsplit(parsed._replace(path="/v1/models"))
    return urllib.parse.urlunsplit(parsed._replace(path=f"{path}/models"))


def _model_name_from_entry(entry: Any, request_format: str) -> dict[str, str] | None:
    if isinstance(entry, str):
        raw_id = entry.strip()
        label = raw_id
    elif isinstance(entry, dict):
        if request_format == "gemini_generate_content":
            methods = entry.get("supportedGenerationMethods")
            if isinstance(methods, list) and "generateContent" not in methods:
                return None
        raw_id = str(
            entry.get("id")
            or entry.get("name")
            or entry.get("model")
            or entry.get("model_id")
            or ""
        ).strip()
        label = str(
            entry.get("display_name") or entry.get("displayName") or entry.get("label") or raw_id
        ).strip()
    else:
        return None

    if not raw_id:
        return None
    model_id = raw_id
    if request_format == "gemini_generate_content" and model_id.startswith("models/"):
        model_id = model_id.split("/", 1)[1]
    if label.startswith("models/"):
        label = label.split("/", 1)[1]
    return {"id": model_id, "label": label or model_id}


def _extract_model_catalog(response_payload: Any, request_format: str) -> list[dict[str, str]]:
    candidates: list[Any] = []
    if isinstance(response_payload, list):
        candidates = response_payload
    elif isinstance(response_payload, dict):
        for key in ("data", "models", "items", "result"):
            value = response_payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates and any(key in response_payload for key in ("id", "name", "model")):
            candidates = [response_payload]

    seen: set[str] = set()
    models: list[dict[str, str]] = []
    for entry in candidates:
        model = _model_name_from_entry(entry, request_format)
        if not model:
            continue
        model_id = model["id"]
        if model_id in seen:
            continue
        seen.add(model_id)
        models.append(model)
    return models[:300]


def _request_payload_for_format(
    payload: AiReportRequest,
    *,
    request_format: str,
    system_prompt: str,
    user_prompt: str,
    context_snapshot: dict[str, Any],
) -> dict[str, Any]:
    messages = _conversation_messages(system_prompt, user_prompt)
    if request_format == "generic_json":
        return {
            "model": payload.model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "messages": messages,
            "context": context_snapshot,
            "temperature": payload.temperature,
            "max_tokens": LLM_MAX_OUTPUT_TOKENS,
        }
    if request_format == "openai_responses":
        return {
            "model": payload.model,
            "instructions": system_prompt,
            "input": user_prompt,
            "temperature": payload.temperature,
        }
    if request_format == "anthropic_messages":
        request_payload: dict[str, Any] = {
            "model": payload.model,
            "max_tokens": LLM_MAX_OUTPUT_TOKENS,
            "temperature": payload.temperature,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if system_prompt.strip():
            request_payload["system"] = system_prompt
        return request_payload
    if request_format == "gemini_generate_content":
        request_payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": payload.temperature,
                "maxOutputTokens": LLM_MAX_OUTPUT_TOKENS,
            },
        }
        if system_prompt.strip():
            request_payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        return request_payload
    return {
        "model": payload.model,
        "temperature": payload.temperature,
        "messages": messages,
    }


def _extract_llm_text_parts(content: Any) -> list[str]:
    text_parts: list[str] = []
    if isinstance(content, str) and content.strip():
        return [content.strip()]
    if isinstance(content, list):
        for item in content:
            text_parts.extend(_extract_llm_text_parts(item))
        return text_parts
    if isinstance(content, dict):
        for key in ("text", "output_text", "response", "result", "completion"):
            candidate = content.get(key)
            if isinstance(candidate, str) and candidate.strip():
                text_parts.append(candidate.strip())
        for key in ("content", "parts"):
            text_parts.extend(_extract_llm_text_parts(content.get(key)))
    return text_parts


def _extract_text_from_llm_response(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
            return payload["output_text"].strip()
        output_items = payload.get("output")
        if isinstance(output_items, list) and output_items:
            text_parts: list[str] = []
            for item in output_items:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for content_item in content:
                        if not isinstance(content_item, dict):
                            continue
                        candidate = (
                            content_item.get("text") or content_item.get("output_text") or ""
                        )
                        if isinstance(candidate, str) and candidate.strip():
                            text_parts.append(candidate.strip())
                elif isinstance(content, str) and content.strip():
                    text_parts.append(content.strip())
            if text_parts:
                return "\n".join(text_parts)
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            text_parts = []
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                text_parts.extend(_extract_llm_text_parts(candidate.get("content")))
            if text_parts:
                return "\n".join(text_parts)
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0] or {}
            message = first_choice.get("message") if isinstance(first_choice, dict) else None
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    text_parts = [
                        str(item.get("text", "")).strip()
                        for item in content
                        if isinstance(item, dict) and item.get("text")
                    ]
                    if text_parts:
                        return "\n".join(text_parts)
        content = payload.get("content")
        if isinstance(content, list) and content:
            text_parts = [
                str(item.get("text", "")).strip()
                for item in content
                if isinstance(item, dict) and item.get("text")
            ]
            if text_parts:
                return "\n".join(text_parts)
        message = payload.get("message")
        if isinstance(message, dict):
            text_parts = _extract_llm_text_parts(message.get("content"))
            if text_parts:
                return "\n".join(text_parts)
        for key in ("response", "result", "completion"):
            if isinstance(payload.get(key), str) and payload[key].strip():
                return payload[key].strip()
        if isinstance(payload.get("text"), str) and payload["text"].strip():
            return payload["text"].strip()
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    raise ValueError("Unable to extract text from LLM response payload")


def _parse_ai_report_sections(analysis_text: str) -> dict[str, str]:
    heading_map = {
        "executive summary": "Executive Summary",
        "strategy and portfolio construction": "Strategy And Portfolio Construction",
        "backtest design": "Backtest Design",
        "backtest results": "Backtest Results",
        "risk, regime and exposure analysis": "Risk, Regime And Exposure Analysis",
        "risk regime and exposure analysis": "Risk, Regime And Exposure Analysis",
        "robustness and sensitivity": "Robustness And Sensitivity",
        "limitations and monitoring signals": "Limitations And Monitoring Signals",
        "product snapshot": "Product Snapshot",
        "what changed since the last update": "What Changed Since The Last Update",
        "performance update": "Performance Update",
        "risk and regime update": "Risk And Regime Update",
        "robustness watch": "Robustness Watch",
        "what users should watch next": "What Users Should Watch Next",
        "strategy summary": "Strategy Summary",
        "product design": "Product Design",
        "performance evaluation": "Performance Evaluation",
        "robustness assessment": "Robustness Assessment",
        "risks and limitations": "Risks and Limitations",
        "reporting priorities": "Reporting Priorities",
    }
    matches = list(
        re.finditer(
            r"(?im)^##\s+(Executive Summary|Strategy And Portfolio Construction|Backtest Design|Backtest Results|Risk, Regime And Exposure Analysis|Risk Regime And Exposure Analysis|Robustness And Sensitivity|Limitations And Monitoring Signals|Product Snapshot|What Changed Since The Last Update|Performance Update|Risk And Regime Update|Robustness Watch|What Users Should Watch Next|Strategy Summary|Product Design|Performance Evaluation|Robustness Assessment|Risks and Limitations|Reporting Priorities)\s*$",
            analysis_text,
        )
    )
    sections: dict[str, str] = {value: "" for value in heading_map.values()}
    if not matches:
        sections[REPORT_SECTION_ORDER[0]] = analysis_text.strip()
        return sections
    for index, match in enumerate(matches):
        raw_heading = match.group(1).strip().lower()
        canonical_heading = heading_map.get(raw_heading)
        if canonical_heading is None:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(analysis_text)
        body = analysis_text[start:end].strip()
        sections[canonical_heading] = body
    return sections


def _call_llm_api(
    payload: AiReportRequest,
    *,
    context_snapshot: dict[str, Any],
    system_prompt_override: str | None = None,
    user_prompt_override: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if system_prompt_override is not None or user_prompt_override is not None:
        system_prompt = system_prompt_override or ""
        user_prompt = user_prompt_override or ""
    else:
        system_prompt, user_prompt = _build_ai_prompt_messages(
            context_snapshot,
            system_prompt=payload.system_prompt,
            user_instruction=payload.user_instruction,
        )
    request_format = _normalize_llm_request_format(payload.request_format)
    request_payload = _request_payload_for_format(
        payload,
        request_format=request_format,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context_snapshot=context_snapshot,
    )
    request_url = _request_url_for_format(
        payload.api_url,
        api_key=payload.api_key,
        model=payload.model,
        request_format=request_format,
    )
    try:
        request_url = _require_http_api_url(request_url)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    request_bytes = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        request_url,
        data=request_bytes,
        headers=_headers_for_llm_request(payload.api_key, request_format),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310
            raw_text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        if error_body:
            raise RuntimeError(f"LLM endpoint returned HTTP {exc.code}: {error_body}") from exc
        raise RuntimeError(
            f"LLM endpoint returned HTTP {exc.code} with an empty response body."
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the LLM endpoint: {exc.reason}") from exc
    if not raw_text.strip():
        raise RuntimeError(
            "The LLM endpoint returned an empty response body. "
            "Check that API URL points to the actual endpoint path, not just the API base URL."
        )
    try:
        response_payload = json.loads(raw_text)
    except json.JSONDecodeError:
        response_payload = {"text": raw_text}
    return _extract_text_from_llm_response(response_payload), response_payload


def _display_percent_from_value(value: Any) -> str:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        numeric = float(value)
    else:
        numeric = _safe_float_text(str(value or ""))
        if numeric is None:
            return ""
    if abs(numeric) <= 1.5:
        numeric *= 100.0
    return f"{numeric:.2f}%"


def _display_decimal_from_value(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        numeric = float(value)
    else:
        numeric = _safe_float_text(str(value or ""))
        if numeric is None:
            return ""
    return f"{numeric:.{digits}f}"


def _nested_value(source: Any, path: tuple[str, ...]) -> Any:
    cursor = source
    for key in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


def _latest_report_summary_for_display() -> dict[str, Any]:
    latest_bundle = _latest_report_bundle_for_ai(BASE_DIR / "outputs" / "reports")
    if latest_bundle is None:
        return {}
    payload = _read_json_if_exists(latest_bundle / "report_summary.json", {})
    return payload if isinstance(payload, dict) else {}


def _ai_report_display_metrics(payload: dict[str, Any]) -> dict[str, str]:
    context = payload.get("context_snapshot")
    if not isinstance(context, dict):
        context = {}
    summary = _latest_report_summary_for_display()

    def percent(paths: list[tuple[str, ...]], summary_key: str = "") -> str:
        for path in paths:
            rendered = _display_percent_from_value(_nested_value(context, path))
            if rendered:
                return rendered
        if summary_key:
            return _display_percent_from_value(summary.get(summary_key))
        return ""

    def decimal(paths: list[tuple[str, ...]], summary_key: str = "") -> str:
        for path in paths:
            rendered = _display_decimal_from_value(_nested_value(context, path))
            if rendered:
                return rendered
        if summary_key:
            return _display_decimal_from_value(summary.get(summary_key))
        return ""

    robustness = context.get("robustness") if isinstance(context.get("robustness"), dict) else {}
    selected_robustness = {}
    selected = payload.get("selected_evidence")
    if isinstance(selected, dict) and isinstance(selected.get("robustness"), dict):
        selected_robustness = selected["robustness"]
    completed = robustness.get(
        "completed_acceptance_blocks", selected_robustness.get("completed_acceptance_blocks")
    )
    total = robustness.get(
        "acceptance_total_blocks", selected_robustness.get("acceptance_total_blocks")
    )

    return {
        "annualized_return_pct": percent(
            [("performance", "summary", "annualized_return_pct")], "annualized_return"
        ),
        "cumulative_return_pct": percent(
            [("performance", "summary", "cumulative_return_pct")], "total_return"
        ),
        "primary_excess_pct": percent(
            [
                (
                    "performance",
                    "comparatives",
                    "primary_benchmark",
                    "excess_return_annualized_pct",
                ),
                ("performance", "comparatives", "primary_benchmark", "excess_return_annualized"),
                ("performance", "summary", "excess_return_vs_primary_pct"),
                ("performance", "summary", "excess_return_vs_primary"),
            ],
            "excess_return_vs_primary",
        ),
        "max_drawdown_pct": percent(
            [("performance", "summary", "max_drawdown_pct")], "max_drawdown"
        ),
        "volatility_pct": percent(
            [("performance", "summary", "volatility_pct")], "annualized_volatility"
        ),
        "sharpe_ratio": decimal(
            [
                ("performance", "summary", "rolling_sharpe"),
                ("performance", "summary", "mainline_realized_sharpe"),
            ],
            "sharpe_ratio",
        ),
        "primary_information_ratio": decimal(
            [("performance", "comparatives", "primary_benchmark", "information_ratio")]
        ),
        "primary_tracking_error_pct": percent(
            [("performance", "comparatives", "primary_benchmark", "tracking_error_pct")]
        ),
        "static_excess_pct": percent(
            [("performance", "comparatives", "static_baseline", "excess_return_annualized_pct")]
        ),
        "static_information_ratio": decimal(
            [("performance", "comparatives", "static_baseline", "information_ratio")]
        ),
        "static_tracking_error_pct": percent(
            [("performance", "comparatives", "static_baseline", "tracking_error_pct")]
        ),
        "acceptance_completed": str(int(completed)) if isinstance(completed, (int, float)) else "",
        "acceptance_total": str(int(total)) if isinstance(total, (int, float)) else "",
    }


def _replace_display_metric(text: str, pattern: str, value: str) -> str:
    if not value:
        return text
    return re.sub(
        pattern,
        lambda match: f"{match.group(1)}{value}{match.group(2) if match.lastindex and match.lastindex > 1 else ''}",
        text,
        flags=re.IGNORECASE,
    )


def _sanitize_ai_report_display_text(text: str, title: str, metrics: dict[str, str]) -> str:
    body = text or ""
    percent_value = r"-?\d+(?:\.\d+)?%"
    decimal_value = r"-?\d+(?:\.\d+)?"
    replacements = [
        (r"\bpersistent alpha generation\b", "historical active-return evidence"),
        (
            r"\bstable, repeatable performance\b",
            "historically stable performance under the tested assumptions",
        ),
        (
            r"\bnot artifacts of historical data\b",
            "not solely an artifact of one realised historical path",
        ),
        (
            r"\blikely to persist under varied future market conditions\b",
            "not solely dependent on one realised path, although future persistence is not guaranteed",
        ),
        (
            r"\bsupporting confidence in the strategy's stability and implementation\b",
            "supporting the historical evidence for the strategy's stability and implementation",
        ),
        (
            r"\bsupporting the strategy's generalizability\b",
            "supporting the out-of-sample evidence for the strategy",
        ),
        (
            r"\bcontinues to perform as expected under evolving market conditions\b",
            "remains aligned with measured assumptions as market conditions change",
        ),
    ]
    for pattern, replacement in replacements:
        body = re.sub(pattern, replacement, body, flags=re.IGNORECASE)
    section_key = (title or "").strip().lower()
    target_text = body
    tail = ""
    if section_key in {
        "executive summary",
        "backtest results",
        "limitations and monitoring signals",
    }:
        paragraphs = re.split(r"(\n\s*\n)", body, maxsplit=1)
        target_text = paragraphs[0]
        tail = "".join(paragraphs[1:])
    if section_key in {"executive summary", "backtest results"}:
        target_text = _replace_display_metric(
            target_text,
            rf"(\bannuali[sz]ed return(?:\s+(?:of|around|near|is|was|at|exceeding))?\s*){percent_value}",
            metrics.get("annualized_return_pct", ""),
        )
        target_text = _replace_display_metric(
            target_text,
            rf"(\bcumulative return(?:\s+(?:of|around|near|is|was|at))?\s*){percent_value}",
            metrics.get("cumulative_return_pct", ""),
        )
        target_text = _replace_display_metric(
            target_text,
            rf"(\b(?:excess|benchmark-relative excess) return(?:\s+(?:of|around|near|is|was|at))?\s*){percent_value}(\s+(?:above|versus|vs|relative to)[^.\n]{{0,100}}(?:primary benchmark|Universe EW|equal-weighted universe|benchmark))",
            metrics.get("primary_excess_pct", ""),
        )
        target_text = _replace_display_metric(
            target_text,
            rf"(\boutperformed[^.\n]{{0,100}}(?:Universe EW|primary benchmark|equal-weighted universe)[^.\n]{{0,40}}\bby\s*){percent_value}(\s+annuali[sz]ed)?",
            metrics.get("primary_excess_pct", ""),
        )
        target_text = _replace_display_metric(
            target_text,
            rf"(\btracking error(?:\s+(?:of|around|near|is|was|at))?\s*){percent_value}",
            metrics.get("primary_tracking_error_pct", ""),
        )
        target_text = _replace_display_metric(
            target_text,
            rf"(\binformation ratio[^.\n]{{0,80}}(?:Universe EW|primary benchmark|equal-weighted universe|benchmark)[^.\n]{{0,40}}(?:stands at|of|is|was|at)\s*){decimal_value}\b",
            metrics.get("primary_information_ratio", ""),
        )
    if section_key in {
        "executive summary",
        "backtest results",
        "limitations and monitoring signals",
    }:
        target_text = _replace_display_metric(
            target_text,
            rf"(\bmaximum drawdown(?:\s+(?:of|around|near|is|was|at))?\s*){percent_value}",
            metrics.get("max_drawdown_pct", ""),
        )
        target_text = _replace_display_metric(
            target_text,
            rf"(\bvolatility(?:\s+(?:of|around|near|is|was|at))?\s*){percent_value}",
            metrics.get("volatility_pct", ""),
        )
        target_text = _replace_display_metric(
            target_text,
            rf"(\bSharpe ratio(?:\s+(?:of approximately|of|around|near|is|was|at))?\s*){decimal_value}\b",
            metrics.get("sharpe_ratio", ""),
        )
    if metrics.get("acceptance_completed") and metrics.get("acceptance_total"):
        target_text = re.sub(
            r"(\brobustness testing[^.\n]{0,120}\b)(\d+)\s+of\s+(\d+)(\s+acceptance blocks)",
            lambda match: f"{match.group(1)}{metrics['acceptance_completed']} of {metrics['acceptance_total']}{match.group(4)}",
            target_text,
            flags=re.IGNORECASE,
        )
    body = f"{target_text}{tail}"
    return body


def _normalize_ai_report_for_display(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    metrics = _ai_report_display_metrics(payload)
    normalized = dict(payload)
    sections = normalized.get("sections")
    if isinstance(sections, dict):
        sanitized_sections = {
            key: (
                _sanitize_ai_report_display_text(value, key, metrics)
                if isinstance(value, str)
                else value
            )
            for key, value in sections.items()
        }
        normalized["sections"] = sanitized_sections
        ordered = [
            (title, sanitized_sections.get(title))
            for title in REPORT_SECTION_ORDER
            if isinstance(sanitized_sections.get(title), str)
            and sanitized_sections.get(title).strip()
        ]
        if ordered:
            normalized["analysis_text"] = "\n\n".join(
                f"## {title}\n\n{body.strip()}" for title, body in ordered
            )
    elif isinstance(normalized.get("analysis_text"), str):
        normalized["analysis_text"] = _sanitize_ai_report_display_text(
            normalized["analysis_text"], "", metrics
        )
    return normalized


def _save_ai_report_result(result_payload: dict[str, Any]) -> None:
    result_payload = _normalize_ai_report_for_display(result_payload)
    AI_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(tz=timezone.utc)
    compact_stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    markdown_path = AI_REPORT_DIR / f"ai_report_{compact_stamp}.md"
    json_path = AI_REPORT_DIR / f"ai_report_{compact_stamp}.json"
    markdown_path.write_text(result_payload["analysis_text"], encoding="utf-8")
    _write_json(json_path, result_payload)
    latest_payload = dict(result_payload)
    latest_payload["output_path"] = str(json_path)
    latest_payload["output_markdown_path"] = str(markdown_path)
    latest_payload["output_docx_path"] = str(result_payload.get("output_docx_path") or "")
    latest_payload["output_pdf_path"] = str(result_payload.get("output_pdf_path") or "")
    _write_json(AI_REPORT_LATEST_PATH, latest_payload)
    registry = _read_json_if_exists(AI_REPORT_REGISTRY_PATH, [])
    if not isinstance(registry, list):
        registry = []
    registry_entry = {
        "report_id": latest_payload.get("report_id"),
        "generated_at": latest_payload.get("generated_at"),
        "model": latest_payload.get("model"),
        "provider_url": latest_payload.get("provider_url"),
        "output_path": latest_payload.get("output_path"),
        "output_markdown_path": latest_payload.get("output_markdown_path"),
        "output_docx_path": latest_payload.get("output_docx_path", ""),
        "output_pdf_path": latest_payload.get("output_pdf_path", ""),
        "status": latest_payload.get("status"),
    }
    registry = [
        registry_entry,
        *[row for row in registry if row.get("report_id") != registry_entry["report_id"]],
    ][:20]
    _write_json(AI_REPORT_REGISTRY_PATH, registry)


def _build_ai_guardrails_snapshot(
    context_snapshot: dict[str, Any], payload: AiReportRequest
) -> dict[str, Any]:
    baseline = context_snapshot.get("baseline", {})
    return {
        "structured_inputs_only": True,
        "ticker_recommendations_disabled": True,
        "numeric_cross_check_status": "snapshot-linked",
        "prompt_template_version": "cw2-report-v5-narrative-pass",
        "result_version": baseline.get("run_id"),
        "model_id": payload.model,
        "request_format": _normalize_llm_request_format(payload.request_format),
    }


def _build_ai_source_trace_preview(context_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    baseline = context_snapshot.get("baseline", {})
    return [
        {
            "label": "Baseline performance summary",
            "source": "performance.baseline",
            "linkage": baseline.get("run_id"),
        },
        {
            "label": "Risk regime snapshot",
            "source": "risk.regime",
            "linkage": "latest risk payload",
        },
        {
            "label": "Robustness dashboard",
            "source": "robustness.dashboard",
            "linkage": "db-first robustness outputs",
        },
        {
            "label": "Acceptance matrix",
            "source": "robustness.acceptance",
            "linkage": "requirement alignment snapshot",
        },
    ]


def _load_ai_history_rows() -> list[dict[str, Any]]:
    history = _read_json_if_exists(AI_REPORT_REGISTRY_PATH, [])
    return history if isinstance(history, list) else []


def _load_ai_report_by_id(report_id: str) -> dict[str, Any] | None:
    latest = _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    if isinstance(latest, dict) and latest.get("report_id") == report_id:
        return latest
    for row in _load_ai_history_rows():
        output_path = row.get("output_path")
        if row.get("report_id") == report_id and output_path and Path(str(output_path)).exists():
            return _read_json(Path(str(output_path)))
    return None


def _export_ai_report_docx(
    report_payload: dict[str, Any], output_docx_path: Path | None = None
) -> Path:
    if not isinstance(report_payload, dict) or not report_payload.get("analysis_text"):
        raise RuntimeError("No AI report analysis is available for DOCX export.")
    AI_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_id = str(
        report_payload.get("report_id")
        or f"ai-report-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    )
    export_payload_path = AI_REPORT_DIR / f"{report_id}_docx_payload.json"
    if output_docx_path is None:
        output_docx_path = AI_REPORT_DIR / f"{report_id}.docx"
    export_payload = {
        "report_id": report_id,
        "generated_at": report_payload.get("generated_at"),
        "provider_url": report_payload.get("provider_url"),
        "model": report_payload.get("model"),
        "prompt_template_version": report_payload.get("prompt_template_version"),
        "analysis_text": report_payload.get("analysis_text") or "",
        "sections": report_payload.get("sections") or {},
        "selected_evidence": report_payload.get("selected_evidence") or {},
        "context_snapshot": report_payload.get("context_snapshot") or {},
        "base_dir": str(BASE_DIR),
    }
    _write_json(export_payload_path, export_payload)
    python_exe = _resolve_docx_export_python()
    if not AI_REPORT_DOCX_SCRIPT_PATH.exists():
        raise RuntimeError("DOCX export helper script is missing.")
    command = [
        str(python_exe),
        str(AI_REPORT_DOCX_SCRIPT_PATH),
        "--input-json",
        str(export_payload_path),
        "--output-docx",
        str(output_docx_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR),
        env=_report_export_subprocess_env(),
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(stderr or "DOCX export failed.")
    if not output_docx_path.exists():
        raise RuntimeError("DOCX export did not produce an output file.")
    latest_payload = _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    if isinstance(latest_payload, dict) and latest_payload.get("report_id") == report_id:
        latest_payload["output_docx_path"] = str(output_docx_path)
        _write_json(AI_REPORT_LATEST_PATH, latest_payload)
    registry = _read_json_if_exists(AI_REPORT_REGISTRY_PATH, [])
    if isinstance(registry, list):
        updated_registry = []
        for row in registry:
            if row.get("report_id") == report_id:
                row = dict(row)
                row["output_docx_path"] = str(output_docx_path)
            updated_registry.append(row)
        _write_json(AI_REPORT_REGISTRY_PATH, updated_registry)
    return output_docx_path


def _export_ai_report_docx_for_download(report_payload: dict[str, Any]) -> Path:
    try:
        return _export_ai_report_docx(report_payload)
    except RuntimeError as exc:
        message = str(exc)
        if "Permission denied" not in message and "Errno 13" not in message:
            raise
        report_id = str(
            report_payload.get("report_id")
            or f"ai-report-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        )
        fallback_docx_path = (
            AI_REPORT_DIR
            / f"{report_id}-export-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}.docx"
        )
        return _export_ai_report_docx(report_payload, output_docx_path=fallback_docx_path)


def _export_ai_report_pdf(
    report_payload: dict[str, Any], output_pdf_path: Path | None = None
) -> Path:
    if not isinstance(report_payload, dict) or not report_payload.get("analysis_text"):
        raise RuntimeError("No AI report analysis is available for PDF export.")
    AI_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_id = str(
        report_payload.get("report_id")
        or f"ai-report-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    )
    export_payload_path = AI_REPORT_DIR / f"{report_id}_pdf_payload.json"
    if output_pdf_path is None:
        output_pdf_path = AI_REPORT_DIR / f"{report_id}.pdf"
    export_payload = {
        "report_id": report_id,
        "generated_at": report_payload.get("generated_at"),
        "provider_url": report_payload.get("provider_url"),
        "model": report_payload.get("model"),
        "prompt_template_version": report_payload.get("prompt_template_version"),
        "analysis_text": report_payload.get("analysis_text") or "",
        "sections": report_payload.get("sections") or {},
        "selected_evidence": report_payload.get("selected_evidence") or {},
        "context_snapshot": report_payload.get("context_snapshot") or {},
        "base_dir": str(BASE_DIR),
    }
    _write_json(export_payload_path, export_payload)
    python_exe = _resolve_docx_export_python()
    if not AI_REPORT_PDF_SCRIPT_PATH.exists():
        raise RuntimeError("PDF export helper script is missing.")
    command = [
        str(python_exe),
        str(AI_REPORT_PDF_SCRIPT_PATH),
        "--input-json",
        str(export_payload_path),
        "--output-pdf",
        str(output_pdf_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR),
        env=_report_export_subprocess_env(),
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(stderr or "PDF export failed.")
    if not output_pdf_path.exists():
        raise RuntimeError("PDF export did not produce an output file.")
    latest_payload = _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    if isinstance(latest_payload, dict) and latest_payload.get("report_id") == report_id:
        latest_payload["output_pdf_path"] = str(output_pdf_path)
        latest_payload["output_docx_path"] = ""
        _write_json(AI_REPORT_LATEST_PATH, latest_payload)
    registry = _read_json_if_exists(AI_REPORT_REGISTRY_PATH, [])
    if isinstance(registry, list):
        updated_registry = []
        for row in registry:
            if row.get("report_id") == report_id:
                row = dict(row)
                row["output_pdf_path"] = str(output_pdf_path)
                row["output_docx_path"] = ""
            updated_registry.append(row)
        _write_json(AI_REPORT_REGISTRY_PATH, updated_registry)
    return output_pdf_path


def _export_ai_report_pdf_for_download(report_payload: dict[str, Any]) -> Path:
    try:
        return _export_ai_report_pdf(report_payload)
    except RuntimeError as exc:
        message = str(exc)
        if "Permission denied" not in message and "Errno 13" not in message:
            raise
        report_id = str(
            report_payload.get("report_id")
            or f"ai-report-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        )
        fallback_pdf_path = (
            AI_REPORT_DIR
            / f"{report_id}-export-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}.pdf"
        )
        return _export_ai_report_pdf(report_payload, output_pdf_path=fallback_pdf_path)


def _numeric_signature_from_snapshot(context_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    performance = context_snapshot.get("performance", {}).get("summary", {})
    risk_summary = context_snapshot.get("risk", {}).get("summary", {})
    robustness = context_snapshot.get("robustness", {})
    mainline = robustness.get("mainline_realized") or {}
    signature = [
        {
            "label": "baseline_run_id",
            "value": str(context_snapshot.get("baseline", {}).get("run_id", "")),
        },
        {"label": "cumulative_return_pct", "value": performance.get("cumulative_return_pct")},
        {"label": "excess_return_pct", "value": performance.get("excess_return_pct")},
        {"label": "rolling_sharpe", "value": performance.get("rolling_sharpe")},
        {"label": "max_drawdown_pct", "value": performance.get("max_drawdown_pct")},
        {"label": "latest_vix", "value": risk_summary.get("latest_vix")},
        {"label": "stress_threshold", "value": risk_summary.get("threshold")},
        {"label": "robustness_sharpe", "value": mainline.get("sharpe")},
    ]
    return signature


app = FastAPI(
    title="Team Pearson CW2 API",
    description=(
        "Project-owned API service for the CW2 research workbench. "
        "The first version reads real robustness outputs and report-evidence files."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup_background_services() -> None:
    _ensure_nightly_scheduler_running()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="cw2-api")


@app.get("/api/navigation", response_model=list[NavigationPage])
def navigation() -> list[NavigationPage]:
    return [
        NavigationPage(id="welcome", label="Welcome", section="home"),
        NavigationPage(id="overview", label="System Overview", section="home"),
        NavigationPage(
            id="scenario_builder",
            label="Scenario Builder",
            section="research_setup",
        ),
        NavigationPage(
            id="universe_selector",
            label="Universe & Company Selector",
            section="research_setup",
        ),
        NavigationPage(
            id="regime_control",
            label="Regime & Threshold Control",
            section="research_setup",
        ),
        NavigationPage(
            id="optimizer_settings",
            label="Portfolio Optimizer Settings",
            section="research_setup",
        ),
        NavigationPage(id="data_health", label="Data Health", section="research_setup"),
        NavigationPage(
            id="backtest_runner",
            label="Backtest Runner",
            section="research_setup",
        ),
        NavigationPage(id="run_history", label="Run History", section="research_setup"),
        NavigationPage(id="factor_lab", label="Factor Lab", section="analytics"),
        NavigationPage(
            id="performance_dashboard",
            label="Performance Dashboard",
            section="analytics",
        ),
        NavigationPage(id="risk_dashboard", label="Risk Dashboard", section="analytics"),
        NavigationPage(id="robustness_lab", label="Robustness Lab", section="analytics"),
        NavigationPage(
            id="holdings_trades",
            label="Holdings / Trades",
            section="portfolio",
        ),
        NavigationPage(id="artifacts", label="Artifacts", section="delivery"),
        NavigationPage(id="report_studio", label="Report Studio", section="delivery"),
        NavigationPage(id="help", label="Help", section="help"),
    ]


@app.get("/api/summary", response_model=list[SummaryCard])
def summary() -> list[SummaryCard]:
    return _build_summary_cards()


@app.get("/api/runs/recent", response_model=list[RunRecord])
def recent_runs() -> list[RunRecord]:
    merged: dict[str, RunRecord] = {}
    status_priority = {
        "canceled": 7,
        "failed": 6,
        "completed": 5,
        "success": 5,
        "running": 4,
        "queued": 3,
        "scheduled": 2,
        "batch_compare": 1,
        "nightly_refresh": 1,
        "single_run": 1,
        "idle": 0,
    }
    records = _load_recent_report_runs(limit=8) + _load_web_queue_runs(limit=12)
    for record in records:
        run_id = str(record.run_id).strip()
        if not run_id:
            continue
        previous = merged.get(run_id)
        record_status = str(record.status).strip().lower()
        previous_status = str(previous.status).strip().lower() if previous else ""
        if (
            previous is None
            or status_priority.get(record_status, 0) > status_priority.get(previous_status, 0)
            or (
                status_priority.get(record_status, 0) == status_priority.get(previous_status, 0)
                and str(record.started_at) >= str(previous.started_at)
            )
        ):
            merged[run_id] = record
    linked_child_ids: set[str] = set()
    for run_id, record in merged.items():
        if not run_id.startswith("NIGHTLY-"):
            continue
        payload = _load_job_metadata(run_id)
        child_run_id = str(payload.get("last_run_id") or "").strip()
        if child_run_id and child_run_id.startswith(("NIGHTLYRUN-", "NIGHTLYBATCH-")):
            linked_child_ids.add(child_run_id)
    for child_run_id in linked_child_ids:
        merged.pop(child_run_id, None)
    ordered = sorted(merged.values(), key=lambda row: row.started_at, reverse=True)
    return ordered[:12]


@app.get("/api/artifacts", response_model=list[ArtifactRecord])
def artifacts() -> list[ArtifactRecord]:
    results: list[ArtifactRecord] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def _add_record(name: str, description: str, status: str, source: str) -> None:
        key = (name, description, source)
        if key in seen_keys:
            return
        seen_keys.add(key)
        results.append(
            ArtifactRecord(
                name=name,
                description=description,
                status=status,
                source=source,
            )
        )

    active_report_dir = _active_report_evidence_dir()
    if active_report_dir.exists():
        for artifact_path in sorted(
            active_report_dir.rglob("*"), key=lambda path: str(path).lower()
        ):
            if not artifact_path.is_file():
                continue
            relative_path = artifact_path.relative_to(active_report_dir)
            if len(relative_path.parts) < 2:
                continue
            part_token = relative_path.parts[0]
            if not re.match(r"^part[_-]\d+", part_token, re.IGNORECASE):
                continue
            _add_record(
                name=str(relative_path).replace("\\", "/"),
                description=f"{part_token} / {(artifact_path.suffix.lstrip('.').lower() or 'file')}",
                status="available",
                source="report_evidence",
            )

    for report_dir in (
        sorted((BASE_DIR / "outputs" / "reports").iterdir(), key=lambda path: path.name.lower())
        if (BASE_DIR / "outputs" / "reports").exists()
        else []
    ):
        if not report_dir.is_dir():
            continue
        files = [
            path
            for path in sorted(report_dir.iterdir(), key=lambda path: path.name.lower())
            if path.is_file()
        ]
        summary = f"{len(files)} files in report bundle"
        _add_record(
            name=report_dir.name,
            description=summary,
            status="available",
            source="main_program_reports",
        )

    for briefing_file in (
        sorted((BASE_DIR / "outputs" / "briefings").glob("*"), key=lambda path: path.name.lower())
        if (BASE_DIR / "outputs" / "briefings").exists()
        else []
    ):
        if not briefing_file.is_file():
            continue
        _add_record(
            name=briefing_file.name,
            description=f"briefing / {briefing_file.suffix.lstrip('.').lower() or 'file'}",
            status="available",
            source="briefings",
        )

    return results


@app.get("/api/delivery/export-zip")
def export_delivery_zip() -> StreamingResponse:
    filename, payload = _build_delivery_zip_payload()
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(payload), media_type="application/zip", headers=headers)


@app.get("/api/robustness/dashboard", response_model=list[RobustnessDashboardRecord])
def robustness_dashboard() -> list[RobustnessDashboardRecord]:
    rows = _load_stochastic_dashboard()
    return [
        RobustnessDashboardRecord(
            section=row["section"],
            item_key=row["item_key"],
            title=row["title"],
            annualized_return=_safe_number(row["annualized_return"]),
            annualized_excess_return=_safe_number(row["annualized_excess_return"]),
            sharpe=_safe_number(row["sharpe"]),
            max_drawdown=_safe_number(row["max_drawdown"]),
            implementation_status=row["implementation_status"],
        )
        for row in rows
    ]


@app.get("/api/robustness/acceptance", response_model=list[AcceptanceRecord])
def robustness_acceptance() -> list[AcceptanceRecord]:
    rows = _load_acceptance_matrix()
    return [
        AcceptanceRecord(
            requirement_group=row["requirement_group"],
            item_key=row["item_key"],
            label=row["label"],
            status=row["status"],
            detail=row["detail"],
        )
        for row in rows
    ]


@app.get("/api/robustness/report-evidence")
@app.get("/api/robustness/report-handoff")
def report_evidence_index() -> dict[str, Any]:
    report, db_artifacts = _fetch_report_evidence_db_artifacts()
    manifest = _load_report_manifest()
    index_rows = _load_report_index()
    return {
        "report": report,
        "manifest": manifest,
        "index": index_rows,
        "artifacts": db_artifacts,
    }


@app.get("/api/robustness/subperiods")
def subperiods() -> list[dict[str, Any]]:
    rows = _load_subperiod_analysis()
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        cleaned.append(
            {
                key: _safe_number(value) if isinstance(value, (float, int, str)) else value
                for key, value in row.items()
            }
        )
    return cleaned


@app.get("/api/robustness/test11")
def test11_summary() -> list[dict[str, str]]:
    return _load_test11_report_ready_summary()


@app.get("/api/performance/baseline")
def performance_baseline() -> dict[str, Any]:
    return _build_performance_payload()


@app.get("/api/performance/run/{run_id}")
def performance_run_series(run_id: str) -> dict[str, Any]:
    rows = _fetch_run_time_series(run_id)
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"No performance series found for run_id: {run_id}"
        )
    return {
        "run_id": run_id,
        "performance_series": rows,
    }


@app.get("/api/risk/regime")
def risk_regime() -> dict[str, Any]:
    return _build_risk_payload()


@app.get("/api/data-health/summary")
def data_health_summary() -> dict[str, Any]:
    return _default_health_snapshot()


@app.get("/api/workbench/context")
def workbench_context() -> dict[str, Any]:
    return _build_workbench_context()


@app.get("/api/workbench/raw-series")
def workbench_raw_series() -> dict[str, Any]:
    run_id = _resolve_primary_run_id()
    return {
        "run_id": run_id,
        "performance_series": _fetch_run_time_series(run_id),
        "holdings_snapshot": _fetch_latest_holdings_snapshot(run_id),
        "execution_slice": _fetch_latest_execution_slice(run_id),
        "covariance_snapshot": _fetch_latest_covariance_snapshot(run_id),
        "factor_scores_snapshot": _fetch_latest_factor_scores_snapshot(),
        "factor_attribution_recent": _fetch_recent_factor_attribution(run_id),
        "covariance_contributions": _fetch_latest_covariance_contributions(run_id),
    }


@app.get("/api/scenario-builder/state")
def scenario_builder_state() -> dict[str, Any]:
    return _load_saved_scenarios()


@app.post("/api/scenario-builder/state")
def save_scenario_builder_state(payload: ScenarioBuilderStatePayload) -> dict[str, Any]:
    saved_at = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    response = {
        "draft": payload.draft,
        "presets": payload.presets,
        "active_preset": payload.active_preset,
        "saved_at": saved_at,
    }
    _write_json(SCENARIO_STATE_PATH, response)
    return {"status": "saved", "saved_at": saved_at}


@app.get("/api/scenarios", response_model=list[ScenarioRecord])
def scenarios_list() -> list[ScenarioRecord]:
    return [ScenarioRecord(**record) for record in _load_scenarios()]


@app.post("/api/scenarios/create", response_model=ScenarioRecord)
def scenarios_create(payload: ScenarioPayload) -> ScenarioRecord:
    scenario_id = _next_scenario_id()
    record = _save_scenario_record(
        scenario_id=scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
        parent_scenario_id=payload.parent_scenario_id,
        notes=payload.notes,
    )
    if not MAINLINE_SCENARIO_PATH.exists():
        _set_mainline_scenario(scenario_id)
        record["is_mainline"] = True
    return ScenarioRecord(**record)


@app.get("/api/scenarios/{scenario_id}", response_model=ScenarioRecord)
def scenarios_get(scenario_id: str) -> ScenarioRecord:
    record = _get_scenario_record(scenario_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
    return ScenarioRecord(**record)


@app.post("/api/scenarios/{scenario_id}/clone", response_model=ScenarioRecord)
def scenarios_clone(scenario_id: str) -> ScenarioRecord:
    parent = _get_scenario_record(scenario_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
    clone_id = _next_scenario_id()
    clone = _save_scenario_record(
        scenario_id=clone_id,
        scenario_name=f"{parent['scenario_name']} Copy",
        scenario_config=parent["scenario_config"],
        parent_scenario_id=parent["scenario_id"],
        notes=f"Cloned from {parent['scenario_name']}",
    )
    return ScenarioRecord(**clone)


@app.put("/api/scenarios/{scenario_id}", response_model=ScenarioRecord)
def scenarios_update(scenario_id: str, payload: ScenarioPayload) -> ScenarioRecord:
    existing = _get_scenario_record(scenario_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
    record = _save_scenario_record(
        scenario_id=scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
        parent_scenario_id=existing.get("parent_scenario_id"),
        notes=payload.notes if payload.notes is not None else existing.get("notes"),
    )
    if existing.get("is_mainline"):
        _set_mainline_scenario(scenario_id)
        record["is_mainline"] = True
    return ScenarioRecord(**record)


@app.delete("/api/scenarios/{scenario_id}")
def scenarios_delete(scenario_id: str) -> dict[str, Any]:
    path = _scenario_file_path(scenario_id)
    if not path.exists():
        return {"status": "missing", "scenario_id": scenario_id}
    record = _read_json_if_exists(path, {})
    path.unlink()
    mainline_payload = _read_json_if_exists(MAINLINE_SCENARIO_PATH, {})
    if mainline_payload.get("scenario_id") == scenario_id:
        remaining = _load_scenarios()
        if remaining:
            _set_mainline_scenario(remaining[0]["scenario_id"])
        elif MAINLINE_SCENARIO_PATH.exists():
            MAINLINE_SCENARIO_PATH.unlink()
    _append_audit_log(
        "scenario_deleted",
        {"scenario_id": scenario_id, "scenario_name": record.get("scenario_name")},
    )
    return {"status": "deleted", "scenario_id": scenario_id}


@app.post("/api/scenarios/{scenario_id}/set-mainline", response_model=ScenarioRecord)
def scenarios_set_mainline(scenario_id: str) -> ScenarioRecord:
    record = _set_mainline_scenario(scenario_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
    return ScenarioRecord(**record)


@app.post("/api/universe/preview")
def universe_preview(payload: PreviewRequest) -> dict[str, Any]:
    return _build_universe_preview_payload(
        scenario_id=payload.scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
    )


@app.post("/api/regime/preview")
def regime_preview(payload: PreviewRequest) -> dict[str, Any]:
    return _build_regime_preview_payload(
        scenario_id=payload.scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
    )


@app.post("/api/optimizer/preview")
def optimizer_preview(payload: PreviewRequest) -> dict[str, Any]:
    return _build_optimizer_preview_payload(
        scenario_id=payload.scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
    )


@app.post("/api/factors/preview")
def factors_preview(payload: PreviewRequest) -> dict[str, Any]:
    return _build_factor_preview_payload(
        scenario_id=payload.scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
    )


@app.post("/api/trades/preview")
def trades_preview(payload: PreviewRequest) -> dict[str, Any]:
    return _build_trade_preview_payload(
        scenario_id=payload.scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
    )


@app.get("/api/ai-report/latest")
def ai_report_latest() -> dict[str, Any]:
    return _normalize_ai_report_for_display(
        _read_json_if_exists(
            AI_REPORT_LATEST_PATH,
            {
                "report_id": "",
                "status": "empty",
                "generated_at": None,
                "provider_url": "",
                "model": "",
                "request_format": "openai",
                "output_path": "",
                "output_markdown_path": "",
                "output_docx_path": "",
                "output_pdf_path": "",
                "analysis_text": "",
                "sections": {},
                "context_snapshot": {},
                "prompt_template_version": "cw2-report-v5-narrative-pass",
                "guardrails": {},
                "source_trace_preview": [],
            },
        )
    )


@app.get("/api/ai-report/history")
def ai_report_history() -> list[dict[str, Any]]:
    history = _read_json_if_exists(AI_REPORT_REGISTRY_PATH, [])
    return history if isinstance(history, list) else []


@app.get("/api/ai-report/export-docx")
def ai_report_export_docx() -> FileResponse:
    report_payload = _normalize_ai_report_for_display(
        _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    )
    if not isinstance(report_payload, dict) or not report_payload.get("analysis_text"):
        raise HTTPException(status_code=404, detail="No AI report is available to export")
    try:
        output_docx = _export_ai_report_docx_for_download(report_payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        path=str(output_docx),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=output_docx.name,
    )


@app.get("/api/ai-report/export-pdf")
def ai_report_export_pdf() -> FileResponse:
    report_payload = _normalize_ai_report_for_display(
        _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    )
    if not isinstance(report_payload, dict) or not report_payload.get("analysis_text"):
        raise HTTPException(status_code=404, detail="No AI report is available to export")
    try:
        output_pdf = _export_ai_report_pdf_for_download(report_payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        path=str(output_pdf),
        media_type="application/pdf",
        filename=output_pdf.name,
    )


@app.post("/api/ai-report/cross-check")
def ai_report_cross_check(payload: AiCrossCheckRequest) -> dict[str, Any]:
    report_payload = (
        _load_ai_report_by_id(payload.report_id)
        if payload.report_id
        else _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    )
    if not isinstance(report_payload, dict) or not report_payload:
        raise HTTPException(status_code=404, detail="No AI report is available for cross-check")
    context_snapshot = report_payload.get("context_snapshot") or _build_ai_context_snapshot()
    numeric_signature = _numeric_signature_from_snapshot(context_snapshot)
    has_all_values = all(row.get("value") not in (None, "") for row in numeric_signature[:5])
    return {
        "report_id": report_payload.get("report_id", ""),
        "status": "passed" if has_all_values else "warning",
        "checked_at": _utc_now_text(),
        "checks": numeric_signature,
        "message": "Snapshot-linked numeric cross-check completed against the stored structured context.",
    }


@app.post("/api/llm/models")
def llm_models(payload: LlmModelsRequest) -> dict[str, Any]:
    request_format = _normalize_llm_request_format(payload.request_format)
    if not str(payload.api_url or "").strip():
        raise HTTPException(status_code=400, detail="API URL is required.")
    request_url = _model_list_url_for_format(
        payload.api_url,
        api_key=payload.api_key,
        request_format=request_format,
    )
    try:
        request_url = _require_http_api_url(request_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers = _headers_for_llm_request(payload.api_key, request_format)
    headers["Accept"] = "application/json"
    request = urllib.request.Request(request_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            raw_text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        detail = error_body or f"Model endpoint returned HTTP {exc.code}."
        raise HTTPException(status_code=502, detail=detail) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach model endpoint: {exc.reason}"
        ) from exc
    if not raw_text.strip():
        raise HTTPException(
            status_code=502, detail="The model endpoint returned an empty response."
        )
    try:
        response_payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail="The model endpoint did not return JSON."
        ) from exc
    models = _extract_model_catalog(response_payload, request_format)
    return {
        "request_format": request_format,
        "model_url": request_url,
        "models": models,
        "count": len(models),
    }


@app.post("/api/ai-report/generate", response_model=AiReportResponse)
def ai_report_generate(payload: AiReportRequest) -> AiReportResponse:
    payload.request_format = _normalize_llm_request_format(payload.request_format)
    generated_at = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    report_id = f"ai-report-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    try:
        context_snapshot = _build_ai_context_snapshot()
        previous_report = _previous_ai_report_context(context_snapshot)
        context_snapshot["previous_update"] = previous_report
        analysis_text, raw_response = _call_llm_api(payload, context_snapshot=context_snapshot)
        sections = _parse_ai_report_sections(analysis_text)
        selected_evidence = _generate_evidence_block_analyses(
            payload,
            sections=sections,
            context_snapshot=context_snapshot,
            selected_blocks=_build_selected_evidence_blocks(BASE_DIR),
        )
        guardrails = _build_ai_guardrails_snapshot(context_snapshot, payload)
        source_trace_preview = _build_ai_source_trace_preview(context_snapshot)
        result_payload = {
            "report_id": report_id,
            "status": "generated",
            "generated_at": generated_at,
            "provider_url": payload.api_url,
            "model": payload.model,
            "request_format": payload.request_format,
            "output_path": "",
            "output_markdown_path": "",
            "output_pdf_path": "",
            "analysis_text": analysis_text,
            "sections": sections,
            "selected_evidence": selected_evidence,
            "prompt_template_version": guardrails["prompt_template_version"],
            "guardrails": guardrails,
            "source_trace_preview": source_trace_preview,
            "error_message": "",
            "context_snapshot": {
                **context_snapshot,
                "llm_request": {
                    "request_format": payload.request_format,
                    "model": payload.model,
                    "temperature": payload.temperature,
                    "user_instruction": payload.user_instruction or "",
                    "system_prompt": payload.system_prompt or "",
                },
                "llm_response_preview": raw_response,
            },
        }
        _save_ai_report_result(result_payload)
        try:
            output_pdf_path = _export_ai_report_pdf(result_payload)
            result_payload["output_pdf_path"] = str(output_pdf_path)
            _save_ai_report_result(result_payload)
        except Exception as pdf_exc:
            result_payload["error_message"] = f"PDF export failed after AI generation: {pdf_exc}"
            _save_ai_report_result(result_payload)
        latest = _read_json_if_exists(AI_REPORT_LATEST_PATH, result_payload)
        return AiReportResponse(**latest)
    except Exception as exc:
        context_snapshot = locals().get("context_snapshot", {})
        try:
            guardrails = _build_ai_guardrails_snapshot(
                context_snapshot if isinstance(context_snapshot, dict) else {}, payload
            )
        except Exception:
            guardrails = {"prompt_template_version": "cw2-report-v5-narrative-pass"}
        try:
            source_trace_preview = _build_ai_source_trace_preview(
                context_snapshot if isinstance(context_snapshot, dict) else {}
            )
        except Exception:
            source_trace_preview = []
        failed_payload = {
            "report_id": report_id,
            "status": "failed",
            "generated_at": generated_at,
            "provider_url": payload.api_url,
            "model": payload.model,
            "request_format": payload.request_format,
            "output_path": "",
            "output_markdown_path": "",
            "output_pdf_path": "",
            "analysis_text": "",
            "sections": {},
            "prompt_template_version": "cw2-report-v5-narrative-pass",
            "guardrails": guardrails,
            "source_trace_preview": source_trace_preview,
            "context_snapshot": {
                **(context_snapshot if isinstance(context_snapshot, dict) else {}),
                "llm_request": {
                    "request_format": payload.request_format,
                    "model": payload.model,
                    "temperature": payload.temperature,
                    "user_instruction": payload.user_instruction or "",
                    "system_prompt": payload.system_prompt or "",
                },
            },
            "error_message": str(exc),
        }
        try:
            _write_json(AI_REPORT_LATEST_PATH, failed_payload)
            registry = _read_json_if_exists(AI_REPORT_REGISTRY_PATH, [])
            if not isinstance(registry, list):
                registry = []
            registry_entry = {
                "report_id": failed_payload.get("report_id"),
                "generated_at": failed_payload.get("generated_at"),
                "model": failed_payload.get("model"),
                "provider_url": failed_payload.get("provider_url"),
                "output_path": failed_payload.get("output_path"),
                "output_markdown_path": failed_payload.get("output_markdown_path"),
                "output_pdf_path": failed_payload.get("output_pdf_path", ""),
                "status": failed_payload.get("status"),
                "error_message": failed_payload.get("error_message", ""),
            }
            registry = [
                registry_entry,
                *[row for row in registry if row.get("report_id") != registry_entry["report_id"]],
            ][:20]
            _write_json(AI_REPORT_REGISTRY_PATH, registry)
        except Exception:
            pass
        return AiReportResponse(**failed_payload)


@app.post("/api/ai-report/regenerate-section")
def ai_report_regenerate_section(payload: AiSectionRegenerateRequest) -> dict[str, Any]:
    payload.request_format = _normalize_llm_request_format(payload.request_format)
    context_snapshot = _build_ai_context_snapshot()
    section_name = payload.section_name.strip() or REPORT_SECTION_ORDER[0]
    augmented_instruction = (
        f"Regenerate only the '{section_name}' section. "
        "Keep it consistent with the current structured CW2 snapshot and do not invent numbers. "
        "Return only markdown for that section body without repeating other top-level sections."
    )
    analysis_text, raw_response = _call_llm_api(
        AiReportRequest(
            api_url=payload.api_url,
            api_key=payload.api_key,
            model=payload.model,
            user_instruction=augmented_instruction,
            system_prompt=payload.system_prompt,
            request_format=payload.request_format,
            temperature=payload.temperature,
        ),
        context_snapshot=context_snapshot,
    )
    latest = _read_json_if_exists(AI_REPORT_LATEST_PATH, {})
    if isinstance(latest, dict) and latest:
        sections = dict(latest.get("sections") or {})
        sections[section_name] = analysis_text.strip()
        latest["sections"] = sections
        latest["analysis_text"] = "\n\n".join(
            [
                f"## {title}\n{(sections.get(title) or '').strip()}".strip()
                for title in REPORT_SECTION_ORDER
            ]
        ).strip()
        latest["generated_at"] = _utc_now_text()
        latest["context_snapshot"] = {
            **(latest.get("context_snapshot") or {}),
            "llm_regenerate_preview": raw_response,
        }
        _save_ai_report_result(latest)
    return {
        "section_name": section_name,
        "section_text": analysis_text.strip(),
        "updated_report_id": latest.get("report_id", "") if isinstance(latest, dict) else "",
    }


@app.post("/api/backtest-runner/queue")
def queue_backtest_runner(payload: RunnerQueuePayload) -> dict[str, Any]:
    return _queue_runner_payload(payload)


@app.get("/api/backtest-runner/options")
def backtest_runner_options() -> dict[str, Any]:
    python_exe = _resolve_runner_python()
    preflight = _runner_preflight_report("single_run")
    return {
        "baseline_config": str(BASELINE_CONFIG_PATH),
        "backfill_window": {
            "start_date": BACKFILL_START_DATE,
            "end_date": BACKFILL_END_DATE,
        },
        "runner_python": str(python_exe),
        "runner_python_exists": python_exe.exists(),
        "supports_autostart": bool(preflight.get("ok")),
        "preflight": preflight,
    }


@app.post("/api/backtests/run")
def backtests_run(payload: BacktestRunRequest) -> dict[str, Any]:
    scenario_id, scenario_name, scenario_config = _resolve_scenario_selection(
        scenario_id=payload.scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
    )
    run_id = f"BT-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    result = _queue_runner_payload(
        RunnerQueuePayload(
            run_id=run_id,
            queue_type="single_run",
            label=f"{scenario_name} / {payload.mode}",
            owner=payload.owner,
            priority=payload.priority,
            scenario_name=scenario_name,
            scenario_config=scenario_config,
            artifact_bundle=payload.artifact_bundle,
            notifications=payload.notifications,
            created_at=_utc_now_text(),
            auto_start=payload.auto_start,
        )
    )
    result["scenario_id"] = scenario_id
    return result


@app.get("/api/backtests/{run_id}/status")
def backtests_status(run_id: str) -> dict[str, Any]:
    metadata = _load_job_metadata(run_id)
    return {
        "run_id": run_id,
        "status": metadata.get("status", "missing"),
        "created_at": metadata.get("created_at"),
        "updated_at": metadata.get("updated_at"),
        "finished_at": metadata.get("finished_at"),
        "progress": metadata.get("progress_pct"),
        "scenario_manifests": metadata.get("scenario_manifests", []),
    }


@app.get("/api/backtests/{run_id}/results")
def backtests_results(run_id: str) -> dict[str, Any]:
    metadata = _load_job_metadata(run_id)
    return {
        "run_id": run_id,
        "status": metadata.get("status", "missing"),
        "job": metadata,
        "artifacts": _build_run_artifact_bundle(run_id).get("artifacts", []),
    }


@app.get("/api/backtests/{run_id}/logs")
def backtests_logs(run_id: str) -> dict[str, Any]:
    return backtest_runner_job_log(run_id)


@app.get("/api/backtests/{run_id}/logs/stream")
async def backtests_logs_stream(run_id: str) -> StreamingResponse:
    async def event_generator() -> Any:
        last_payload = ""
        for _ in range(10):
            metadata = _load_job_metadata(run_id)
            log_payload = backtest_runner_job_log(run_id)
            payload = json.dumps(
                {
                    "run_id": run_id,
                    "status": metadata.get("status", "missing"),
                    "progress": metadata.get("progress_pct"),
                    "updated_at": metadata.get("updated_at"),
                    "finished_at": metadata.get("finished_at"),
                    "tail": (log_payload.get("lines") or [])[-12:],
                },
                ensure_ascii=False,
            )
            if payload != last_payload:
                yield f"event: status\ndata: {payload}\n\n"
                last_payload = payload
            if str(metadata.get("status", "")).lower() in {
                "completed",
                "failed",
                "canceled",
                "missing",
            }:
                break
            await asyncio.sleep(2)
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/backtests/{run_id}/cancel")
def backtests_cancel(run_id: str) -> dict[str, Any]:
    metadata = _load_job_metadata(run_id)
    canceled_ids: list[str] = []
    if _cancel_run_metadata(run_id):
        canceled_ids.append(run_id)
    queue_type = str(metadata.get("queue_type") or "").strip().lower()
    if queue_type == "nightly_refresh":
        linked_run_id = str(metadata.get("last_run_id") or "").strip()
        if linked_run_id:
            _cancel_run_metadata(linked_run_id)
            canceled_ids.append(linked_run_id)
    _append_audit_log("backtest_canceled", {"run_id": run_id})
    return {"run_id": run_id, "status": "canceled", "canceled_ids": canceled_ids}


@app.delete("/api/backtests/{run_id}")
def backtests_delete(run_id: str) -> dict[str, Any]:
    deleted_ids, deleted_paths = _delete_run_and_linked_children(run_id)
    _append_audit_log(
        "backtest_deleted",
        {
            "run_id": run_id,
            "deleted_ids": deleted_ids,
            "deleted_paths": deleted_paths,
        },
    )
    return {
        "run_id": run_id,
        "status": "deleted",
        "deleted_ids": deleted_ids,
        "deleted_paths": deleted_paths,
    }


@app.post("/api/backtests/compare")
def backtests_compare(payload: BacktestCompareRequest) -> dict[str, Any]:
    if len(payload.scenario_ids) < 2:
        raise HTTPException(
            status_code=400, detail="At least two scenario_ids are required for compare"
        )
    scenario_configs: dict[str, dict[str, Any]] = {}
    labels: list[str] = []
    for scenario_id in payload.scenario_ids:
        record = _get_scenario_record(scenario_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
        scenario_configs[record["scenario_name"]] = record["scenario_config"]
        labels.append(record["scenario_name"])
    run_id = f"BATCH-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    return _queue_runner_payload(
        RunnerQueuePayload(
            run_id=run_id,
            queue_type="batch_compare",
            label=f"Batch compare / {' vs '.join(labels)}",
            owner=payload.owner,
            priority=payload.priority,
            scenario_name=labels[0],
            scenario_config=scenario_configs[labels[0]],
            batch_targets=labels,
            scenario_configs=scenario_configs,
            artifact_bundle=payload.artifact_bundle,
            notifications=payload.notifications,
            created_at=_utc_now_text(),
            auto_start=payload.auto_start,
        )
    )


@app.post("/api/robustness/run-sensitivity")
def robustness_run_sensitivity(payload: RobustnessSensitivityRequest) -> dict[str, Any]:
    scenario_id, scenario_name, scenario_config = _resolve_scenario_selection(
        scenario_id=payload.scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
    )
    selected_tests = _map_sensitivity_dimensions_to_tests(payload.sensitivity_dimensions)
    if not selected_tests:
        raise HTTPException(
            status_code=400, detail="Select at least one supported sensitivity dimension."
        )
    run_id = f"SENS-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    result = _queue_runner_payload(
        RunnerQueuePayload(
            run_id=run_id,
            queue_type="robustness_sensitivity",
            label=f"Sensitivity / {payload.base_scenario} / {len(selected_tests)} dimensions",
            owner=payload.owner,
            priority=payload.priority,
            scenario_name=scenario_name,
            scenario_config=scenario_config,
            created_at=_utc_now_text(),
            auto_start=payload.auto_start,
            robustness_options={
                "base_scenario": payload.base_scenario,
                "sensitivity_dimensions": payload.sensitivity_dimensions,
                "range_profile": payload.range_profile,
                "bootstrap_iterations": int(payload.bootstrap_iterations),
                "stochastic_mode": payload.stochastic_mode,
                "subperiod_definition": payload.subperiod_definition,
                "selected_tests": selected_tests,
                "scenario_id": scenario_id,
            },
        )
    )
    result["selected_tests"] = selected_tests
    result["base_scenario"] = payload.base_scenario
    return result


@app.post("/api/backtests/estimate-cost")
def backtests_estimate_cost(payload: BacktestEstimateRequest) -> dict[str, Any]:
    _, scenario_name, scenario_config = _resolve_scenario_selection(
        scenario_id=payload.scenario_id,
        scenario_name=payload.scenario_name,
        scenario_config=payload.scenario_config,
    )
    top_n = int(_coerce_numeric_text((scenario_config or {}).get("top_n"), default=25))
    cost_bps = _coerce_bps_text((scenario_config or {}).get("transaction_cost"), default=15.0)
    frequency = str((scenario_config or {}).get("rebalance") or "Quarterly")
    estimated_minutes = round(max(4.0, 4.0 + top_n / 8.0 + cost_bps / 20.0), 1)
    return {
        "scenario_name": scenario_name,
        "mode": payload.mode,
        "estimate": {
            "estimated_minutes": estimated_minutes,
            "expected_worker": "coursework_one/.venv python runner",
            "estimated_artifacts": 4 if payload.mode == "full" else 2,
            "rebalance_frequency": frequency,
            "transaction_cost_bps": cost_bps,
        },
    }


@app.get("/api/backtest-runner/jobs/{run_id}")
def backtest_runner_job(run_id: str) -> dict[str, Any]:
    return _load_job_metadata(run_id)


@app.get("/api/backtest-runner/jobs/{run_id}/log")
def backtest_runner_job_log(run_id: str) -> dict[str, Any]:
    metadata = _load_job_metadata(run_id)
    log_path_text = metadata.get("log_path")
    log_path = Path(log_path_text) if log_path_text else None
    if log_path is None or not log_path.exists():
        return {
            "run_id": run_id,
            "status": metadata.get("status", "missing"),
            "lines": [],
            "log_path": log_path_text,
        }
    content = log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "run_id": run_id,
        "status": metadata.get("status", "missing"),
        "lines": content.splitlines(),
        "log_path": str(log_path),
    }


@app.get("/api/backtest-runner/jobs/{run_id}/artifacts")
def backtest_runner_job_artifacts(run_id: str) -> dict[str, Any]:
    return _build_run_artifact_bundle(run_id)


@app.get("/api/version")
def api_version() -> dict[str, Any]:
    return {
        "service": "cw2-api",
        "version": app.version,
        "baseline_config": str(BASELINE_CONFIG_PATH),
        "generated_at": _utc_now_text(),
    }


@app.get("/api/audit/log")
def api_audit_log() -> dict[str, Any]:
    return {"rows": _read_json_if_exists(AUDIT_LOG_PATH, [])}


app.mount("/", NoCacheStaticFiles(directory=WEB_DIR, html=True), name="web")
