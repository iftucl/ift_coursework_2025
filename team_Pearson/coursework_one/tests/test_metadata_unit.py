import json

import modules.output.metadata as metadata_mod


class _FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params):
        self.calls.append((stmt, params))
        return object()


class _FakeBeginCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def begin(self):
        return _FakeBeginCtx(self._conn)


def test_bootstrap_metadata_catalog_skips_when_test_mode(monkeypatch):
    monkeypatch.setenv("CW1_TEST_MODE", "1")
    called = {"db": False}

    def _fake_engine():
        called["db"] = True
        return _FakeEngine(_FakeConn())

    monkeypatch.setattr(metadata_mod, "get_db_engine", _fake_engine)
    metadata_mod.bootstrap_metadata_catalog()
    assert called["db"] is False


def test_bootstrap_metadata_catalog_executes_expected_rows(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    conn = _FakeConn()
    monkeypatch.setattr(metadata_mod, "get_db_engine", lambda: _FakeEngine(conn))

    metadata_mod.bootstrap_metadata_catalog()

    stmt_texts = [stmt.text for stmt, _ in conn.calls]
    assert any("INSERT INTO systematic_equity.dataset_registry" in t for t in stmt_texts)
    assert any("UPDATE systematic_equity.schema_versions" in t for t in stmt_texts)
    assert any("INSERT INTO systematic_equity.schema_versions" in t for t in stmt_texts)
    assert any("INSERT INTO systematic_equity.lineage_edges" in t for t in stmt_texts)

    first_params = conn.calls[0][1]
    assert first_params["dataset_name"] == "company_static"
    assert first_params["refresh_frequency"] == "ad_hoc"
    assert first_params["logical_layer"] == "core"
    assert first_params["supports_pit"] is False

    schema_params = [
        params
        for stmt, params in conn.calls
        if "INSERT INTO systematic_equity.schema_versions" in stmt.text
    ]
    assert any(
        params["dataset_name"] == "source_b_raw_news" and params["version_tag"] == "v2"
        for params in schema_params
    )
    assert any(
        params["dataset_name"] == "source_a_raw_pricing_fundamentals"
        and params["version_tag"] == "v5"
        for params in schema_params
    )
    assert any(
        params["dataset_name"] == "backtest_runs" and params["version_tag"] == "v1"
        for params in schema_params
    )
    assert any(
        params["dataset_name"] == "portfolio_update_decisions" and params["version_tag"] == "v1"
        for params in schema_params
    )
    assert any(
        params["dataset_name"] == "source_coverage_audit" and params["version_tag"] == "v1"
        for params in schema_params
    )


def test_write_quality_snapshot_status_mapping(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    conn = _FakeConn()
    monkeypatch.setattr(metadata_mod, "get_db_engine", lambda: _FakeEngine(conn))

    metadata_mod.write_quality_snapshot(
        run_id="r-pass",
        run_date="2026-03-03",
        dataset_name="factor_observations",
        quality_report={"passed": True, "missing_required": 0},
    )
    metadata_mod.write_quality_snapshot(
        run_id="r-fail",
        run_date="2026-03-03",
        dataset_name="factor_observations",
        quality_report={"passed": False, "missing_required": 2},
    )
    metadata_mod.write_quality_snapshot(
        run_id="r-unknown",
        run_date="2026-03-03",
        dataset_name="factor_observations",
        quality_report={"missing_required": 1},
    )

    assert len(conn.calls) == 3
    statuses = [params["status"] for _, params in conn.calls]
    assert statuses == ["pass", "fail", "unknown"]
    assert all(
        "ON CONFLICT (run_id, run_date, dataset_name) DO UPDATE" in stmt.text
        for stmt, _ in conn.calls
    )

    payload = json.loads(conn.calls[0][1]["quality_report"])
    assert payload["passed"] is True
    assert payload["missing_required"] == 0


def test_write_quality_snapshot_skips_when_test_mode(monkeypatch):
    monkeypatch.setenv("CW1_TEST_MODE", "1")
    called = {"db": False}

    def _fake_engine():
        called["db"] = True
        return _FakeEngine(_FakeConn())

    monkeypatch.setattr(metadata_mod, "get_db_engine", _fake_engine)
    metadata_mod.write_quality_snapshot(
        run_id="r1",
        run_date="2026-03-03",
        dataset_name="factor_observations",
        quality_report={"passed": True},
    )
    assert called["db"] is False


def test_write_source_coverage_audit_upserts_rows(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    conn = _FakeConn()
    monkeypatch.setattr(metadata_mod, "get_db_engine", lambda: _FakeEngine(conn))

    written = metadata_mod.write_source_coverage_audit(
        run_id="run-1",
        run_date="2026-04-16",
        rows=[
            {
                "source_name": "source_b",
                "symbol": "AAPL",
                "parent_in_universe": True,
                "policy_eligible": True,
                "routing_eligible": True,
                "expected_in_run": True,
                "realized_in_run": True,
                "content_available": False,
                "status": "realized_empty",
                "reason_code": "no_articles_in_window",
                "details": {"expected_windows": 2, "succeeded_windows": 2},
            }
        ],
    )

    assert written == 1
    assert len(conn.calls) == 1
    stmt, params = conn.calls[0]
    assert "ON CONFLICT (run_id, run_date, source_name, symbol) DO UPDATE" in stmt.text
    assert params["run_id"] == "run-1"
    assert params["source_name"] == "source_b"
    assert params["status"] == "realized_empty"
    assert params["content_available"] is False
    assert json.loads(params["details_json"]) == {
        "expected_windows": 2,
        "succeeded_windows": 2,
    }
