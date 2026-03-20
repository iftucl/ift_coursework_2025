from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"


def _load_script(name: str):
    path = SCRIPTS_ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"cw1_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(f"cw1_{name}", module)
    spec.loader.exec_module(module)
    return module


run_pipeline_and_index = _load_script("run_pipeline_and_index")
run_scheduled_pipeline = _load_script("run_scheduled_pipeline")
search_news = _load_script("search_news")
manage_universe_overrides = _load_script("manage_universe_overrides")
seed_universe_from_sqlite = _load_script("seed_universe_from_sqlite")
validate_pipeline_data = _load_script("validate_pipeline_data")
index_news_to_mongo = _load_script("index_news_to_mongo")
init_db = _load_script("init_db")


class _Parser:
    def __init__(self, args):
        self._args = args

    def parse_args(self):
        return self._args


class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, _spec):
        return self

    def limit(self, n):
        return self._rows[:n]


class _Collection:
    def __init__(self, rows):
        self._rows = rows

    def find(self, query, projection):  # noqa: ARG002
        return _Cursor(self._rows)


class _MongoClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _ContextConn:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        return self

    def fetchall(self):
        return self.rows


class _Engine:
    def __init__(self, rows=None):
        self.conn = _ContextConn(rows=rows)

    def connect(self):
        return self.conn

    def begin(self):
        return self.conn


class _BulkResult:
    upserted_count = 1
    matched_count = 0
    modified_count = 0


class _BulkCollection:
    def __init__(self):
        self.calls = []

    def bulk_write(self, ops, ordered=False):  # noqa: ARG002
        self.calls.append(list(ops))
        return _BulkResult()


class _RowResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


def test_run_pipeline_and_index_builds_main_command():
    args = SimpleNamespace(
        run_date="2026-03-18",
        frequency="daily",
        config="config/conf.yaml",
        backfill_years=5,
        company_limit=10,
        enabled_extractors="source_a,source_b",
        dry_run=True,
        index_mongo=False,
    )
    cmd = run_pipeline_and_index._build_main_cmd(args, PROJECT_ROOT)
    assert "--run-date" in cmd
    assert "--config" in cmd
    assert "--backfill-years" in cmd
    assert "--company-limit" in cmd
    assert "--enabled-extractors" in cmd
    assert "--dry-run" in cmd
    assert "--no-index-mongo" in cmd


def test_run_pipeline_and_index_main_success(monkeypatch, capsys):
    args = SimpleNamespace(
        run_date="2026-03-18",
        frequency="daily",
        config="config/conf.yaml",
        backfill_years=None,
        company_limit=None,
        enabled_extractors="",
        dry_run=False,
        index_mongo=True,
    )
    calls = []

    monkeypatch.setattr(run_pipeline_and_index, "build_parser", lambda: _Parser(args))
    monkeypatch.setattr(run_pipeline_and_index, "load_dotenv_if_exists", lambda _p: None)
    monkeypatch.setattr(run_pipeline_and_index, "PROJECT_ROOT", PROJECT_ROOT)
    monkeypatch.setattr(
        run_pipeline_and_index.subprocess,
        "run",
        lambda cmd, check=False: calls.append((cmd, check)) or SimpleNamespace(returncode=0),
    )

    assert run_pipeline_and_index.main() == 0
    out = capsys.readouterr().out
    assert "[orchestrator] main command:" in out
    assert "mongo indexing handled by Main.py" in out
    assert calls and calls[0][1] is False


def test_run_pipeline_and_index_main_failure(monkeypatch, capsys):
    args = SimpleNamespace(
        run_date="2026-03-18",
        frequency="daily",
        config="config/conf.yaml",
        backfill_years=None,
        company_limit=None,
        enabled_extractors="",
        dry_run=False,
        index_mongo=False,
    )
    monkeypatch.setattr(run_pipeline_and_index, "build_parser", lambda: _Parser(args))
    monkeypatch.setattr(run_pipeline_and_index, "load_dotenv_if_exists", lambda _p: None)
    monkeypatch.setattr(run_pipeline_and_index, "PROJECT_ROOT", PROJECT_ROOT)
    monkeypatch.setattr(
        run_pipeline_and_index.subprocess,
        "run",
        lambda cmd, check=False: SimpleNamespace(returncode=7),  # noqa: ARG005
    )

    assert run_pipeline_and_index.main() == 7
    assert "main failed rc=7" in capsys.readouterr().out


def test_run_scheduled_build_run_specs_daily_and_forced():
    run_date = datetime(2026, 3, 18, tzinfo=UTC).date()
    daily_specs = run_scheduled_pipeline._build_run_specs(
        run_date=run_date,
        include_daily=True,
        force_frequencies=None,
    )
    forced_specs = run_scheduled_pipeline._build_run_specs(
        run_date=run_date,
        include_daily=False,
        force_frequencies=["weekly", "monthly"],
    )
    assert [(s.frequency, s.run_date) for s in daily_specs] == [("daily", "2026-03-18")]
    assert [(s.frequency, s.run_date) for s in forced_specs] == [
        ("weekly", "2026-03-18"),
        ("monthly", "2026-03-18"),
    ]


