from decimal import Decimal

import pytest

import modules.output.load as load_mod
from modules.output.load import load_curated


def test_load_curated_empty_returns_zero():
    assert load_curated([], dry_run=False) == 0


def test_load_curated_dry_run_returns_record_count():
    rows = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_load",
            "value": 1.0,
        },
        {
            "symbol": "MSFT",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_load",
            "value": 2.0,
        },
    ]
    assert load_curated(rows, dry_run=True) == 2


def test_load_curated_missing_required_raises_before_db():
    rows = [{"observation_date": "2026-02-14", "factor_name": "test_factor_load", "value": 1.0}]
    with pytest.raises(ValueError, match="Missing required columns"):
        load_curated(rows, dry_run=False)


def test_load_curated_executes_upsert(monkeypatch):
    executed = {"called": False, "constraint": None}

    class _FakeConn:
        def execute(self, stmt):
            executed["called"] = True
            executed["stmt"] = stmt

    class _Ctx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    class _Excluded:
        factor_value = "fv"
        source = "src"
        metric_frequency = "mf"
        source_report_date = "srd"

    class _Stmt:
        excluded = _Excluded()

        def values(self, records):
            self.records = records
            return self

        def on_conflict_do_update(self, constraint, set_, where=None):
            executed["constraint"] = constraint
            executed["set_keys"] = sorted(set_.keys())
            executed["where"] = where
            return "UPSERT_STMT"

    monkeypatch.setattr(load_mod, "datetime", type("DT", (), {"now": staticmethod(lambda: "now")}))

    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))

    import sqlalchemy
    import sqlalchemy.dialects.postgresql as pg

    class _Col:
        def __init__(self, name):
            self.name = name

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("observation_date"),
            _Col("factor_name"),
            _Col("factor_value"),
            _Col("source"),
            _Col("metric_frequency"),
            _Col("source_report_date"),
        ]

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(
        sqlalchemy,
        "Table",
        lambda *args, **kwargs: _FakeTable(),
    )
    monkeypatch.setattr(pg, "insert", lambda table: _Stmt())

    rows = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_load",
            "value": 1.0,
            "source": "alpha_vantage",
            "frequency": "daily",
        }
    ]
    out = load_curated(rows, dry_run=False)
    assert out == 1
    assert executed["called"] is True
    assert executed["constraint"] == "uniq_observation"
    assert executed["where"] is None


def test_load_curated_preserves_existing_non_null_on_null_updates(monkeypatch):
    captured = {}

    class _Expr:
        def __init__(self, label):
            self.label = label

        def is_not(self, value):
            return _Expr(f"{self.label} IS NOT {value}")

        def is_(self, value):
            return _Expr(f"{self.label} IS {value}")

        def __or__(self, other):
            return f"({self.label}) OR ({other.label})"

    class _FakeConn:
        def execute(self, stmt):
            captured["stmt"] = stmt

    class _Ctx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    class _Excluded:
        factor_value = _Expr("excluded.factor_value")
        source = "src"
        metric_frequency = "mf"
        source_report_date = "srd"

    class _Stmt:
        excluded = _Excluded()

        def values(self, records):
            captured["records"] = records
            return self

        def on_conflict_do_update(self, constraint, set_, where=None):
            captured["constraint"] = constraint
            captured["where"] = where
            return "UPSERT_STMT"

    class _Col:
        def __init__(self, name):
            self.name = name

        def is_(self, value):
            return _Expr(f"{self.name} IS {value}")

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("observation_date"),
            _Col("factor_name"),
            _Col("factor_value"),
            _Col("source"),
            _Col("metric_frequency"),
            _Col("source_report_date"),
        ]

    monkeypatch.setattr(load_mod, "datetime", type("DT", (), {"now": staticmethod(lambda: "now")}))
    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))
    import sqlalchemy
    import sqlalchemy.dialects.postgresql as pg

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())
    monkeypatch.setattr(pg, "insert", lambda table: _Stmt())

    rows = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-02-14",
            "factor_name": "daily_return",
            "factor_value": None,
            "source": "alpha_vantage",
            "metric_frequency": "daily",
            "source_report_date": "2026-02-14",
        }
    ]

    assert load_curated(rows, dry_run=False) == 1
    assert captured["constraint"] == "uniq_observation"
    assert captured["where"] == "(excluded.factor_value IS NOT None) OR (factor_value IS None)"


