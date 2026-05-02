from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from modules.transform import cw2_features as cw2_mod


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeExecuteResult:
    def __init__(self, rows=None, *, scalar=None, keys=None):
        self._rows = list(rows or [])
        self._scalar = scalar
        if keys is None and self._rows and isinstance(self._rows[0], dict):
            keys = list(self._rows[0].keys())
        self._keys = list(keys or [])

    def mappings(self):
        return _FakeMappingsResult(self._rows)

    def fetchall(self):
        if self._rows and isinstance(self._rows[0], dict):
            return [tuple(row.get(key) for key in self._keys) for row in self._rows]
        return list(self._rows)

    def keys(self):
        return list(self._keys)

    def scalar(self):
        return self._scalar


class _FakeContext:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False


class _SequenceConnection:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        if not self._responses:
            return _FakeExecuteResult()
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, _FakeExecuteResult):
            return response
        if isinstance(response, dict) and ("rows" in response or "scalar" in response):
            return _FakeExecuteResult(
                response.get("rows"),
                scalar=response.get("scalar"),
                keys=response.get("keys"),
            )
        return _FakeExecuteResult(response)


class _SequenceEngine:
    def __init__(self, responses):
        self.conn = _SequenceConnection(responses)

    def connect(self):
        return _FakeContext(self.conn)

    def begin(self):
        return _FakeContext(self.conn)


class _ArrayValue:
    def __init__(self, value):
        self._value = value

    def item(self):
        return self._value


class _BrokenArrayValue:
    def item(self):
        raise ValueError("bad scalar")


def test_load_company_info_uses_fallback_query_and_default_rows(monkeypatch):
    fallback_engine = _SequenceEngine(
        [
            RuntimeError("company_static unavailable"),
            [
                {
                    "symbol": "AAPL",
                    "security": "Apple Inc",
                    "gics_sector": None,
                    "country": "US",
                }
            ],
        ]
    )
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: fallback_engine)

    df = cw2_mod._load_company_info(["AAPL"])

    assert df.to_dict(orient="records") == [
        {
            "symbol": "AAPL",
            "security": "Apple Inc",
            "gics_sector": "Unknown",
            "country": "US",
        }
    ]

    empty_engine = _SequenceEngine([RuntimeError("boom"), []])
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: empty_engine)

    default_df = cw2_mod._load_company_info(["AAPL", "MSFT"])

    assert default_df.to_dict(orient="records") == [
        {
            "symbol": "AAPL",
            "security": None,
            "gics_sector": "Unknown",
            "country": None,
        },
        {
            "symbol": "MSFT",
            "security": None,
            "gics_sector": "Unknown",
            "country": None,
        },
    ]


def test_macro_history_previous_positions_and_risk_helpers(monkeypatch):
    history_engine = _SequenceEngine(
        [
            [
                {"factor_value": "4.0"},
                {"factor_value": None},
                {"factor_value": "bad"},
                {"factor_value": "4.5"},
            ]
        ]
    )
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: history_engine)
    history = cw2_mod._load_macro_factor_history(
        date(2026, 4, 15),
        "us_treasury_10y",
        lookback_days=5,
    )
    assert history == [4.0, 4.5]
    assert (
        cw2_mod._load_macro_factor_history(
            date(2026, 4, 15),
            "us_treasury_10y",
            lookback_days=0,
        )
        == []
    )

    monkeypatch.setattr(
        cw2_mod,
        "_load_macro_factor_series",
        lambda as_of, factor_name, *, lookback_days: pd.Series(
            [4.0, 4.2] if factor_name == "us_treasury_10y" else [3.5, 3.7],
            index=[date(2026, 4, 14), date(2026, 4, 15)],
        ),
    )
    latest_spread, spread_history = cw2_mod._load_term_spread_context(
        date(2026, 4, 15),
        lookback_days=30,
    )
    assert latest_spread == pytest.approx(0.5)
    assert spread_history == [0.5, 0.5]

    prev_engine = _SequenceEngine(
        [
            [{"prev_as_of_date": date(2026, 3, 31)}],
            [{"symbol": "AAPL", "target_weight": 0.6}],
        ]
    )
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: prev_engine)
    previous_positions = cw2_mod._load_previous_portfolio_positions(
        date(2026, 4, 15),
        portfolio_name="cw2_core_equity",
    )
    assert previous_positions == [{"symbol": "AAPL", "target_weight": 0.6}]

    factor_df = pd.DataFrame(
        [
            {"symbol": "AAPL", "factor_name": "log_market_cap", "factor_value": 25.0},
            {
                "symbol": "AAPL",
                "factor_name": "liquidity_20d",
                "factor_value": 1_000_000.0,
            },
            {"symbol": "MSFT", "factor_name": "log_market_cap", "factor_value": 26.0},
            {"symbol": "_MACRO", "factor_name": "vix_close", "factor_value": 18.0},
        ]
    )
    risk_df = cw2_mod._extract_risk_data(
        factor_df,
        config={
            "risk_overlay": {
                "optional_percentile_blacklists": [{"column": "garch_vol_60d"}]
            }
        },
    )
    assert list(risk_df.columns) == [
        "symbol",
        "log_market_cap",
        "liquidity_20d",
        "volatility_60d",
        "garch_vol_60d",
    ]
    assert risk_df.loc[risk_df["symbol"] == "MSFT", "garch_vol_60d"].iloc[0] is None

    scoring_symbols = cw2_mod._factor_scoring_symbols(
        [
            {"symbol": "AAPL", "pass_country": True, "log_market_cap": 25.0},
            {"symbol": "MSFT", "pass_country": False, "log_market_cap": 30.0},
            {"symbol": "TSLA", "pass_country": True, "log_market_cap": 10.0},
        ],
        {"investable_universe": {"min_market_cap_log": 20.0}},
    )
    assert scoring_symbols == {"AAPL"}