def test_run_scheduled_main_plan_only(monkeypatch, capsys):
    args = SimpleNamespace(
        run_date="2026-03-18",
        only="daily,monthly",
        skip_daily=False,
        backfill_years=2,
        company_limit=5,
        dry_run=False,
        index_mongo=False,
        plan_only=True,
    )
    monkeypatch.setattr(
        run_scheduled_pipeline.argparse.ArgumentParser,
        "parse_args",
        lambda self: args,
    )
    monkeypatch.setattr(run_scheduled_pipeline, "load_dotenv_if_exists", lambda _p: None)

    assert run_scheduled_pipeline.main() == 0
    out = capsys.readouterr().out
    assert "[scheduled] frequency=daily" in out
    assert "[scheduled] frequency=monthly" in out


def test_run_scheduled_main_invalid_frequency(monkeypatch):
    args = SimpleNamespace(
        run_date="2026-03-18",
        only="daily,bad",
        skip_daily=False,
        backfill_years=None,
        company_limit=None,
        dry_run=False,
        index_mongo=True,
        plan_only=False,
    )
    monkeypatch.setattr(
        run_scheduled_pipeline.argparse.ArgumentParser,
        "parse_args",
        lambda self: args,
    )
    monkeypatch.setattr(run_scheduled_pipeline, "load_dotenv_if_exists", lambda _p: None)
    with pytest.raises(SystemExit, match="Unsupported frequencies"):
        run_scheduled_pipeline.main()


def test_search_news_parses_date_bounds():
    floor = search_news._parse_date_floor("2026-03-18")
    ceil = search_news._parse_date_ceil_exclusive("2026-03-18")
    assert floor.isoformat() == "2026-03-18T00:00:00+00:00"
    assert ceil.isoformat() == "2026-03-19T00:00:00+00:00"


def test_search_news_main_outputs_rows(monkeypatch, capsys):
    args = SimpleNamespace(
        config="config/conf.yaml",
        collection="news_articles",
        q="earnings",
        symbol="aapl",
        ticker="",
        from_date="2026-03-01",
        to_date="2026-03-18",
        limit=3,
        mongo_db="ift_cw",
    )
    rows = [
        {
            "title": "Headline",
            "summary": "Summary",
            "url": "https://example.com",
            "time_published": datetime(2026, 3, 18, tzinfo=UTC),
            "source": "av",
            "symbols": ["AAPL"],
        }
    ]
    client = _MongoClient()
    monkeypatch.setattr(search_news, "build_parser", lambda: _Parser(args))
    monkeypatch.setattr(search_news, "load_dotenv_if_exists", lambda _p: None)
    monkeypatch.setattr(
        search_news,
        "load_mongo_cfg",
        lambda config, root: {"db": "ift_cw"},  # noqa: ARG005
    )
    monkeypatch.setattr(
        search_news,
        "resolve_mongo_db",
        lambda mongo_db, cfg: mongo_db or cfg["db"],
    )
    monkeypatch.setattr(
        search_news,
        "build_mongo_collection",
        lambda mongo_cfg, collection, mongo_db: (client, _Collection(rows)),  # noqa: ARG005
    )

    assert search_news.main() == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0] == '{"count": 1}'
    assert '"AAPL"' in out[1]
    assert client.closed is True


def test_manage_universe_overrides_main_paths(monkeypatch, capsys):
    monkeypatch.setattr(
        manage_universe_overrides.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            cmd="set",
            symbol=" aapl ",
            action="include",
            is_active="true",
            reason="manual include",
        ),
    )
    recorded = {}
    monkeypatch.setattr(
        manage_universe_overrides,
        "_upsert",
        lambda symbol, action, is_active, reason: recorded.update(
            {
                "symbol": symbol,
                "action": action,
                "is_active": is_active,
                "reason": reason,
            }
        ),
    )
    assert manage_universe_overrides.main() == 0
    assert recorded == {
        "symbol": "AAPL",
        "action": "include",
        "is_active": True,
        "reason": "manual include",
    }
    assert "Override saved: symbol=AAPL" in capsys.readouterr().out


def test_manage_universe_overrides_remove_and_list(monkeypatch, capsys):
    monkeypatch.setattr(
        manage_universe_overrides.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(cmd="remove", symbol="msft"),
    )
    removed = []
    monkeypatch.setattr(manage_universe_overrides, "_remove", lambda symbol: removed.append(symbol))
    assert manage_universe_overrides.main() == 0
    assert removed == ["MSFT"]
    assert "Override removed: symbol=MSFT" in capsys.readouterr().out

    monkeypatch.setattr(
        manage_universe_overrides.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(cmd="list", active_only=True),
    )
    called = []
    monkeypatch.setattr(
        manage_universe_overrides, "_list_rows", lambda active_only: called.append(active_only)
    )
    assert manage_universe_overrides.main() == 0
    assert called == [True]


def test_manage_universe_override_helpers(monkeypatch, capsys):
    engine = _Engine(
        rows=[
            (
                "AAPL",
                "include",
                True,
                "manual",
                datetime(2026, 3, 18, tzinfo=UTC),
            )
        ]
    )
    monkeypatch.setattr(manage_universe_overrides, "get_db_engine", lambda: engine)

    manage_universe_overrides._ensure_table()
    assert len(engine.conn.executed) == 2

    engine.conn.executed.clear()
    manage_universe_overrides._upsert("AAPL", "include", True, "manual")
    assert len(engine.conn.executed) == 3

    engine.conn.executed.clear()
    manage_universe_overrides._remove("AAPL")
    assert len(engine.conn.executed) == 3

    manage_universe_overrides._list_rows(active_only=False)
    out = capsys.readouterr().out
    assert "symbol\taction\tis_active\treason\tupdated_at" in out
    assert "AAPL\tinclude\tTrue\tmanual" in out


