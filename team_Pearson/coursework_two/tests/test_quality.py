"""Unit tests for CW2 quality snapshot persistence helpers."""

from __future__ import annotations

import json
from datetime import date, datetime

from team_Pearson.coursework_two.modules import ops as ops_mod
from team_Pearson.coursework_two.modules.ops import quality as quality_mod


class _FakeBegin:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, stmt, params):
        self._sink.append((stmt, dict(params)))


class _FakeEngine:
    def __init__(self):
        self.calls = []

    def begin(self):
        return _FakeBegin(self.calls)


def test_record_quality_snapshot_upserts_and_maps_failed_status():
    engine = _FakeEngine()

    quality_mod.record_quality_snapshot(
        engine=engine,
        dataset_name="portfolio_recommendations",
        run_id="run-123",
        run_date="2026-04-15",
        quality_report={"passed": False, "duplicates": 2},
    )

    assert len(engine.calls) == 1
    stmt, params = engine.calls[0]
    assert "ON CONFLICT (run_id, run_date, dataset_name) DO UPDATE" in stmt.text
    assert params["status"] == "fail"
    assert params["run_date"] == "2026-04-15"
    assert json.loads(params["quality_report"]) == {"duplicates": 2, "passed": False}


def test_record_quality_snapshot_maps_warn_pass_and_unknown_statuses():
    engine = _FakeEngine()

    quality_mod.record_quality_snapshot(
        engine=engine,
        dataset_name="dataset_warn",
        run_id="run-warn",
        run_date=datetime(2026, 4, 15, 9, 0),
        quality_report={"warnings": ["missing sector exposure"]},
    )
    quality_mod.record_quality_snapshot(
        engine=engine,
        dataset_name="dataset_pass",
        run_id="run-pass",
        run_date=date(2026, 4, 16),
        quality_report={"passed": True},
    )
    quality_mod.record_quality_snapshot(
        engine=engine,
        dataset_name="dataset_unknown",
        run_id="run-unknown",
        run_date="2026-04-17T08:30:00Z",
        quality_report=None,
    )

    statuses = [params["status"] for _, params in engine.calls]
    run_dates = [params["run_date"] for _, params in engine.calls]
    assert statuses == ["warn", "pass", "unknown"]
    assert run_dates == ["2026-04-15", "2026-04-16", "2026-04-17"]


def test_quality_normalize_run_date_and_ops_getattr_errors():
    assert quality_mod._normalize_run_date(datetime(2026, 4, 18, 10, 0)) == "2026-04-18"
    assert quality_mod._normalize_run_date(date(2026, 4, 19)) == "2026-04-19"

    for value, expected in [
        ("", "run_date is required"),
        ("2026-04", "Invalid run_date value"),
    ]:
        try:
            quality_mod._normalize_run_date(value)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected ValueError")

    try:
        ops_mod.__getattr__("not_real")
    except AttributeError as exc:
        assert str(exc) == "not_real"
    else:
        raise AssertionError("expected AttributeError")