def test_covariance_context_and_factor_helpers(monkeypatch):
    config = {
        "portfolio_construction": {
            "weighting": "mean_variance",
            "covariance": {
                "lookback_days": 120,
                "min_history_days": 60,
                "shrinkage_intensity": 0.3,
                "max_forward_fill_days": 3,
            },
        },
        "backtest": {"benchmark_ticker": "QQQ"},
    }

    from team_Pearson.coursework_two.modules.backtest import data_loader

    captured = {}

    def fake_build_context(engine, as_of_arg, symbols_arg, config_arg):
        captured["engine"] = engine
        captured["as_of_date"] = as_of_arg
        captured["symbols"] = symbols_arg
        captured["config"] = config_arg
        return (
            pd.DataFrame([[0.05]], index=["AAPL"], columns=["AAPL"]),
            {
                "covariance_method": "fundamental_factor",
                "requested_covariance_method": "fundamental_factor",
                "lookback_days": 120,
                "history_days": 3,
            },
        )

    engine = object()
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)
    monkeypatch.setattr(
        data_loader,
        "_build_portfolio_covariance_context",
        fake_build_context,
    )

    covariance_matrix, meta = cw2_mod._build_portfolio_covariance_context(
        date(2026, 4, 15),
        ["AAPL", "_MACRO"],
        config=config,
    )

    assert covariance_matrix.loc["AAPL", "AAPL"] == 0.05
    assert meta["covariance_method"] == "fundamental_factor"
    assert meta["requested_covariance_method"] == "fundamental_factor"
    assert captured["engine"] is engine
    assert captured["as_of_date"] == date(2026, 4, 15)
    assert captured["symbols"] == ["AAPL"]
    assert captured["config"] is config
    assert cw2_mod._benchmark_ticker(config) == "QQQ"
    assert cw2_mod._portfolio_name(None) == "cw2_core_equity"


def test_json_identifier_and_upsert_helpers(monkeypatch):
    payload = {
        "when": date(2026, 4, 15),
        "value": _ArrayValue(3.5),
        "broken": _BrokenArrayValue(),
        "decimal": cw2_mod.Decimal("1.5"),
        "infinite_float": float("inf"),
        "infinite_decimal": cw2_mod.Decimal("Infinity"),
    }
    cleaned = cw2_mod._json_safe_value(payload)
    assert cleaned["when"] == "2026-04-15"
    assert cleaned["value"] == 3.5
    assert isinstance(cleaned["broken"], _BrokenArrayValue)
    assert cleaned["decimal"] == 1.5
    assert cleaned["infinite_float"] is None
    assert cleaned["infinite_decimal"] is None
    assert cw2_mod._json_dumps(
        {"payload": {"when": cleaned["when"], "value": cleaned["value"]}}
    )

    assert cw2_mod._safe_float("4.2") == 4.2
    assert cw2_mod._safe_float(float("inf")) is None
    assert cw2_mod._average([1.0, None, 3.0]) == 2.0
    assert cw2_mod._first_non_null([None, "", "alpha"]) == "alpha"
    assert cw2_mod._aggregate_sector_weights(
        [
            {"gics_sector": "Tech", "target_weight": 0.25},
            {"gics_sector": "Tech", "target_weight": 0.15},
            {"gics_sector": "Health", "target_weight": 0.10},
        ]
    ) == {"Health": 0.1, "Tech": 0.4}

    engine = _SequenceEngine([{}])
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)
    count = cw2_mod._upsert_rows(
        table_name="feature_factor_scores",
        rows=[
            {
                "as_of_date": date(2026, 4, 15),
                "symbol": "AAPL",
                "quality_score": float("inf"),
            }
        ],
        allowed_cols=["as_of_date", "symbol", "quality_score"],
        conflict_cols=["as_of_date", "symbol"],
    )
    assert count == 1
    assert engine.conn.calls[0][1][0]["quality_score"] is None

    with pytest.raises(ValueError):
        cw2_mod._validated_identifier("bad-name", label="table_name")


def test_replace_rows_for_scope_deletes_then_upserts(monkeypatch):
    engine = _SequenceEngine([{}, {}])
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)

    count = cw2_mod._replace_rows_for_scope(
        table_name="portfolio_target_positions",
        rows=[
            {
                "as_of_date": date(2026, 4, 15),
                "portfolio_name": "cw2_core_equity",
                "symbol": "AAPL",
                "target_weight": 1.0,
            }
        ],
        allowed_cols=["as_of_date", "portfolio_name", "symbol", "target_weight"],
        conflict_cols=["as_of_date", "portfolio_name", "symbol"],
        scope_cols=["as_of_date", "portfolio_name"],
        scope_values={
            "as_of_date": date(2026, 4, 15),
            "portfolio_name": "cw2_core_equity",
        },
    )

    assert count == 1
    assert (
        "DELETE FROM systematic_equity.portfolio_target_positions"
        in engine.conn.calls[0][0]
    )
    assert engine.conn.calls[0][1] == {
        "as_of_date": date(2026, 4, 15),
        "portfolio_name": "cw2_core_equity",
    }
    assert engine.conn.calls[1][1][0]["symbol"] == "AAPL"