def test_seed_universe_loads_sqlite_and_main(monkeypatch, tmp_path, capsys):
    sqlite_path = tmp_path / "Equity.db"
    with sqlite3.connect(sqlite_path) as con:
        con.execute(
            """
            CREATE TABLE equity_static (
                symbol TEXT,
                security TEXT,
                gics_sector TEXT,
                gics_industry TEXT,
                country TEXT,
                region TEXT
            )
            """
        )
        con.executemany(
            "INSERT INTO equity_static VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("AAPL", "Apple", "Tech", "Hardware", "US", "NA"),
                ("AAPL", "Apple", "Tech", "Hardware", "US", "NA"),
                ("", "Bad", "Tech", "Hardware", "US", "NA"),
                (None, "Bad", "Tech", "Hardware", "US", "NA"),
                ("MSFT", "Microsoft", "Tech", "Software", "US", "NA"),
            ],
        )
        con.commit()

    df = seed_universe_from_sqlite.load_equity_static(sqlite_path)
    assert list(df["symbol"]) == ["AAPL", "MSFT"]

    monkeypatch.setattr(seed_universe_from_sqlite, "load_dotenv_if_exists", lambda _p: None)
    monkeypatch.setattr(
        seed_universe_from_sqlite,
        "parse_args",
        lambda: SimpleNamespace(sqlite_path=str(sqlite_path)),
    )
    monkeypatch.setattr(seed_universe_from_sqlite, "seed_company_static", lambda frame: len(frame))
    assert seed_universe_from_sqlite.main() == 0
    assert "inserted 2 rows" in capsys.readouterr().out


def test_seed_company_static_executes_setup_and_to_sql(monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(seed_universe_from_sqlite, "get_db_engine", lambda: engine)

    to_sql_calls = []

    def _to_sql(self, name, con, schema, if_exists, index, method, chunksize):
        to_sql_calls.append(
            {
                "name": name,
                "schema": schema,
                "if_exists": if_exists,
                "index": index,
                "method": method,
                "chunksize": chunksize,
            }
        )

    monkeypatch.setattr(pd.DataFrame, "to_sql", _to_sql, raising=False)
    df = pd.DataFrame(
        [{"symbol": "AAPL", "security": "Apple", "gics_sector": "Tech"}]
    )
    rows = seed_universe_from_sqlite.seed_company_static(df)
    assert rows == 1
    assert len(engine.conn.executed) == 3
    assert to_sql_calls[0]["name"] == "company_static"
    assert to_sql_calls[0]["schema"] == "systematic_equity"


def test_validate_pipeline_data_helpers_and_main(monkeypatch, capsys):
    factors = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "observation_date": datetime(2026, 3, 1),
                "factor_name": "sentiment_30d_avg",
                "factor_value": 0.1,
                "source": "extractor_b",
                "metric_frequency": "daily",
            },
            {
                "symbol": "AAPL",
                "observation_date": datetime(2026, 3, 2),
                "factor_name": "article_count_30d",
                "factor_value": 2.0,
                "source": "extractor_b",
                "metric_frequency": "daily",
            },
        ]
    )
    normalized = validate_pipeline_data._normalize_date_column(factors.copy(), "observation_date")
    assert str(normalized["observation_date"].iloc[0]) == "2026-03-01"

    coverage = validate_pipeline_data._validate_daily_symbol_coverage(
        normalized,
        start_date=datetime(2026, 3, 1).date(),
        end_date=datetime(2026, 3, 2).date(),
        coverage_factors={"sentiment_30d_avg", "article_count_30d"},
    )
    assert coverage["coverage_expected_rows"] == 4
    assert coverage["coverage_missing_rows"] == 2

    args = SimpleNamespace(
        tolerance=1e-6,
        daily_return_sanity_threshold=1.0,
        start_date=None,
        end_date=None,
        coverage_factors="sentiment_30d_avg,article_count_30d",
    )
    monkeypatch.setattr(validate_pipeline_data, "parse_args", lambda: args)
    monkeypatch.setattr(validate_pipeline_data, "_load_latest_run_id", lambda: "run-1")
    monkeypatch.setattr(
        validate_pipeline_data,
        "_validate_daily_return",
        lambda tol: (10, 0.0),  # noqa: ARG005
    )
    monkeypatch.setattr(
        validate_pipeline_data,
        "_validate_debt_to_equity",
        lambda tol: (8, 0.0),  # noqa: ARG005
    )
    monkeypatch.setattr(validate_pipeline_data, "_load_factor_observations", lambda: normalized)
    monkeypatch.setattr(
        validate_pipeline_data,
        "_validate_common_quality",
        lambda factors, daily_return_sanity_threshold: (  # noqa: ARG005
            {
                "checked_rows": 2,
                "duplicate_key_rows": 0,
                "missing_required_rows": 0,
                "non_finite_value_rows": 0,
                "invalid_frequency_rows": 0,
                "invalid_source_rows": 0,
                "unexpected_daily_return_null_rows": 0,
                "news_sentiment_null_rows": 0,
                "news_count_null_rows": 0,
                "news_count_negative_rows": 0,
                "sentiment_30d_null_rows": 0,
            },
            {"daily_return_extreme_rows": 0, "expected_daily_return_null_rows": 0},
        ),
    )

    assert validate_pipeline_data.main() == 0
    out = capsys.readouterr().out
    assert "latest_run_id=run-1" in out
    assert "validation_status=PASS" in out