def test_load_curated_ignores_extra_columns_not_in_table(monkeypatch):
    captured = {}

    class _FakeConn:
        def execute(self, stmt):
            captured["stmt"] = stmt

    class _Ctx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    class _Excluded:
        factor_value = "fv"
        source = "src"
        metric_frequency = "mf"
        source_report_date = "srd"

    class _Stmt:
        excluded = _Excluded()

        def values(self, records):
            captured["records"] = records
            return self

        def on_conflict_do_update(self, constraint, set_, where=None):
            return "UPSERT_STMT"

    class _Col:
        def __init__(self, name):
            self.name = name

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("observation_date"),
            _Col("factor_name"),
            _Col("factor_value"),
        ]

    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))
    import sqlalchemy
    import sqlalchemy.dialects.postgresql as pg

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())
    monkeypatch.setattr(pg, "insert", lambda table: _Stmt())

    rows = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_load",
            "factor_value": 1.0,
            "run_id": "abc",
        }
    ]
    assert load_curated(rows, dry_run=False) == 1
    assert "run_id" not in captured["records"][0]


def test_load_curated_drops_invalid_date(monkeypatch):
    class _Col:
        def __init__(self, name):
            self.name = name

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("observation_date"),
            _Col("factor_name"),
            _Col("factor_value"),
        ]

    class _Engine:
        def begin(self):
            raise AssertionError("should not hit DB execute when no valid rows")

    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))
    import sqlalchemy

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())

    rows = [
        {
            "symbol": "AAPL",
            "observation_date": "NaT",
            "factor_name": "test_factor_load",
            "factor_value": 1.0,
        }
    ]
    assert load_curated(rows, dry_run=False) == 0


def test_load_financial_observations_executes_upsert(monkeypatch):
    executed = {"called": False, "constraint": None}

    class _FakeConn:
        def execute(self, stmt):
            executed["called"] = True
            executed["stmt"] = stmt

    class _Ctx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    class _Excluded:
        metric_value = "mv"
        currency = "ccy"
        period_type = "period"
        source = "src"
        as_of = "as_of"
        metric_definition = "defn"

    class _Stmt:
        excluded = _Excluded()

        def values(self, records):
            self.records = records
            return self

        def on_conflict_do_update(self, constraint, set_, where=None):
            executed["constraint"] = constraint
            executed["set_keys"] = sorted(set_.keys())
            executed["where"] = where
            return "UPSERT_STMT"

    monkeypatch.setattr(load_mod, "datetime", type("DT", (), {"now": staticmethod(lambda: "now")}))
    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))

    import sqlalchemy
    import sqlalchemy.dialects.postgresql as pg

    class _Col:
        def __init__(self, name):
            self.name = name

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("report_date"),
            _Col("metric_name"),
            _Col("metric_value"),
            _Col("currency"),
            _Col("period_type"),
            _Col("source"),
            _Col("as_of"),
            _Col("metric_definition"),
        ]

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())
    monkeypatch.setattr(pg, "insert", lambda table: _Stmt())

    rows = [
        {
            "symbol": "AAPL",
            "report_date": "2025-12-31",
            "metric_name": "book_value",
            "metric_value": 10.0,
            "currency": "USD",
            "period_type": "quarterly",
            "source": "alpha_vantage",
            "as_of": "2026-02-14",
            "metric_definition": "provider_reported",
        }
    ]
    out = load_mod.load_financial_observations(rows, dry_run=False)
    assert out == 1
    assert executed["called"] is True
    assert executed["constraint"] == "uniq_financial_observation"


