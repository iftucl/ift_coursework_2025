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

    # 7 dataset rows + (3 schema rows * reset+upsert) + 5 lineage rows.
    assert len(conn.calls) == 18

    stmt_texts = [stmt.text for stmt, _ in conn.calls]
    assert any("INSERT INTO systematic_equity.dataset_registry" in t for t in stmt_texts)
    assert any("UPDATE systematic_equity.schema_versions" in t for t in stmt_texts)
    assert any("INSERT INTO systematic_equity.schema_versions" in t for t in stmt_texts)
    assert any("INSERT INTO systematic_equity.lineage_edges" in t for t in stmt_texts)

    first_params = conn.calls[0][1]
    assert first_params["dataset_name"] == "company_static"
    assert first_params["refresh_frequency"] == "ad_hoc"


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