def test_validate_common_quality_and_recompute_helpers(monkeypatch):
    factors = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-01",
                "factor_name": "adjusted_close_price",
                "factor_value": 100.0,
                "source": "alpha_vantage",
                "metric_frequency": "daily",
            },
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-02",
                "factor_name": "adjusted_close_price",
                "factor_value": 110.0,
                "source": "alpha_vantage",
                "metric_frequency": "daily",
            },
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-02",
                "factor_name": "daily_return",
                "factor_value": 0.0953101798,
                "source": "alpha_vantage",
                "metric_frequency": "daily",
            },
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-01",
                "factor_name": "daily_return",
                "factor_value": None,
                "source": "alpha_vantage",
                "metric_frequency": "daily",
            },
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-02",
                "factor_name": "news_sentiment_daily",
                "factor_value": 0.2,
                "source": "extractor_b",
                "metric_frequency": "daily",
            },
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-02",
                "factor_name": "news_article_count_daily",
                "factor_value": 3.0,
                "source": "extractor_b",
                "metric_frequency": "daily",
            },
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-02",
                "factor_name": "sentiment_30d_avg",
                "factor_value": 0.2,
                "source": "extractor_b",
                "metric_frequency": "daily",
            },
        ]
    )
    factors = validate_pipeline_data._normalize_date_column(factors, "observation_date")
    hard_fail_counts, warning_counts = validate_pipeline_data._validate_common_quality(
        factors,
        daily_return_sanity_threshold=1.0,
    )
    assert hard_fail_counts["missing_required_rows"] == 0
    assert hard_fail_counts["unexpected_daily_return_null_rows"] == 0
    assert warning_counts["expected_daily_return_null_rows"] == 1

    price_df = factors[
        ["symbol", "observation_date", "factor_name", "factor_value"]
    ].copy()
    atomics = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "report_date": "2026-03-01",
                "metric_name": "total_debt",
                "metric_value": 50.0,
            },
            {
                "symbol": "AAPL",
                "report_date": "2026-03-01",
                "metric_name": "total_shareholder_equity",
                "metric_value": 25.0,
            },
        ]
    )
    dte_df = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-02",
                "factor_value": 2.0,
            }
        ]
    )
    monkeypatch.setattr(validate_pipeline_data, "get_db_engine", lambda: _Engine())
    read_sql_calls = []

    def _read_sql(_query, _conn):
        read_sql_calls.append(True)
        if len(read_sql_calls) == 1:
            return price_df.copy()
        if len(read_sql_calls) == 2:
            return atomics.copy()
        return dte_df.copy()

    monkeypatch.setattr(validate_pipeline_data.pd, "read_sql", _read_sql)
    checked_rows, max_abs_err = validate_pipeline_data._validate_daily_return(1e-6)
    assert checked_rows == 1
    assert max_abs_err < 1e-10

    checked_rows, max_abs_err = validate_pipeline_data._validate_debt_to_equity(1e-6)
    assert checked_rows == 1
    assert max_abs_err == pytest.approx(0.0)


def test_validate_recompute_helpers_raise_on_large_error(monkeypatch):
    monkeypatch.setattr(validate_pipeline_data, "get_db_engine", lambda: _Engine())

    price_df = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-01",
                "factor_name": "adjusted_close_price",
                "factor_value": 100.0,
            },
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-02",
                "factor_name": "adjusted_close_price",
                "factor_value": 110.0,
            },
            {
                "symbol": "AAPL",
                "observation_date": "2026-03-02",
                "factor_name": "daily_return",
                "factor_value": 0.5,
            },
        ]
    )
    atomics = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "report_date": "2026-03-01",
                "metric_name": "total_debt",
                "metric_value": 50.0,
            },
            {
                "symbol": "AAPL",
                "report_date": "2026-03-01",
                "metric_name": "total_shareholder_equity",
                "metric_value": 25.0,
            },
        ]
    )
    dte_df = pd.DataFrame(
        [{"symbol": "AAPL", "observation_date": "2026-03-02", "factor_value": 1.0}]
    )

    read_sql_calls = []

    def _read_sql(_query, _conn):
        read_sql_calls.append(True)
        if len(read_sql_calls) == 1:
            return price_df.copy()
        if len(read_sql_calls) == 2:
            return atomics.copy()
        return dte_df.copy()

    monkeypatch.setattr(validate_pipeline_data.pd, "read_sql", _read_sql)

    with pytest.raises(AssertionError, match="daily_return check failed"):
        validate_pipeline_data._validate_daily_return(1e-6)

    read_sql_calls.clear()
    dte_df.loc[0, "factor_value"] = 3.0

    def _read_sql_dte(_query, _conn):
        read_sql_calls.append(True)
        if len(read_sql_calls) == 1:
            return atomics.copy()
        return dte_df.copy()

    monkeypatch.setattr(validate_pipeline_data.pd, "read_sql", _read_sql_dte)
    with pytest.raises(AssertionError, match="debt_to_equity check failed"):
        validate_pipeline_data._validate_debt_to_equity(1e-6)