def test_load_financial_observations_accepts_large_in_range_values(monkeypatch):
    captured = {}

    class _FakeConn:
        def execute(self, stmt):
            captured["stmt"] = stmt

    class _Ctx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    class _Excluded:
        metric_value = "mv"
        currency = "ccy"
        period_type = "period"
        source = "src"
        as_of = "as_of"
        metric_definition = "defn"

    class _Stmt:
        excluded = _Excluded()

        def values(self, records):
            captured["records"] = records
            return self

        def on_conflict_do_update(self, constraint, set_, where=None):
            _ = (constraint, set_, where)
            return "UPSERT_STMT"

    class _Type:
        precision = 24
        scale = 6

    class _Col:
        def __init__(self, name):
            self.name = name
            self.type = _Type() if name == "metric_value" else None

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("report_date"),
            _Col("metric_name"),
            _Col("metric_value"),
            _Col("currency"),
            _Col("period_type"),
            _Col("source"),
            _Col("as_of"),
            _Col("metric_definition"),
        ]

    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))
    import sqlalchemy
    import sqlalchemy.dialects.postgresql as pg

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())
    monkeypatch.setattr(pg, "insert", lambda table: _Stmt())

    rows = [
        {
            "symbol": "BIG",
            "report_date": "2025-12-31",
            "metric_name": "shares_outstanding",
            "metric_value": "1234567890123.123456",
            "currency": "USD",
            "period_type": "quarterly",
            "source": "alpha_vantage",
            "as_of": "2026-02-14",
            "metric_definition": "provider_reported",
        }
    ]

    assert load_mod.load_financial_observations(rows, dry_run=False) == 1
    assert captured["records"][0]["metric_value"] == Decimal("1234567890123.123456")


def test_load_financial_observations_skips_out_of_range_values(monkeypatch, caplog):
    class _Type:
        precision = 24
        scale = 6

    class _Col:
        def __init__(self, name):
            self.name = name
            self.type = _Type() if name == "metric_value" else None

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("report_date"),
            _Col("metric_name"),
            _Col("metric_value"),
            _Col("currency"),
            _Col("period_type"),
            _Col("source"),
            _Col("as_of"),
            _Col("metric_definition"),
        ]

    class _Engine:
        def begin(self):
            raise AssertionError("should not hit DB execute when all rows are out of range")

    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))
    import sqlalchemy

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())

    stats = {}
    rows = [
        {
            "symbol": "BIG",
            "report_date": "2025-12-31",
            "metric_name": "shares_outstanding",
            "metric_value": "1000000000000000000.000001",
            "currency": "USD",
            "period_type": "quarterly",
            "source": "alpha_vantage",
            "as_of": "2026-02-14",
            "metric_definition": "provider_reported",
        }
    ]

    with caplog.at_level("WARNING"):
        assert load_mod.load_financial_observations(rows, dry_run=False, stats_out=stats) == 0

    assert stats == {"attempted": 1, "inserted": 0, "updated": 0, "invalid": 1}
    assert "Skipped 1 out-of-range financial observation rows for metric_value." in caplog.text
    assert "shares_outstanding x1" in caplog.text