def test_factor_snapshot_loaders_apply_publish_date_cutoffs(monkeypatch):
    engine = _SequenceEngine(
        [
            {
                "rows": [
                    {
                        "symbol": "AAPL",
                        "observation_date": date(2026, 4, 14),
                        "factor_name": "pb_ratio",
                        "factor_value": 5.0,
                        "publish_date": date(2026, 4, 14),
                    }
                ],
                "keys": [
                    "symbol",
                    "observation_date",
                    "factor_name",
                    "factor_value",
                    "publish_date",
                ],
            },
            {
                "rows": [
                    {
                        "symbol": "AAPL",
                        "report_date": date(2025, 12, 31),
                        "metric_name": "roe",
                        "metric_value": 0.2,
                        "source": "edgar",
                        "publish_date": date(2026, 2, 15),
                    }
                ],
                "keys": [
                    "symbol",
                    "report_date",
                    "metric_name",
                    "metric_value",
                    "source",
                    "publish_date",
                ],
            },
        ]
    )
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)

    factor_df = cw2_mod._load_latest_factor_snapshot(
        date(2026, 4, 15), ["AAPL"], ["pb_ratio"]
    )
    financial_df = cw2_mod._load_financial_snapshot(
        date(2026, 4, 14),
        date(2026, 4, 15),
        ["AAPL"],
    )

    assert factor_df["publish_date"].iloc[0] == date(2026, 4, 14)
    assert financial_df["publish_date"].iloc[0] == date(2026, 2, 15)
    assert (
        "COALESCE(publish_date, observation_date) <= :as_of_date"
        in engine.conn.calls[0][0]
    )
    assert "report_date <= :market_as_of_date" in engine.conn.calls[1][0]
    assert "publish_date <= :publish_cutoff_date" in engine.conn.calls[1][0]
    assert "publish_date AS publish_date" in engine.conn.calls[1][0]


def test_load_factor_snapshot_uses_latest_available_observation(monkeypatch):
    engine = _SequenceEngine(
        [
            {
                "rows": [
                    {
                        "symbol": "AAPL",
                        "observation_date": date(2026, 4, 14),
                        "factor_name": "pb_ratio",
                        "factor_value": 5.0,
                        "publish_date": date(2026, 4, 14),
                    }
                ],
                "keys": [
                    "symbol",
                    "observation_date",
                    "factor_name",
                    "factor_value",
                    "publish_date",
                ],
            }
        ]
    )
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)

    factor_df = cw2_mod._load_factor_snapshot(date(2026, 4, 15), ["AAPL"])

    assert factor_df["observation_date"].iloc[0] == date(2026, 4, 14)
    assert factor_df["publish_date"].iloc[0] == date(2026, 4, 14)
    assert "observation_date <= :as_of_date" in engine.conn.calls[0][0]
    assert "ROW_NUMBER() OVER" in engine.conn.calls[0][0]


def test_load_factor_snapshot_can_filter_requested_factor_names(monkeypatch):
    engine = _SequenceEngine(
        [
            {
                "rows": [
                    {
                        "symbol": "AAPL",
                        "observation_date": date(2026, 4, 14),
                        "factor_name": "pb_ratio",
                        "factor_value": 5.0,
                        "publish_date": date(2026, 4, 14),
                    }
                ],
                "keys": [
                    "symbol",
                    "observation_date",
                    "factor_name",
                    "factor_value",
                    "publish_date",
                ],
            }
        ]
    )
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)

    factor_df = cw2_mod._load_factor_snapshot(
        date(2026, 4, 15),
        ["AAPL"],
        factor_names=["pb_ratio"],
    )

    assert factor_df["factor_name"].iloc[0] == "pb_ratio"
    assert "factor_name = ANY(:factor_names)" in engine.conn.calls[0][0]
    assert engine.conn.calls[0][1]["factor_names"] == ["pb_ratio"]


def test_financial_snapshot_loader_can_enable_legacy_publish_fallback(monkeypatch):
    engine = _SequenceEngine(
        [
            {
                "rows": [
                    {
                        "symbol": "AAPL",
                        "report_date": date(2025, 12, 31),
                        "metric_name": "roe",
                        "metric_value": 0.2,
                        "source": "edgar",
                        "publish_date": date(2026, 2, 15),
                    }
                ],
                "keys": [
                    "symbol",
                    "report_date",
                    "metric_name",
                    "metric_value",
                    "source",
                    "publish_date",
                ],
            }
        ]
    )
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)
    monkeypatch.setenv("CW1_ALLOW_FINANCIAL_PUBLISH_FALLBACK", "true")

    cw2_mod._load_financial_snapshot(date(2026, 4, 14), date(2026, 4, 15), ["AAPL"])

    assert "COALESCE(publish_date, as_of, report_date) AS publish_date" in engine.conn.calls[0][0]
    assert "COALESCE(publish_date, as_of, report_date) <= :publish_cutoff_date" in engine.conn.calls[0][0]


def test_resolve_feature_as_of_date_prefers_price_anchor_and_falls_back(monkeypatch):
    engine = _SequenceEngine(
        [
            {"rows": [], "keys": ["as_of_date"]},
            {"rows": [{"as_of_date": date(2026, 4, 14)}], "keys": ["as_of_date"]},
        ]
    )
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)

    resolved = cw2_mod._resolve_feature_as_of_date(date(2026, 4, 15), ["AAPL", "MSFT"])

    assert resolved == date(2026, 4, 14)
    assert "factor_name = 'adjusted_close_price'" in engine.conn.calls[0][0]
    assert "COUNT(DISTINCT symbol) >= :min_symbols" in engine.conn.calls[0][0]
    assert "COUNT(DISTINCT symbol) >= :min_symbols" in engine.conn.calls[1][0]
    assert engine.conn.calls[0][1]["min_symbols"] == 2


def test_publish_cutoff_predicate_raises_when_required_parts_missing():
    with pytest.raises(ValueError, match="publish cutoff predicate requires"):
        cw2_mod._pit_publish_cutoff_predicate("")

    with pytest.raises(ValueError, match="publish cutoff predicate requires"):
        cw2_mod._pit_publish_cutoff_predicate("as_of_date", fallback_expr="")