def test_validate_main_raises_for_invalid_dates_and_failures(monkeypatch):
    args = SimpleNamespace(
        tolerance=1e-6,
        daily_return_sanity_threshold=1.0,
        start_date="2026-03-03",
        end_date=None,
        coverage_factors="sentiment_30d_avg",
    )
    monkeypatch.setattr(validate_pipeline_data, "parse_args", lambda: args)
    with pytest.raises(ValueError, match="must be provided together"):
        validate_pipeline_data.main()

    args = SimpleNamespace(
        tolerance=1e-6,
        daily_return_sanity_threshold=1.0,
        start_date="2026-03-03",
        end_date="2026-03-01",
        coverage_factors="sentiment_30d_avg",
    )
    monkeypatch.setattr(validate_pipeline_data, "parse_args", lambda: args)
    with pytest.raises(ValueError, match="must be <= --end-date"):
        validate_pipeline_data.main()

    args = SimpleNamespace(
        tolerance=1e-6,
        daily_return_sanity_threshold=1.0,
        start_date="2026-03-01",
        end_date="2026-03-02",
        coverage_factors="sentiment_30d_avg",
    )
    monkeypatch.setattr(validate_pipeline_data, "parse_args", lambda: args)
    monkeypatch.setattr(validate_pipeline_data, "_load_latest_run_id", lambda: "run-2")
    monkeypatch.setattr(validate_pipeline_data, "_validate_daily_return", lambda tol: (1, 0.0))
    monkeypatch.setattr(validate_pipeline_data, "_validate_debt_to_equity", lambda tol: (1, 0.0))
    monkeypatch.setattr(validate_pipeline_data, "_load_factor_observations", lambda: pd.DataFrame())
    monkeypatch.setattr(
        validate_pipeline_data,
        "_validate_common_quality",
        lambda factors, daily_return_sanity_threshold: (  # noqa: ARG005
            {
                "checked_rows": 0,
                "duplicate_key_rows": 1,
                "missing_required_rows": 0,
                "non_finite_value_rows": 0,
                "invalid_frequency_rows": 0,
                "invalid_source_rows": 0,
                "unexpected_daily_return_null_rows": 0,
                "news_sentiment_null_rows": 0,
                "news_count_null_rows": 0,
                "news_count_negative_rows": 0,
                "sentiment_30d_null_rows": 0,
            },
            {"daily_return_extreme_rows": 0, "expected_daily_return_null_rows": 0},
        ),
    )
    with pytest.raises(AssertionError, match="common quality checks failed"):
        validate_pipeline_data.main()

    monkeypatch.setattr(
        validate_pipeline_data,
        "_validate_common_quality",
        lambda factors, daily_return_sanity_threshold: (  # noqa: ARG005
            {
                "checked_rows": 0,
                "duplicate_key_rows": 0,
                "missing_required_rows": 0,
                "non_finite_value_rows": 0,
                "invalid_frequency_rows": 0,
                "invalid_source_rows": 0,
                "unexpected_daily_return_null_rows": 0,
                "news_sentiment_null_rows": 0,
                "news_count_null_rows": 0,
                "news_count_negative_rows": 0,
                "sentiment_30d_null_rows": 0,
            },
            {"daily_return_extreme_rows": 0, "expected_daily_return_null_rows": 0},
        ),
    )
    monkeypatch.setattr(
        validate_pipeline_data,
        "_validate_daily_symbol_coverage",
        lambda factors, start_date, end_date, coverage_factors: {  # noqa: ARG005
            "coverage_expected_rows": 4,
            "coverage_missing_rows": 2,
        },
    )
    with pytest.raises(AssertionError, match="coverage check failed"):
        validate_pipeline_data.main()


def test_index_news_processes_minio_rows():
    class _Obj:
        object_name = "raw/source_b/news/run_date=2026-03-18/symbol=AAPL.jsonl"

    class _Response:
        def __init__(self, payload):
            self._payload = payload
            self.closed = False
            self.released = False

        def stream(self, amt):  # noqa: ARG002
            yield self._payload

        def close(self):
            self.closed = True

        def release_conn(self):
            self.released = True

    class _Minio:
        def __init__(self, response):
            self.response = response

        def list_objects(self, bucket, prefix, recursive=True):  # noqa: ARG002
            return [_Obj()]

        def get_object(self, bucket, object_name):  # noqa: ARG002
            return self.response

    payload = (
        b'{"title":"Headline","summary":"Summary text long enough for language inference",'
        b'"url":"https://example.com","source":"av","time_published":"20260318T010203",'
        b'"ticker_hits":[{"ticker":"MSFT"}],"topics":[{"topic":"Tech"}]}\n'
    )
    response = _Response(payload)
    coll = _BulkCollection()
    stats = index_news_to_mongo.index_news(
        coll=coll,
        minio_client=_Minio(response),
        bucket="bucket",
        prefix="raw/source_b/news/",
        batch_size=1,
        symbol_filter=set(),
        since_dt=None,
        until_dt=None,
        dry_run=False,
        run_date="2026-03-18",
    )
    assert stats["objects_scanned"] == 1
    assert stats["articles_seen"] == 1
    assert stats["ops_submitted"] == 1
    assert stats["docs_upserted"] == 1
    assert len(coll.calls) == 1
    assert response.closed is True
    assert response.released is True