def test_load_curated_reports_idempotency_stats_on_repeat_runs(monkeypatch):
    class _FakeConn:
        def execute(self, stmt):
            _ = stmt
            return None

    class _Ctx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    class _Excluded:
        factor_value = "fv"
        source = "src"
        metric_frequency = "mf"
        source_report_date = "srd"

    class _Stmt:
        excluded = _Excluded()

        def values(self, records):
            self.records = records
            return self

        def on_conflict_do_update(self, constraint, set_, where=None):
            _ = (constraint, set_, where)
            return self

    monkeypatch.setattr(load_mod, "datetime", type("DT", (), {"now": staticmethod(lambda: "now")}))
    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))
    import sqlalchemy
    import sqlalchemy.dialects.postgresql as pg

    class _Col:
        def __init__(self, name):
            self.name = name

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("observation_date"),
            _Col("factor_name"),
            _Col("factor_value"),
            _Col("source"),
            _Col("metric_frequency"),
            _Col("source_report_date"),
        ]

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())
    monkeypatch.setattr(pg, "insert", lambda table: _Stmt())

    seen = {"n": 0}

    def _fake_count_existing(*args, **kwargs):
        seen["n"] += 1
        return 0 if seen["n"] == 1 else 1

    monkeypatch.setattr(load_mod, "_count_existing_rows", _fake_count_existing)

    rows = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_load",
            "factor_value": 1.0,
            "source": "alpha_vantage",
            "metric_frequency": "daily",
            "source_report_date": "2026-02-14",
        }
    ]
    stats_first = {}
    stats_second = {}
    assert load_curated(rows, dry_run=False, stats_out=stats_first) == 1
    assert load_curated(rows, dry_run=False, stats_out=stats_second) == 1

    assert stats_first["attempted"] == 1
    assert stats_first["inserted"] == 1
    assert stats_first["updated"] == 0
    assert stats_first["invalid"] == 0

    assert stats_second["attempted"] == 1
    assert stats_second["inserted"] == 0
    assert stats_second["updated"] == 1
    assert stats_second["invalid"] == 0


def test_load_curated_stats_counts_invalid_rows(monkeypatch):
    class _Col:
        def __init__(self, name):
            self.name = name

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("observation_date"),
            _Col("factor_name"),
            _Col("factor_value"),
        ]

    class _Engine:
        def begin(self):
            raise AssertionError("should not hit DB execute when no valid rows")

    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))
    import sqlalchemy

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())

    stats = {}
    rows = [
        {
            "symbol": "AAPL",
            "observation_date": "NaT",
            "factor_name": "test_factor_load",
            "factor_value": 1.0,
        }
    ]
    assert load_curated(rows, dry_run=False, stats_out=stats) == 0
    assert stats == {"attempted": 1, "inserted": 0, "updated": 0, "invalid": 1}


def test_load_curated_executes_in_batches(monkeypatch):
    executed_batches = []

    class _FakeConn:
        def execute(self, stmt):
            executed_batches.append(len(stmt.records))
            return None

    class _Ctx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    class _Excluded:
        factor_value = "fv"
        source = "src"
        metric_frequency = "mf"
        source_report_date = "srd"

    class _Stmt:
        excluded = _Excluded()

        def values(self, records):
            self.records = records
            return self

        def on_conflict_do_update(self, constraint, set_, where=None):
            _ = (constraint, set_, where)
            return self

    class _Col:
        def __init__(self, name):
            self.name = name

    class _FakeTable:
        columns = [
            _Col("symbol"),
            _Col("observation_date"),
            _Col("factor_name"),
            _Col("factor_value"),
            _Col("source"),
            _Col("metric_frequency"),
            _Col("source_report_date"),
        ]

    monkeypatch.setattr(load_mod, "datetime", type("DT", (), {"now": staticmethod(lambda: "now")}))
    monkeypatch.setitem(__import__("sys").modules, "pandas", __import__("pandas"))
    import sqlalchemy
    import sqlalchemy.dialects.postgresql as pg

    monkeypatch.setattr(load_mod, "get_db_engine", lambda: _Engine())
    monkeypatch.setattr(sqlalchemy, "MetaData", lambda: object())
    monkeypatch.setattr(sqlalchemy, "Table", lambda *args, **kwargs: _FakeTable())
    monkeypatch.setattr(pg, "insert", lambda table: _Stmt())

    rows = [
        {
            "symbol": f"SYM{i}",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_load",
            "factor_value": float(i),
            "source": "alpha_vantage",
            "metric_frequency": "daily",
            "source_report_date": "2026-02-14",
        }
        for i in range(5)
    ]

    assert load_curated(rows, dry_run=False, batch_size=2) == 5
    assert executed_batches == [2, 2, 1]