def test_registry_manifest_and_quality_helpers(monkeypatch):
    engine = _SequenceEngine([{"scalar": "stored-snapshot"}, {}, {}, {}])
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)
    monkeypatch.setattr(
        cw2_mod, "resolve_version_bundle", lambda cfg: cfg["governance"]["versions"]
    )
    monkeypatch.setattr(
        cw2_mod,
        "select_version_fields",
        lambda bundle, keys: {key: bundle[key] for key in keys},
    )

    snapshot = cw2_mod.CW2PITSnapshot(
        requested_as_of_date=date(2026, 4, 15),
        as_of_date=date(2026, 4, 14),
        financial_publish_cutoff_date=date(2026, 4, 15),
        factor_df=pd.DataFrame([{"symbol": "AAPL"}]),
        financial_df=pd.DataFrame([{"symbol": "AAPL"}]),
        company_info=pd.DataFrame(),
        company_info_lookup={},
        sector_map={},
        vix_level=19.5,
        vix_history=[19.0, 19.5],
        risk_data=pd.DataFrame(),
        covariance_matrix=pd.DataFrame([[0.02]], index=["AAPL"], columns=["AAPL"]),
        covariance_meta={"covariance_method": "diag", "symbol_count": 1},
        previous_positions=[{"symbol": "AAPL", "target_weight": 0.5}],
        term_spread_level=0.4,
        term_spread_history=[0.3, 0.4],
    )
    guard = cw2_mod.UniverseGuardResult(
        min_scoring_universe=10,
        min_investable_universe=5,
        scoring_universe=25,
        investable_universe=20,
        allow_factor_scoring=True,
        allow_portfolio_construction=True,
    )
    config = {
        "portfolio_construction": {"portfolio_name": "cw2_core_equity"},
        "regime": {},
        "pipeline_guards": {},
        "governance": {
            "versions": {
                "model_version": "m1",
                "factor_definition_version": "f1",
                "covariance_method_version": "c1",
                "risk_overlay_policy_version": "r1",
            }
        },
    }

    snapshot_id = cw2_mod._write_feature_snapshot_registry(
        snapshot_id="snapshot-1",
        requested_as_of=date(2026, 4, 15),
        snapshot=snapshot,
        guard=guard,
        config=config,
    )
    assert snapshot_id == "stored-snapshot"
    registry_row = engine.conn.calls[0][1]
    assert registry_row["snapshot_status"] == "completed"
    assert (
        json.loads(registry_row["config_snapshot"])["governance"]["versions"][
            "model_version"
        ]
        == "m1"
    )

    cw2_mod._write_model_input_manifest(
        snapshot_id="stored-snapshot",
        as_of_date=date(2026, 4, 14),
        manifest_type="feature_input",
        payload={"symbols": ["AAPL"]},
    )
    manifest_insert = engine.conn.calls[2][1]
    assert json.loads(manifest_insert["payload_json"]) == {"symbols": ["AAPL"]}

    cw2_mod._write_portfolio_snapshot_registry(
        snapshot_id="stored-snapshot",
        as_of_date=date(2026, 4, 14),
        portfolio_name="cw2_core_equity",
        portfolio_target_records=[
            {
                "symbol": "AAPL",
                "target_weight": 0.6,
                "composite_alpha": 1.2,
                "trade_weight": 0.1,
                "gics_sector": "Tech",
                "source": "cw2_portfolio_construction",
            }
        ],
        config=config,
    )
    portfolio_row = engine.conn.calls[3][1]
    assert portfolio_row["snapshot_status"] == "completed"
    assert json.loads(portfolio_row["summary_json"])["top_symbols"] == ["AAPL"]

    quality_calls = []
    monkeypatch.setattr(
        cw2_mod, "write_quality_snapshot", lambda **kwargs: quality_calls.append(kwargs)
    )
    cw2_mod._write_cw2_quality_gate(
        requested_as_of=date(2026, 4, 15),
        snapshot=snapshot,
        guard=guard,
        universe_screen_records=[{"symbol": "AAPL"}],
        sub_score_records=[{"symbol": "AAPL"}],
        factor_score_records=[{"symbol": "AAPL"}],
        risk_overlay_records=[{"symbol": "AAPL", "pass_all": False}],
        portfolio_target_records=[],
        config={
            "quality_gates": {
                "min_sub_score_rows": 2,
                "min_factor_score_rows": 2,
                "min_risk_overlay_rows": 2,
                "min_portfolio_targets": 1,
                "min_factor_score_coverage_vs_scoring": 0.5,
                "min_risk_pass_rate": 0.5,
                "max_as_of_date_shift_days": 0,
            }
        },
    )
    report = quality_calls[0]["quality_report"]
    assert report["passed"] is False
    assert "portfolio_target_rows_below_threshold" in report["failures"]
    assert "as_of_shift_exceeds_threshold" in report["failures"]


def test_write_portfolio_snapshot_registry_marks_carried_forward_status(monkeypatch):
    engine = _SequenceEngine([{}])
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: engine)
    monkeypatch.setattr(
        cw2_mod, "resolve_version_bundle", lambda cfg: cfg["governance"]["versions"]
    )
    monkeypatch.setattr(
        cw2_mod,
        "select_version_fields",
        lambda bundle, keys: {key: bundle[key] for key in keys},
    )

    config = {
        "governance": {
            "versions": {
                "model_version": "m1",
                "factor_definition_version": "f1",
                "covariance_method_version": "c1",
                "risk_overlay_policy_version": "r1",
            }
        }
    }

    cw2_mod._write_portfolio_snapshot_registry(
        snapshot_id="stored-snapshot",
        as_of_date=date(2026, 4, 30),
        portfolio_name="cw2_core_equity",
        portfolio_target_records=[
            {
                "symbol": "AAPL",
                "target_weight": 0.6,
                "composite_alpha": 1.2,
                "trade_weight": 0.0,
                "gics_sector": "Tech",
                "source": "frequency_carry",
            }
        ],
        config=config,
    )

    portfolio_row = engine.conn.calls[0][1]
    assert portfolio_row["snapshot_status"] == "carried_forward"
    summary = json.loads(portfolio_row["summary_json"])
    assert summary["snapshot_status"] == "carried_forward"
    assert summary["sources"] == ["frequency_carry"]