def test_index_news_filters_rows_by_time():
    class _Obj:
        object_name = "raw/source_b/news/run_date=2026-03-18/symbol=AAPL.jsonl"

    class _Response:
        def stream(self, amt):  # noqa: ARG002
            yield (
                b'{"title":"Headline","summary":"Summary",'
                b'"source":"av","time_published":"20260318T010203"}\n'
            )

        def close(self):
            return None

        def release_conn(self):
            return None

    class _Minio:
        def list_objects(self, bucket, prefix, recursive=True):  # noqa: ARG002
            return [_Obj()]

        def get_object(self, bucket, object_name):  # noqa: ARG002
            return _Response()

    stats = index_news_to_mongo.index_news(
        coll=_BulkCollection(),
        minio_client=_Minio(),
        bucket="bucket",
        prefix="raw/source_b/news/",
        batch_size=10,
        symbol_filter={"AAPL"},
        since_dt=datetime(2026, 3, 18, 2, 0, 0, tzinfo=UTC),
        until_dt=None,
        dry_run=True,
        run_date="2026-03-18",
    )
    assert stats["articles_seen"] == 1
    assert stats["articles_filtered_by_time"] == 1
    assert stats["ops_submitted"] == 0


def test_index_news_to_mongo_helpers_and_main(monkeypatch, capsys):
    assert index_news_to_mongo._build_query_prefix("raw/source_b/news", "2026-03-18") == (
        "raw/source_b/news/run_date=2026-03-18/"
    )
    assert index_news_to_mongo._parse_symbol_from_object_name(
        "raw/source_b/news/run_date=2026-03-18/symbol=AAPL.jsonl"
    ) == "AAPL"
    assert index_news_to_mongo._parse_run_date_from_object_name(
        "raw/source_b/news/run_date=2026-03-18/symbol=AAPL.jsonl"
    ) == "2026-03-18"
    assert index_news_to_mongo._extract_topics([{"topic": "Tech"}, "tech", "Finance"]) == [
        "tech",
        "finance",
    ]
    assert index_news_to_mongo._extract_symbols(
        {"ticker_hits": [{"ticker": "msft"}], "ticker": "aapl"},
        object_symbol="AAPL",
    ) == ["AAPL", "MSFT"]
    assert index_news_to_mongo._truncate_text("abcdef", 4) == "abcd"

    args = SimpleNamespace(
        config="config/conf.yaml",
        collection="news_articles",
        run_date="2026-03-18",
        symbol=["AAPL"],
        since="",
        until="",
        batch_size=500,
        prefix="raw/source_b/news/",
        skip_indexes=False,
        dry_run=False,
        log_level="INFO",
        mongo_db="ift_cw",
    )
    client = _MongoClient()
    monkeypatch.setattr(index_news_to_mongo, "build_parser", lambda: _Parser(args))
    monkeypatch.setattr(index_news_to_mongo, "load_dotenv_if_exists", lambda _p: None)
    monkeypatch.setattr(index_news_to_mongo, "_configure_logging", lambda level: None)
    monkeypatch.setattr(
        index_news_to_mongo,
        "_resolve_config",
        lambda path: ({}, {"db": "ift_cw"}),  # noqa: ARG005
    )
    monkeypatch.setattr(
        index_news_to_mongo,
        "_build_minio_client",
        lambda cfg: (object(), "bucket"),  # noqa: ARG005
    )
    monkeypatch.setattr(
        index_news_to_mongo,
        "resolve_mongo_db",
        lambda mongo_db, cfg: mongo_db or cfg["db"],
    )
    monkeypatch.setattr(
        index_news_to_mongo,
        "build_mongo_collection",
        lambda mongo_cfg, collection, mongo_db: (client, object()),  # noqa: ARG005
    )
    ensure_calls = []
    monkeypatch.setattr(
        index_news_to_mongo,
        "_ensure_indexes",
        lambda coll: ensure_calls.append(coll),
    )
    monkeypatch.setattr(
        index_news_to_mongo,
        "index_news",
        lambda **kwargs: {  # noqa: ARG005
            "objects_scanned": 1,
            "articles_seen": 2,
            "articles_filtered_by_time": 0,
            "ops_submitted": 2,
            "bulk_calls": 1,
            "docs_upserted": 2,
            "docs_matched": 0,
            "docs_modified": 0,
        },
    )

    assert index_news_to_mongo.main() == 0
    out = capsys.readouterr().out
    assert '"mongo_db": "ift_cw"' in out
    assert ensure_calls
    assert client.closed is True


