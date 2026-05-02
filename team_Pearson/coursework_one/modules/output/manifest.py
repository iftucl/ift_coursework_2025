from __future__ import annotations

"""Lightweight run manifest and materialization tracking for hybrid orchestration."""

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

TERMINAL_UNIT_STATUSES = {"success", "failed", "skipped"}
ATOMIC_MATERIALIZATION_VERSION = "atomic-v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def atomic_config_identity(config: Dict[str, Any], *, extractor: str) -> str:
    """Build a conservative config/version identity for atomic materializations."""
    extractor = str(extractor).strip().lower()
    relevant = {
        "version": ATOMIC_MATERIALIZATION_VERSION,
        "extractor": extractor,
        "symbol_filter": config.get("symbol_filter") or {},
        extractor: config.get(extractor) or {},
    }
    return _stable_json_hash(relevant)


def source_a_materialization_key(symbol: str, run_date: str, backfill_years: int) -> str:
    """Return a stable Source A materialization key for one symbol snapshot."""
    return (
        f"source_a:{str(symbol).strip().upper()}:"
        f"run_date={run_date}:backfill_years={int(backfill_years)}"
    )


def source_b_materialization_key(symbol: str, month_start: str, fetch_end: str) -> str:
    """Return a stable Source B materialization key for one symbol-month window."""
    return (
        f"source_b:{str(symbol).strip().upper()}:"
        f"month_start={month_start}:fetch_end={fetch_end}"
    )


class RunManifestTracker:
    """Track planned work units and final-build gating with lightweight files."""

    def __init__(
        self,
        *,
        base_dir: str,
        run_id: str,
        run_date: str,
        frequency: str,
        backfill_years: int,
        company_limit: Optional[int],
        enabled_extractors: List[str],
        universe: List[str],
        planned_units: List[Dict[str, Any]],
    ) -> None:
        manifest_dir = os.path.join(base_dir, "logs", "manifests")
        os.makedirs(manifest_dir, exist_ok=True)

        self.plan_path = os.path.join(manifest_dir, f"{run_id}.plan.json")
        self.state_path = os.path.join(manifest_dir, f"{run_id}.state.json")
        self.events_path = os.path.join(manifest_dir, f"{run_id}.events.jsonl")
        self.run_id = run_id
        self._status_by_unit = {str(unit["unit_id"]): "pending" for unit in planned_units}
        self._status_counts = {
            "pending": len(planned_units),
            "running": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }
        self._final_build = {
            "status": "not_started",
            "started_at": None,
            "finished_at": None,
            "rows_written": 0,
            "error": "",
        }

        plan_payload = {
            "run_id": run_id,
            "run_date": run_date,
            "frequency": frequency,
            "backfill_years": int(backfill_years),
            "company_limit": company_limit,
            "enabled_extractors": list(enabled_extractors),
            "universe": list(universe),
            "planned_unit_count": len(planned_units),
            "planned_units": planned_units,
            "created_at": _utc_now_iso(),
        }
        with open(self.plan_path, "w", encoding="utf-8") as fh:
            json.dump(plan_payload, fh, ensure_ascii=False, indent=2)

        self._write_state()

    def _append_event(self, payload: Dict[str, Any]) -> None:
        record = dict(payload)
        record.setdefault("timestamp", _utc_now_iso())
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_state(self) -> None:
        payload = {
            "run_id": self.run_id,
            "updated_at": _utc_now_iso(),
            "unit_status_counts": dict(self._status_counts),
            "final_build": dict(self._final_build),
        }
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def mark_unit(
        self,
        unit_id: str,
        status: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update one unit status and persist a corresponding event/state snapshot."""
        unit_id = str(unit_id)
        status = str(status)
        previous = self._status_by_unit.get(unit_id)
        if previous is None:
            raise KeyError(f"Unknown manifest unit_id={unit_id}")
        if previous == status and not details:
            return

        self._status_counts[previous] = max(0, self._status_counts.get(previous, 0) - 1)
        self._status_counts[status] = self._status_counts.get(status, 0) + 1
        self._status_by_unit[unit_id] = status

        self._append_event(
            {
                "event": "unit_status",
                "run_id": self.run_id,
                "unit_id": unit_id,
                "status": status,
                "details": details or {},
            }
        )
        self._write_state()

    def ready_for_final_build(self) -> bool:
        """Return True when every planned unit has reached a terminal state."""
        return (
            self._status_counts.get("pending", 0) == 0
            and self._status_counts.get("running", 0) == 0
        )

    def mark_final_build(
        self,
        status: str,
        *,
        rows_written: int = 0,
        error: str = "",
    ) -> None:
        """Update final-build lifecycle state and persist a manifest event."""
        now = _utc_now_iso()
        if status == "running":
            self._final_build.update(
                {
                    "status": status,
                    "started_at": now,
                    "finished_at": None,
                    "rows_written": 0,
                    "error": "",
                }
            )
        else:
            self._final_build.update(
                {
                    "status": status,
                    "finished_at": now,
                    "rows_written": int(rows_written),
                    "error": error,
                }
            )
            if self._final_build.get("started_at") is None:
                self._final_build["started_at"] = now

        self._append_event(
            {
                "event": "final_build",
                "run_id": self.run_id,
                "status": status,
                "rows_written": int(rows_written),
                "error": error,
            }
        )
        self._write_state()

    def summary(self) -> Dict[str, Any]:
        """Return the current manifest summary."""
        return {
            "unit_status_counts": dict(self._status_counts),
            "final_build": dict(self._final_build),
            "plan_path": self.plan_path,
            "state_path": self.state_path,
            "events_path": self.events_path,
        }


class MaterializationRegistry:
    """Track reusable atomic unit materializations across runs."""

    def __init__(self, *, base_dir: str) -> None:
        registry_dir = os.path.join(base_dir, "logs", "materializations")
        os.makedirs(registry_dir, exist_ok=True)
        self.index_path = os.path.join(registry_dir, "atomic_registry.json")
        self.events_path = os.path.join(registry_dir, "atomic_registry.events.jsonl")
        self._records: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(self.index_path):
            with open(self.index_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh) or {}
            if isinstance(payload, dict):
                self._records = {str(k): v for k, v in payload.items() if isinstance(v, dict)}

    def _write_index(self) -> None:
        with open(self.index_path, "w", encoding="utf-8") as fh:
            json.dump(self._records, fh, ensure_ascii=False, indent=2, sort_keys=True)

    def _append_event(self, payload: Dict[str, Any]) -> None:
        record = dict(payload)
        record.setdefault("timestamp", _utc_now_iso())
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_reusable(
        self, materialization_key: str, *, config_identity: str
    ) -> Optional[Dict[str, Any]]:
        """Return a reusable success record when identity and completeness both match."""
        record = self._records.get(str(materialization_key))
        if not record:
            return None
        if str(record.get("status") or "") != "success":
            return None
        if str(record.get("config_identity") or "") != str(config_identity):
            return None
        if not bool(record.get("complete")):
            return None
        return dict(record)

    def record_success(
        self,
        materialization_key: str,
        *,
        run_id: str,
        unit_id: str,
        extractor: str,
        config_identity: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist a successful, reusable atomic materialization record."""
        payload = {
            "materialization_key": str(materialization_key),
            "run_id": str(run_id),
            "unit_id": str(unit_id),
            "extractor": str(extractor),
            "status": "success",
            "complete": True,
            "config_identity": str(config_identity),
            "details": details or {},
            "updated_at": _utc_now_iso(),
        }
        self._records[str(materialization_key)] = payload
        self._write_index()
        self._append_event({"event": "materialized_success", **payload})