def test_write_cw2_quality_gate_warns_when_portfolio_breadth_is_near_floor(monkeypatch):
    quality_calls = []
    monkeypatch.setattr(
        cw2_mod, "write_quality_snapshot", lambda **kwargs: quality_calls.append(kwargs)
    )
    snapshot = cw2_mod.CW2PITSnapshot(
        requested_as_of_date=date(2026, 4, 15),
        as_of_date=date(2026, 4, 15),
        financial_publish_cutoff_date=date(2026, 4, 15),
        factor_df=pd.DataFrame(),
        financial_df=pd.DataFrame(),
        company_info=pd.DataFrame(),
        company_info_lookup={},
        sector_map={},
        vix_level=19.5,
        vix_history=[19.5],
        risk_data=pd.DataFrame(),
        covariance_matrix=None,
        covariance_meta=None,
        previous_positions=[],
        term_spread_level=None,
        term_spread_history=[],
    )
    guard = cw2_mod.UniverseGuardResult(
        min_scoring_universe=10,
        min_investable_universe=25,
        scoring_universe=40,
        investable_universe=28,
        allow_factor_scoring=True,
        allow_portfolio_construction=True,
    )

    cw2_mod._write_cw2_quality_gate(
        requested_as_of=date(2026, 4, 15),
        snapshot=snapshot,
        guard=guard,
        universe_screen_records=[{"symbol": f"S{i:02d}"} for i in range(28)],
        sub_score_records=[{"symbol": f"S{i:02d}", "z_score": 0.1} for i in range(160)],
        factor_score_records=[{"symbol": f"S{i:02d}"} for i in range(32)],
        risk_overlay_records=[
            {"symbol": f"S{i:02d}", "pass_all": True} for i in range(28)
        ],
        portfolio_target_records=[
            {"symbol": f"S{i:02d}", "target_weight": 1 / 27} for i in range(27)
        ],
        config={
            "quality_gates": {
                "min_sub_score_rows": 150,
                "min_factor_score_rows": 30,
                "min_risk_overlay_rows": 20,
                "min_portfolio_targets": 25,
                "min_factor_score_coverage_vs_scoring": 0.70,
                "min_risk_pass_rate": 0.50,
                "max_as_of_date_shift_days": 5,
            },
            "portfolio_construction": {
                "hybrid_min_n": 30,
            },
        },
    )

    report = quality_calls[0]["quality_report"]
    assert report["passed"] is True
    assert report["failures"] == []
    assert report["warnings"] == ["portfolio_target_rows_near_threshold"]
    assert report["portfolio_target_floor"] == 25
    assert report["portfolio_target_warning_ceiling"] == 30
    assert report["portfolio_target_breadth_margin"] == 2


def test_persist_covariance_artifact_writes_npz_to_minio(monkeypatch):
    captured = {}

    class _FakeMinio:
        def bucket_exists(self, bucket):
            captured["bucket_exists"] = bucket
            return True

        def make_bucket(self, bucket):  # pragma: no cover - should not be called
            raise AssertionError(f"unexpected bucket creation: {bucket}")

        def put_object(self, bucket, object_name, data, length, content_type):
            captured["put"] = {
                "bucket": bucket,
                "object_name": object_name,
                "length": length,
                "content_type": content_type,
                "payload": data.read(),
            }

    monkeypatch.setattr(
        cw2_mod,
        "_resolved_minio_config",
        lambda: {
            "endpoint": "miniocw:9000",
            "access_key": "ift_bigdata",
            "secret_key": "minio_password",
            "bucket": "csreport",
            "secure": False,
        },
    )
    monkeypatch.setattr(
        cw2_mod, "_build_minio_client", lambda cfg: _FakeMinio()
    )  # noqa: ARG005

    meta = cw2_mod._persist_covariance_artifact(
        snapshot_id="snap-1",
        as_of_date=date(2026, 4, 14),
        portfolio_name="cw2_core_equity",
        covariance_matrix=pd.DataFrame(
            [[0.03, 0.01], [0.01, 0.04]],
            index=["AAPL", "MSFT"],
            columns=["AAPL", "MSFT"],
        ),
        covariance_meta={"covariance_method": "diag", "lookback_days": 252},
    )

    assert meta["storage_type"] == "minio"
    assert meta["bucket"] == "csreport"
    assert meta["object_key"].endswith("snapshot_id=snap-1.npz")
    assert meta["symbol_count"] == 2
    assert captured["put"]["content_type"] == "application/octet-stream"
    assert captured["put"]["length"] == len(captured["put"]["payload"])


