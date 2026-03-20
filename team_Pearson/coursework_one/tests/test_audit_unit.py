import modules.output.audit as audit_mod


class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _FakeConn:
    def __init__(self, rowcounts):
        self.calls = []
        self._rowcounts = list(rowcounts)

    def execute(self, stmt, params):
        self.calls.append((stmt, params))
        rowcount = self._rowcounts.pop(0) if self._rowcounts else 1
        return _FakeResult(rowcount=rowcount)


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


def test_write_pipeline_run_start_skips_db_when_test_mode(monkeypatch):
    monkeypatch.setenv("CW1_TEST_MODE", "1")
    called = {"db": False}

    def _fake_engine():
        called["db"] = True
        return _FakeEngine(_FakeConn([1]))

    monkeypatch.setattr(audit_mod, "get_db_engine", _fake_engine)

    audit_mod.write_pipeline_run_start(
        run_id="r1",
        run_date="2026-03-01",
        started_at="2026-03-01T00:00:00Z",
        frequency="daily",
        backfill_years=5,
        company_limit=20,
        enabled_extractors="source_a,source_b",
        notes="n",
    )
    assert called["db"] is False


def test_write_pipeline_run_start_executes_single_upsert(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    conn = _FakeConn([1])
    monkeypatch.setattr(audit_mod, "get_db_engine", lambda: _FakeEngine(conn))

    audit_mod.write_pipeline_run_start(
        run_id="r2",
        run_date="2026-03-01",
        started_at="2026-03-01T01:02:03Z",
        frequency="weekly",
        backfill_years=3,
        company_limit=None,
        enabled_extractors="source_b",
        notes="start",
    )

    assert len(conn.calls) == 1
    stmt, params = conn.calls[0]
    assert "ON CONFLICT (run_id) DO UPDATE" in stmt.text
    assert params["run_id"] == "r2"
    assert params["started_at"] == "2026-03-01T01:02:03Z"
    assert params["frequency"] == "weekly"
    assert params["backfill_years"] == 3
    assert params["company_limit"] is None
    assert params["enabled_extractors"] == "source_b"
    assert params["notes"] == "start"


def test_write_pipeline_run_finish_update_hit_no_fallback(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    conn = _FakeConn([1])
    monkeypatch.setattr(audit_mod, "get_db_engine", lambda: _FakeEngine(conn))

    audit_mod.write_pipeline_run_finish(
        run_id="r3",
        run_date="2026-03-01",
        finished_at="2026-03-01T02:00:00Z",
        status="success",
        rows_written=10,
        error_message="",
        error_traceback="",
        notes="done",
    )

    assert len(conn.calls) == 1
    stmt, params = conn.calls[0]
    assert "UPDATE systematic_equity.pipeline_runs" in stmt.text
    assert params["run_id"] == "r3"
    assert params["status"] == "success"
    assert params["rows_written"] == 10


def test_write_pipeline_run_finish_fallback_insert_when_update_misses(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    conn = _FakeConn([0, 1])
    monkeypatch.setattr(audit_mod, "get_db_engine", lambda: _FakeEngine(conn))

    audit_mod.write_pipeline_run_finish(
        run_id="r4",
        run_date="2026-03-01",
        finished_at="2026-03-01T03:00:00Z",
        status="failed",
        rows_written=0,
        error_message="err",
        error_traceback="tb",
        notes="n",
        frequency="daily",
        backfill_years=5,
        company_limit=20,
        enabled_extractors="source_a",
    )

    assert len(conn.calls) == 2
    first_stmt, first_params = conn.calls[0]
    second_stmt, second_params = conn.calls[1]
    assert "UPDATE systematic_equity.pipeline_runs" in first_stmt.text
    assert "INSERT INTO systematic_equity.pipeline_runs" in second_stmt.text
    assert first_params["run_id"] == "r4"
    assert second_params["run_id"] == "r4"
    assert second_params["error_message"] == "err"
    assert second_params["error_traceback"] == "tb"
    assert second_params["enabled_extractors"] == "source_a"


def test_write_pipeline_run_finish_accepts_none_error_fields(monkeypatch):
    monkeypatch.delenv("CW1_TEST_MODE", raising=False)
    conn = _FakeConn([1])
    monkeypatch.setattr(audit_mod, "get_db_engine", lambda: _FakeEngine(conn))

    audit_mod.write_pipeline_run_finish(
        run_id="r5",
        run_date="2026-03-01",
        finished_at="2026-03-01T04:00:00Z",
        status="failed",
        rows_written=0,
        error_message=None,
        error_traceback=None,
        notes=None,
    )

    assert len(conn.calls) == 1
    _, params = conn.calls[0]
    assert params["error_message"] is None
    assert params["error_traceback"] is None
    assert params["notes"] is None
