from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from team_Pearson.coursework_two.modules.robustness import persistence


class _FakeResult:
    def mappings(self):
        return self

    def first(self):
        return {"robustness_report_id": "report-123"}


class _FakeConnection:
    def __init__(self, engine: "_FakeEngine") -> None:
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ARG002
        return False

    def execute(self, sql, params: dict[str, Any] | None = None):  # noqa: ANN001
        sql_text = str(sql)
        self.engine.executed.append((sql_text, params or {}))
        if "RETURNING robustness_report_id" in sql_text:
            return _FakeResult()
        return None


class _FakeCursor:
    def __init__(self, engine: "_FakeEngine") -> None:
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ARG002
        return False

    def execute(self, sql_text: str) -> None:
        self.engine.schema_sql = sql_text


class _FakeRawConnection:
    def __init__(self, engine: "_FakeEngine") -> None:
        self.engine = engine

    def cursor(self):
        return _FakeCursor(self.engine)

    def commit(self) -> None:
        self.engine.committed = True

    def close(self) -> None:
        self.engine.closed = True


class _FakeEngine:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.schema_sql = ""
        self.committed = False
        self.closed = False

    def begin(self):
        return _FakeConnection(self)

    def raw_connection(self):
        return _FakeRawConnection(self)


def test_collect_artifacts_classifies_outputs_and_counts_csv_rows(tmp_path: Path):
    part_root = tmp_path / "part_1"
    part_root.mkdir()
    (part_root / "metrics.csv").write_text("case,return\nbase,0.10\nstress,0.02\n")
    (part_root / "note.md").write_text("# Note\n")
    (tmp_path / "chart.png").write_bytes(b"png")
    (tmp_path / "config.yaml").write_text("run: demo\n")
    (tmp_path / "run.log").write_text("ok\n")
    (tmp_path / "launch.cmd").write_text("echo ok\n")
    (tmp_path / "other.txt").write_text("plain\n")

    artifacts = persistence._collect_artifacts(tmp_path)
    by_name = {item["artifact_name"]: item for item in artifacts}

    assert by_name["part_1/metrics.csv"]["artifact_group"] == "part_1"
    assert by_name["part_1/metrics.csv"]["artifact_role"] == "csv"
    assert by_name["part_1/metrics.csv"]["row_count"] == 2
    assert by_name["part_1/note.md"]["artifact_role"] == "markdown"
    assert by_name["chart.png"]["artifact_role"] == "plot"
    assert by_name["config.yaml"]["artifact_role"] == "config"
    assert by_name["run.log"]["artifact_role"] == "log"
    assert by_name["launch.cmd"]["artifact_role"] == "script"
    assert by_name["other.txt"]["artifact_role"] == "other"
    assert by_name["other.txt"]["artifact_metadata"]["suffix"] == ".txt"


def test_persist_robustness_outputs_writes_header_artifacts_rows_and_quality(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "part_2").mkdir()
    (tmp_path / "part_2" / "ablation.csv").write_text(
        "scenario,return,drawdown\nfull,0.12,\nno_value,0.08,-0.15\n"
    )
    (tmp_path / "summary.md").write_text("# Robustness\n")
    (tmp_path / "evidence.json").write_text('{"ok": true}\n')

    quality_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        persistence,
        "record_quality_snapshot",
        lambda **kwargs: quality_calls.append(kwargs),
    )
    engine = _FakeEngine()

    result = persistence.persist_robustness_outputs(
        engine=engine,
        report_name="formal_6905",
        output_root=tmp_path,
        source_run_id="6905e84b",
    )

    assert result == {
        "robustness_report_id": "report-123",
        "report_name": "formal_6905",
        "output_root": str(tmp_path.resolve()),
        "artifact_count": 3,
        "row_count": 2,
    }
    assert "robustness_reports" in engine.schema_sql
    assert engine.committed is True
    assert engine.closed is True

    executed_sql = "\n".join(sql for sql, _ in engine.executed)
    assert "INSERT INTO systematic_equity.robustness_reports" in executed_sql
    assert "INSERT INTO systematic_equity.robustness_report_artifacts" in executed_sql
    assert "INSERT INTO systematic_equity.robustness_report_rows" in executed_sql

    row_payloads = [
        json.loads(params["row_payload"])
        for sql, params in engine.executed
        if "INSERT INTO systematic_equity.robustness_report_rows" in sql
    ]
    assert row_payloads == [
        {"drawdown": None, "return": 0.12, "scenario": "full"},
        {"drawdown": -0.15, "return": 0.08, "scenario": "no_value"},
    ]
    assert quality_calls[0]["dataset_name"] == "robustness_reports"
    assert quality_calls[0]["run_id"] == "report-123"
    assert quality_calls[0]["quality_report"]["artifact_count"] == 3
    assert quality_calls[0]["quality_report"]["row_count"] == 2


def test_persist_robustness_outputs_handles_missing_root(monkeypatch, tmp_path: Path):
    quality_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        persistence,
        "record_quality_snapshot",
        lambda **kwargs: quality_calls.append(kwargs),
    )
    engine = _FakeEngine()

    result = persistence.persist_robustness_outputs(
        engine=engine,
        report_name="empty",
        output_root=tmp_path / "missing",
    )

    assert result["artifact_count"] == 0
    assert result["row_count"] == 0
    assert quality_calls[0]["quality_report"]["passed"] is False
    assert quality_calls[0]["quality_report"]["output_root_exists"] is False


def test_replace_rows_skips_unreadable_csv_and_normalizes_dates(tmp_path: Path):
    csv_path = tmp_path / "dates.csv"
    pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-03-31"),
                "value": 1.5,
                "missing": pd.NA,
            }
        ]
    ).to_csv(csv_path, index=False)
    engine = _FakeEngine()

    inserted = persistence._replace_rows(
        engine=engine,
        robustness_report_id="report-123",
        artifacts=[
            {
                "artifact_role": "csv",
                "artifact_path": str(csv_path),
                "artifact_name": "part_5/dates.csv",
            },
            {
                "artifact_role": "csv",
                "artifact_path": str(tmp_path / "missing.csv"),
                "artifact_name": "missing.csv",
            },
            {
                "artifact_role": "markdown",
                "artifact_path": str(tmp_path / "summary.md"),
                "artifact_name": "summary.md",
            },
        ],
    )

    assert inserted == 1
    insert_params = [
        params
        for sql, params in engine.executed
        if "INSERT INTO systematic_equity.robustness_report_rows" in sql
    ][0]
    assert insert_params["dataset_name"] == "part_5__dates"
    assert json.loads(insert_params["row_payload"]) == {
        "date": "2026-03-31",
        "missing": None,
        "value": 1.5,
    }


def test_normalize_cell_handles_nan_timestamp_and_fallback_object():
    class _BadIso:
        def isoformat(self):
            raise RuntimeError("bad iso")

        def __str__(self) -> str:
            return "bad-iso"

    assert persistence._normalize_cell(float("nan")) is None
    assert persistence._normalize_cell(pd.Timestamp("2026-04-20")) == "2026-04-20T00:00:00"
    assert persistence._normalize_cell(_BadIso()) == "bad-iso"