def test_build_and_load_cw2_features_happy_path_and_no_snapshot(monkeypatch):
    requested_as_of = date(2026, 4, 15)
    snapshot = cw2_mod.CW2PITSnapshot(
        requested_as_of_date=requested_as_of,
        as_of_date=date(2026, 4, 14),
        financial_publish_cutoff_date=requested_as_of,
        factor_df=pd.DataFrame(
            [
                {"symbol": "AAPL", "factor_name": "pb_ratio", "factor_value": 1.0},
                {"symbol": "_MACRO", "factor_name": "vix_close", "factor_value": 18.0},
            ]
        ),
        financial_df=pd.DataFrame(
            [{"symbol": "AAPL", "metric_name": "roe", "metric_value": 0.2}]
        ),
        company_info=pd.DataFrame(
            [{"symbol": "AAPL", "gics_sector": "Tech", "country": "US"}]
        ),
        company_info_lookup={"AAPL": {"gics_sector": "Tech", "country": "US"}},
        sector_map={"AAPL": "Tech"},
        vix_level=18.0,
        vix_history=[17.0, 18.0],
        risk_data=pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "log_market_cap": 25.0,
                    "liquidity_20d": 1e6,
                    "volatility_60d": 0.2,
                }
            ]
        ),
        covariance_matrix=pd.DataFrame([[0.03]], index=["AAPL"], columns=["AAPL"]),
        covariance_meta={"covariance_method": "diag"},
        previous_positions=[{"symbol": "AAPL", "target_weight": 0.4}],
    )

    monkeypatch.setattr(cw2_mod, "_ensure_cw2_schema", lambda: None)
    monkeypatch.setattr(
        cw2_mod,
        "_load_cw2_config",
        lambda config_path=None: {
            "portfolio_construction": {"portfolio_name": "cw2_core_equity"},
            "preprocessing": {"min_observations": 1},
            "pipeline_guards": {
                "min_scoring_universe": 1,
                "min_investable_universe": 1,
            },
            "governance": {
                "versions": {
                    "model_version": "m1",
                    "factor_definition_version": "f1",
                    "covariance_method_version": "c1",
                    "risk_overlay_policy_version": "r1",
                }
            },
        },
    )
    monkeypatch.setattr(cw2_mod, "_build_cw2_pit_snapshot", lambda **kwargs: snapshot)
    monkeypatch.setattr(
        cw2_mod,
        "_load_previous_portfolio_target_snapshot",
        lambda *args, **kwargs: (
            date(2026, 3, 31),
            [
                {
                    "symbol": "AAPL",
                    "selection_rank": 1,
                    "selected_signal": True,
                    "target_weight": 0.4,
                    "weighting_scheme": "mean_variance",
                    "ranking_mode": "global",
                    "ranking_score": 0.9,
                    "composite_alpha": 0.9,
                    "regime": "normal",
                    "gics_sector": "Tech",
                    "country": "US",
                    "previous_weight": 0.4,
                    "trade_weight": 0.6,
                    "turnover_cap": None,
                    "realized_turnover": 0.6,
                    "turnover_limited": False,
                }
            ],
        ),
    )
    monkeypatch.setattr(
        cw2_mod, "_write_feature_snapshot_registry", lambda **kwargs: "snap-1"
    )
    monkeypatch.setattr(
        cw2_mod,
        "_persist_covariance_artifact",
        lambda **kwargs: {  # noqa: ARG005
            "storage_type": "minio",
            "bucket": "csreport",
            "object_key": "artifacts/cw2/covariance/snap-1.npz",
            "format": "npz",
        },
    )
    manifest_calls = []
    monkeypatch.setattr(
        cw2_mod,
        "_write_model_input_manifest",
        lambda **kwargs: manifest_calls.append(kwargs),
    )
    portfolio_registry_calls = []
    monkeypatch.setattr(
        cw2_mod,
        "_write_portfolio_snapshot_registry",
        lambda **kwargs: portfolio_registry_calls.append(kwargs),
    )
    quality_calls = []
    monkeypatch.setattr(
        cw2_mod,
        "_write_cw2_quality_gate",
        lambda **kwargs: quality_calls.append(kwargs),
    )
    monkeypatch.setattr(
        cw2_mod,
        "_upsert_rows",
        lambda **kwargs: len(kwargs["rows"]),
    )
    monkeypatch.setattr(
        cw2_mod,
        "_replace_rows_for_scope",
        lambda **kwargs: len(kwargs["rows"]),
    )
    monkeypatch.setattr(
        cw2_mod,
        "_import_cw2_modules",
        lambda: (
            lambda factor_df, financial_df, as_of_date, sector_map, config=None: (  # noqa: ARG005
                [
                    {
                        "symbol": "AAPL",
                        "factor_group": "quality",
                        "sub_variable": "roe",
                        "z_score": 1.0,
                    }
                ],
                [{"symbol": "AAPL", "quality_score": 0.9, "composite_alpha": 0.9}],
            ),
            lambda records, **kwargs: [
                {
                    **record,
                    "composite_alpha": record["composite_alpha"],
                    "regime": "normal",
                    "vix_level": 18.0,
                }
                for record in records
            ],
            lambda factor_scores, risk_df, sub_scores, config=None: [  # noqa: ARG005
                {
                    "symbol": "AAPL",
                    "as_of_date": snapshot.as_of_date,
                    "log_market_cap": 25.0,
                    "liquidity_20d": 1e6,
                    "volatility_60d": 0.2,
                    "missing_factor_pct": 0.0,
                    "factor_groups_present": 5,
                    "pass_market_cap": True,
                    "pass_liquidity": True,
                    "pass_volatility": True,
                    "pass_factor_coverage": True,
                    "pass_data_quality": True,
                    "pass_all": True,
                }
            ],
            lambda risk_data, company_info, as_of_date, config=None: [  # noqa: ARG005
                {
                    "as_of_date": snapshot.as_of_date,
                    "symbol": "AAPL",
                    "country": "US",
                    "gics_sector": "Tech",
                    "log_market_cap": 25.0,
                    "liquidity_20d": 1e6,
                    "pass_country": True,
                    "pass_market_cap": True,
                    "pass_liquidity": True,
                    "pass_all": True,
                }
            ],
            lambda factor_scores, risk_overlay, universe_screen, company_info_lookup, **kwargs: (  # noqa: ARG005
                [
                    {
                        "as_of_date": snapshot.as_of_date,
                        "portfolio_name": "cw2_core_equity",
                        "symbol": "AAPL",
                        "selection_rank": 1,
                        "selected_signal": True,
                        "target_weight": 1.0,
                        "weighting_scheme": "mean_variance",
                        "ranking_mode": "global",
                        "ranking_score": 0.9,
                        "composite_alpha": 0.9,
                        "regime": "normal",
                        "gics_sector": "Tech",
                        "country": "US",
                        "previous_weight": 0.4,
                        "trade_weight": 0.6,
                        "turnover_cap": None,
                        "realized_turnover": 0.6,
                        "turnover_limited": False,
                    }
                ],
                kwargs.get("return_diagnostics")
                and SimpleNamespace(
                    records=[
                        {
                            "as_of_date": snapshot.as_of_date,
                            "portfolio_name": "cw2_core_equity",
                            "symbol": "AAPL",
                            "candidate_rank": 1,
                            "selected_signal": True,
                            "selection_drop_reason": None,
                            "gics_sector": "Tech",
                            "country": "US",
                            "ranking_mode": "global",
                            "ranking_score": 0.9,
                            "composite_alpha": 0.9,
                            "optimizer_requested": "mean_variance",
                            "optimizer_applied": "mean_variance",
                            "raw_preference_weight": 1.0,
                            "pre_constraint_weight": 1.0,
                            "constrained_weight": 1.0,
                            "final_target_weight": 1.0,
                            "previous_weight": 0.4,
                            "constraint_weight_delta": 0.0,
                            "turnover_weight_delta": 0.0,
                            "total_weight_delta": 0.0,
                            "sector_weight_pre_constraint": 1.0,
                            "sector_weight_post_constraint": 1.0,
                            "sector_weight_final": 1.0,
                            "max_single_weight": None,
                            "max_sector_weight": None,
                            "single_name_cap_binding": False,
                            "sector_cap_binding": False,
                            "turnover_limited": False,
                            "turnover_cap": None,
                            "realized_turnover": 0.6,
                            "covariance_method": "diag",
                            "optimizer_fallback_reason": None,
                            "diagnostic_json": {"binding_reasons": []},
                        }
                    ],
                    summary={"status": "completed", "candidate_count": 1},
                ),
            ),
        ),
    )

    result = cw2_mod.build_and_load_cw2_features(
        run_date="2026-04-15",
        symbols=["AAPL"],
    )

    assert result == {
        "universe_screen": 1,
        "sub_scores": 1,
        "factor_scores": 1,
        "risk_overlay": 1,
        "portfolio_targets": 1,
        "portfolio_diagnostics": 1,
        "covariance_artifact_stored": 1,
        "as_of_date_shifted": 1,
    }
    assert len(manifest_calls) == 3
    assert len(portfolio_registry_calls) == 1
    assert len(quality_calls) == 1
    portfolio_manifest = next(
        call for call in manifest_calls if call["manifest_type"] == "portfolio_input"
    )
    assert portfolio_manifest["payload"]["covariance_artifact"]["object_key"].endswith(
        "snap-1.npz"
    )
    assert portfolio_manifest["payload"]["construction_diagnostics"]["row_count"] == 1

    monkeypatch.setattr(cw2_mod, "_build_cw2_pit_snapshot", lambda **kwargs: None)
    empty_result = cw2_mod.build_and_load_cw2_features(
        run_date="2026-04-15",
        symbols=["AAPL"],
    )
    assert empty_result == {
        "universe_screen": 0,
        "sub_scores": 0,
        "factor_scores": 0,
        "risk_overlay": 0,
        "portfolio_targets": 0,
        "portfolio_diagnostics": 0,
        "covariance_artifact_stored": 0,
        "as_of_date_shifted": 0,
    }