def test_index_news_to_mongo_minio_helpers_and_language_paths(monkeypatch):
    monkeypatch.setattr(index_news_to_mongo, "_LANGID_AVAILABLE", False)
    assert index_news_to_mongo._infer_language("x" * 40) == (None, None)

    monkeypatch.setattr(index_news_to_mongo, "_LANGID_AVAILABLE", True)
    monkeypatch.setattr(
        index_news_to_mongo,
        "langid",
        SimpleNamespace(classify=lambda text: ("en", 0.99)),  # noqa: ARG005
    )
    assert index_news_to_mongo._infer_language("enough text for inference") == ("en", 0.99)

    monkeypatch.setattr(
        index_news_to_mongo,
        "langid",
        SimpleNamespace(classify=lambda text: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    assert index_news_to_mongo._infer_language("enough text for inference") == (None, None)

    assert index_news_to_mongo._parse_time_published("20260318T010203").isoformat() == (
        "2026-03-18T01:02:03+00:00"
    )
    assert index_news_to_mongo._parse_time_published("2026-03-18").isoformat() == (
        "2026-03-18T00:00:00+00:00"
    )
    assert index_news_to_mongo._parse_time_published("") is None
    assert index_news_to_mongo._parse_optional_dt("2026-03-18").isoformat() == (
        "2026-03-18T00:00:00+00:00"
    )

    lines = list(
        index_news_to_mongo._iter_jsonl_rows_stream(
            SimpleNamespace(
                stream=lambda amt: [  # noqa: ARG005
                    b'{"ok": 1}\nnot-json\n{"also": 2}',
                ]
            )
        )
    )
    assert lines == [{"ok": 1}, {"also": 2}]


def test_build_minio_client_and_index_news_edge_paths(monkeypatch):
    with pytest.raises(RuntimeError, match="Missing MinIO config"):
        index_news_to_mongo._build_minio_client({})

    constructed = {}

    def _fake_minio(endpoint, access_key, secret_key, secure):
        constructed.update(
            {
                "endpoint": endpoint,
                "access_key": access_key,
                "secret_key": secret_key,
                "secure": secure,
            }
        )
        return "client"

    monkeypatch.setattr(index_news_to_mongo, "Minio", _fake_minio)
    client, bucket = index_news_to_mongo._build_minio_client(
        {
            "endpoint": "https://minio.example.com",
            "access_key": "ak",
            "secret_key": "sk",
            "bucket": "bucket",
            "secure": "true",
        }
    )
    assert client == "client"
    assert bucket == "bucket"
    assert constructed["endpoint"] == "minio.example.com"
    assert constructed["secure"] is True

    class _Obj:
        def __init__(self, object_name):
            self.object_name = object_name

    class _Response:
        def __init__(self, payload=None, fail=False):
            self.payload = payload or b""
            self.fail = fail
            self.closed = False
            self.released = False

        def stream(self, amt):  # noqa: ARG002
            if self.fail:
                raise RuntimeError("stream boom")
            yield self.payload

        def close(self):
            self.closed = True

        def release_conn(self):
            self.released = True

    class _Minio:
        def __init__(self):
            self.responses = {
                "raw/source_b/news/skip.txt": _Response(),
                "raw/source_b/news/run_date=2026-03-18/symbol=MSFT.jsonl": _Response(
                    (
                        b'{"title":"Ignore","summary":"ignore","source":"av",'
                        b'"time_published":"20260318T010203"}\n'
                    )
                ),
                "raw/source_b/news/run_date=2026-03-18/symbol=AAPL.jsonl": _Response(
                    b'{"title":"Keep","summary":"summary text long enough for inference",'
                    b'"source":"av","time_published":"20260318T010203"}\n',
                ),
                "raw/source_b/news/run_date=2026-03-18/symbol=ERR.jsonl": _Response(
                    fail=True
                ),
            }

        def list_objects(self, bucket, prefix, recursive=True):  # noqa: ARG002
            return [_Obj(name) for name in self.responses]

        def get_object(self, bucket, object_name):  # noqa: ARG002
            return self.responses[object_name]

    coll = _BulkCollection()
    monkeypatch.setattr(index_news_to_mongo, "_infer_language", lambda text: ("en", 0.5))
    stats = index_news_to_mongo.index_news(
        coll=coll,
        minio_client=_Minio(),
        bucket="bucket",
        prefix="raw/source_b/news/",
        batch_size=10,
        symbol_filter={"AAPL", "ERR"},
        since_dt=None,
        until_dt=None,
        dry_run=False,
        run_date="",
    )
    assert stats["objects_scanned"] == 2
    assert stats["articles_seen"] == 1
    assert stats["ops_submitted"] == 1
    assert stats["bulk_calls"] == 1


def test_index_news_to_mongo_main_without_indexes_and_with_warning(monkeypatch, capsys):
    args = SimpleNamespace(
        config="config/conf.yaml",
        collection="news_articles",
        run_date=None,
        symbol=[],
        since="2026-03-01",
        until="2026-03-02",
        batch_size=1,
        prefix="raw/source_b/news/",
        skip_indexes=True,
        dry_run=False,
        log_level="INFO",
        mongo_db="ift_cw",
    )
    client = _MongoClient()
    warnings = []
    monkeypatch.setattr(index_news_to_mongo, "build_parser", lambda: _Parser(args))
    monkeypatch.setattr(index_news_to_mongo, "load_dotenv_if_exists", lambda _p: None)
    monkeypatch.setattr(index_news_to_mongo, "_configure_logging", lambda level: None)
    monkeypatch.setattr(index_news_to_mongo, "_LANGID_AVAILABLE", False)
    monkeypatch.setattr(
        index_news_to_mongo.logger, "warning", lambda msg: warnings.append(msg)
    )
    monkeypatch.setattr(
        index_news_to_mongo,
        "_resolve_config",
        lambda path: ({}, {"db": "ift_cw"}),
    )
    monkeypatch.setattr(
        index_news_to_mongo,
        "_build_minio_client",
        lambda cfg: (object(), "bucket"),
    )
    monkeypatch.setattr(index_news_to_mongo, "resolve_mongo_db", lambda mongo_db, cfg: mongo_db)
    monkeypatch.setattr(
        index_news_to_mongo,
        "build_mongo_collection",
        lambda mongo_cfg, collection, mongo_db: (client, object()),  # noqa: ARG005
    )
    monkeypatch.setattr(
        index_news_to_mongo,
        "_ensure_indexes",
        lambda coll: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    monkeypatch.setattr(
        index_news_to_mongo,
        "index_news",
        lambda **kwargs: {  # noqa: ARG005
            "objects_scanned": 0,
            "articles_seen": 0,
            "articles_filtered_by_time": 0,
            "ops_submitted": 0,
            "bulk_calls": 0,
            "docs_upserted": 0,
            "docs_matched": 0,
            "docs_modified": 0,
        },
    )

    assert index_news_to_mongo.main() == 0
    out = capsys.readouterr().out
    assert '"since": "2026-03-01T00:00:00+00:00"' in out
    assert warnings == ["langid_unavailable language_inference_disabled fallback=unknown"]
    assert client.closed is True


def test_index_news_to_mongo_main_failure(monkeypatch, capsys):
    args = SimpleNamespace(
        config="config/conf.yaml",
        collection="news_articles",
        run_date=None,
        symbol=[],
        since="",
        until="",
        batch_size=500,
        prefix="raw/source_b/news/",
        skip_indexes=True,
        dry_run=True,
        log_level="INFO",
        mongo_db="",
    )
    monkeypatch.setattr(index_news_to_mongo, "build_parser", lambda: _Parser(args))
    monkeypatch.setattr(index_news_to_mongo, "load_dotenv_if_exists", lambda _p: None)
    monkeypatch.setattr(index_news_to_mongo, "_configure_logging", lambda level: None)
    monkeypatch.setattr(
        index_news_to_mongo,
        "_resolve_config",
        lambda path: (_ for _ in ()).throw(RuntimeError("boom")),  # noqa: ARG005
    )

    assert index_news_to_mongo.main() == 1
    assert '"error": "RuntimeError(\'boom\')"' in capsys.readouterr().out


def test_init_db_helpers_and_main(monkeypatch, tmp_path, capsys):
    assert init_db._validate_container_name("postgres_db_cw") == "postgres_db_cw"
    with pytest.raises(ValueError, match="Invalid container name"):
        init_db._validate_container_name("bad name")

    base = init_db._psql_base_cmd("postgres_db_cw", "postgres", "fift")
    createdb = init_db._createdb_cmd("postgres_db_cw", "postgres", "fift")
    assert base[:4] == ["docker", "exec", "-i", "postgres_db_cw"]
    assert createdb[-1] == "fift"

    sql_path = tmp_path / "init.sql"
    sql_path.write_text("SELECT 1;", encoding="utf-8")
    run_calls = []
    monkeypatch.setattr(
        init_db.subprocess,
        "run",
        lambda cmd, **kwargs: run_calls.append((cmd, kwargs)) or SimpleNamespace(stdout=""),
    )
    init_db.run_sql_init("postgres_db_cw", "postgres", "fift", sql_path)
    assert run_calls[0][0][:4] == ["docker", "exec", "-i", "postgres_db_cw"]
    assert run_calls[0][1]["input"] == b"SELECT 1;"

    run_calls.clear()
    monkeypatch.setattr(init_db, "PROJECT_ROOT", PROJECT_ROOT)
    init_db.run_seed(None, PROJECT_ROOT)
    assert "seed_universe_from_sqlite.py" in run_calls[0][0][1]

    args = SimpleNamespace(
        container="postgres_db_cw",
        db_user="postgres",
        admin_db="postgres",
        db_name="fift",
        sqlite_path=None,
    )
    monkeypatch.setattr(init_db, "parse_args", lambda: args)
    monkeypatch.setattr(init_db, "load_dotenv_if_exists", lambda _p: None)
    called = []
    monkeypatch.setattr(
        init_db,
        "ensure_database_exists",
        lambda container, db_user, admin_db, db_name: called.append(
            ("ensure", container, db_user, admin_db, db_name)
        ),
    )
    monkeypatch.setattr(
        init_db,
        "run_sql_init",
        lambda container, db_user, db_name, init_sql_path: called.append(
            ("sql", container, db_user, db_name, init_sql_path.name)
        ),
    )
    monkeypatch.setattr(
        init_db,
        "run_seed",
        lambda sqlite_path, project_root: called.append(("seed", sqlite_path, project_root.name)),
    )
    assert init_db.main() == 0
    assert called[0][0] == "ensure"
    assert called[1][0] == "sql"
    assert called[2][0] == "seed"
    assert "DB init completed" in capsys.readouterr().out
