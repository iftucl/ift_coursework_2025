import json

from modules.output.manifest import (
    MaterializationRegistry,
    RunManifestTracker,
    atomic_config_identity,
    source_a_materialization_key,
)


def test_manifest_gate_requires_all_units_to_reach_terminal_state(tmp_path):
    tracker = RunManifestTracker(
        base_dir=str(tmp_path),
        run_id="run-1",
        run_date="2026-03-14",
        frequency="daily",
        backfill_years=5,
        company_limit=None,
        enabled_extractors=["source_a", "source_b"],
        universe=["AAPL", "MSFT"],
        planned_units=[
            {"unit_id": "source_a:AAPL", "extractor": "source_a", "symbol": "AAPL"},
            {"unit_id": "source_b:AAPL:2026-03-01", "extractor": "source_b", "symbol": "AAPL"},
        ],
    )

    assert tracker.ready_for_final_build() is False

    tracker.mark_unit("source_a:AAPL", "success", details={"loaded_rows": 12})
    assert tracker.ready_for_final_build() is False

    tracker.mark_unit(
        "source_b:AAPL:2026-03-01",
        "skipped",
        details={"reason": "no_fetch_needed_or_filtered"},
    )
    assert tracker.ready_for_final_build() is True

    tracker.mark_final_build("running")
    tracker.mark_final_build("success", rows_written=42)

    with open(tracker.state_path, "r", encoding="utf-8") as fh:
        state = json.load(fh)

    assert state["unit_status_counts"]["pending"] == 0
    assert state["unit_status_counts"]["success"] == 1
    assert state["unit_status_counts"]["skipped"] == 1
    assert state["final_build"]["status"] == "success"
    assert state["final_build"]["rows_written"] == 42


def test_materialization_registry_reuses_success_across_runs(tmp_path):
    registry = MaterializationRegistry(base_dir=str(tmp_path))
    config_identity = atomic_config_identity(
        {"source_a": {"primary_source": "alpha_vantage"}},
        extractor="source_a",
    )
    key = source_a_materialization_key("AAPL", "2026-03-15", 1)

    registry.record_success(
        key,
        run_id="run-1",
        unit_id="source_a:AAPL",
        extractor="source_a",
        config_identity=config_identity,
        details={"loaded_rows": 123, "quality_report": {"row_count": 123}},
    )

    reusable = registry.get_reusable(key, config_identity=config_identity)
    assert reusable is not None
    assert reusable["run_id"] == "run-1"
    assert reusable["details"]["loaded_rows"] == 123


def test_materialization_registry_rejects_config_identity_mismatch(tmp_path):
    registry = MaterializationRegistry(base_dir=str(tmp_path))
    key = source_a_materialization_key("AAPL", "2026-03-15", 1)

    registry.record_success(
        key,
        run_id="run-1",
        unit_id="source_a:AAPL",
        extractor="source_a",
        config_identity="cfg-v1",
        details={"loaded_rows": 5},
    )

    assert registry.get_reusable(key, config_identity="cfg-v2") is None