def test_build_and_load_cw2_features_carries_forward_off_cycle_targets(monkeypatch):
    requested_as_of = date(2026, 4, 30)
    snapshot = cw2_mod.CW2PITSnapshot(
        requested_as_of_date=requested_as_of,
        as_of_date=requested_as_of,
        financial_publish_cutoff_date=requested_as_of,
        factor_df=pd.DataFrame(
            [
                {"symbol": "AAPL", "factor_name": "pb_ratio", "factor_value": 1.0},
                {"symbol": "_MACRO", "factor_name": "vix_close", "factor_value": 18.0},
            ]
        ),
        financial_df=pd.DataFrame(
            [{"symbol": "AAPL", "metric_name": "roe", "metric_value": 0.2}]
        ),
        company_info=pd.DataFrame(
            [{"symbol": "AAPL", "gics_sector": "Tech", "country": "US"}]
        ),
        company_info_lookup={"AAPL": {"gics_sector": "Tech", "country": "US"}},
        sector_map={"AAPL": "Tech"},
        vix_level=18.0,
        vix_history=[17.0, 18.0],
        risk_data=pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "log_market_cap": 25.0,
                    "liquidity_20d": 1e6,
                    "volatility_60d": 0.2,
                }
            ]
        ),
        covariance_matrix=pd.DataFrame([[0.03]], index=["AAPL"], columns=["AAPL"]),
        covariance_meta={"covariance_method": "diag"},
        previous_positions=[{"symbol": "AAPL", "target_weight": 0.4}],
    )

    monkeypatch.setattr(cw2_mod, "_ensure_cw2_schema", lambda: None)
    monkeypatch.setattr(
        cw2_mod,
        "_load_cw2_config",
        lambda config_path=None: {
            "portfolio_construction": {
                "portfolio_name": "cw2_core_equity",
                "target_generation_frequency": "quarterly",
            },
            "preprocessing": {"min_observations": 1},
            "pipeline_guards": {
                "min_scoring_universe": 1,
                "min_investable_universe": 1,
            },
            "governance": {
                "versions": {
                    "model_version": "m1",
                    "factor_definition_version": "f1",
                    "covariance_method_version": "c1",
                    "risk_overlay_policy_version": "r1",
                }
            },
        },
    )
    monkeypatch.setattr(cw2_mod, "_build_cw2_pit_snapshot", lambda **kwargs: snapshot)
    monkeypatch.setattr(
        cw2_mod, "_write_feature_snapshot_registry", lambda **kwargs: "snap-2"
    )
    monkeypatch.setattr(cw2_mod, "_persist_covariance_artifact", lambda **kwargs: None)
    monkeypatch.setattr(
        cw2_mod,
        "_load_previous_portfolio_target_snapshot",
        lambda *args, **kwargs: (
            date(2026, 3, 31),
            [
                {
                    "symbol": "AAPL",
                    "selection_rank": 1,
                    "selected_signal": True,
                    "target_weight": 1.0,
                    "weighting_scheme": "mean_variance",
                    "ranking_mode": "global",
                    "ranking_score": 0.9,
                    "composite_alpha": 0.9,
                    "regime": "normal",
                    "gics_sector": "Tech",
                    "country": "US",
                    "previous_weight": 0.4,
                    "trade_weight": 0.6,
                    "turnover_cap": 0.6,
                    "realized_turnover": 0.6,
                    "turnover_limited": False,
                }
            ],
        ),
    )
    manifest_calls = []
    monkeypatch.setattr(
        cw2_mod,
        "_write_model_input_manifest",
        lambda **kwargs: manifest_calls.append(kwargs),
    )
    monkeypatch.setattr(
        cw2_mod, "_write_portfolio_snapshot_registry", lambda **kwargs: None
    )
    monkeypatch.setattr(cw2_mod, "_write_cw2_quality_gate", lambda **kwargs: None)
    monkeypatch.setattr(cw2_mod, "_upsert_rows", lambda **kwargs: len(kwargs["rows"]))
    replace_calls = []

    def _capture_replace(**kwargs):
        replace_calls.append(kwargs)
        return len(kwargs["rows"])

    monkeypatch.setattr(cw2_mod, "_replace_rows_for_scope", _capture_replace)

    def _unexpected_portfolio_build(*args, **kwargs):  # noqa: ARG001, ARG002
        raise AssertionError("portfolio construction should be skipped off-cycle")

    monkeypatch.setattr(
        cw2_mod,
        "_import_cw2_modules",
        lambda: (
            lambda factor_df, financial_df, as_of_date, sector_map, config=None: (  # noqa: ARG005
                [
                    {
                        "symbol": "AAPL",
                        "factor_group": "quality",
                        "sub_variable": "roe",
                        "z_score": 1.0,
                    }
                ],
                [{"symbol": "AAPL", "quality_score": 0.9, "composite_alpha": 0.9}],
            ),
            lambda records, **kwargs: [
                {
                    **record,
                    "composite_alpha": record["composite_alpha"],
                    "regime": "normal",
                    "vix_level": 18.0,
                }
                for record in records
            ],
            lambda factor_scores, risk_df, sub_scores, config=None: [  # noqa: ARG005
                {
                    "symbol": "AAPL",
                    "as_of_date": snapshot.as_of_date,
                    "log_market_cap": 25.0,
                    "liquidity_20d": 1e6,
                    "volatility_60d": 0.2,
                    "missing_factor_pct": 0.0,
                    "factor_groups_present": 5,
                    "pass_market_cap": True,
                    "pass_liquidity": True,
                    "pass_volatility": True,
                    "pass_factor_coverage": True,
                    "pass_data_quality": True,
                    "pass_all": True,
                }
            ],
            lambda risk_data, company_info, as_of_date, config=None: [  # noqa: ARG005
                {
                    "as_of_date": snapshot.as_of_date,
                    "symbol": "AAPL",
                    "country": "US",
                    "gics_sector": "Tech",
                    "log_market_cap": 25.0,
                    "liquidity_20d": 1e6,
                    "pass_country": True,
                    "pass_market_cap": True,
                    "pass_liquidity": True,
                    "pass_all": True,
                }
            ],
            _unexpected_portfolio_build,
        ),
    )

    result = cw2_mod.build_and_load_cw2_features(
        run_date="2026-04-30",
        symbols=["AAPL"],
    )

    assert result == {
        "universe_screen": 1,
        "sub_scores": 1,
        "factor_scores": 1,
        "risk_overlay": 1,
        "portfolio_targets": 1,
        "portfolio_diagnostics": 0,
        "covariance_artifact_stored": 0,
        "as_of_date_shifted": 0,
    }
    portfolio_replace = next(
        call
        for call in replace_calls
        if call["table_name"] == "portfolio_target_positions"
    )
    assert portfolio_replace["rows"] == [
        {
            "as_of_date": requested_as_of,
            "portfolio_name": "cw2_core_equity",
            "symbol": "AAPL",
            "selection_rank": 1,
            "selected_signal": True,
            "target_weight": 1.0,
            "weighting_scheme": "mean_variance",
            "ranking_mode": "global",
            "ranking_score": 0.9,
            "composite_alpha": 0.9,
            "regime": "normal",
            "gics_sector": "Tech",
            "country": "US",
            "previous_weight": 1.0,
            "trade_weight": 0.0,
            "turnover_cap": 0.6,
            "realized_turnover": 0.0,
            "turnover_limited": False,
            "source": "frequency_carry",
        }
    ]
    portfolio_manifest = next(
        call for call in manifest_calls if call["manifest_type"] == "portfolio_input"
    )
    assert portfolio_manifest["payload"]["construction_diagnostics"]["status"] == (
        "carried_forward"
    )
    assert portfolio_manifest["payload"]["construction_diagnostics"][
        "source_as_of_date"
    ] == "2026-03-31"
