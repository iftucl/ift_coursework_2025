from datetime import date

import pandas as pd
from modules.transform import cw2_features as cw2_mod


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return _FakeMappingsResult(self._rows)


class _FakeConn:
    def __init__(self, rows):
        self._rows = list(rows)

    def execute(self, stmt, params):  # noqa: ARG002
        return _FakeExecuteResult(self._rows)


class _FakeConnectCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False


class _FakeEngine:
    def __init__(self, rows):
        self._rows = list(rows)

    def connect(self):
        return _FakeConnectCtx(_FakeConn(self._rows))


def test_build_cw2_pit_snapshot_assembles_snapshot(monkeypatch):
    requested_as_of = date(2026, 4, 14)
    as_of_date = date(2026, 4, 11)
    factor_df = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "observation_date": as_of_date,
                "factor_name": "pb_ratio",
                "factor_value": 5.0,
            }
        ]
    )
    financial_df = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "report_date": date(2025, 12, 31),
                "metric_name": "roe",
                "metric_value": 0.2,
            }
        ]
    )
    company_info = pd.DataFrame(
        [{"symbol": "AAPL", "gics_sector": "Information Technology", "country": "US"}]
    )
    company_info_lookup = {
        "AAPL": {"gics_sector": "Information Technology", "country": "US"}
    }
    risk_data = pd.DataFrame([{"symbol": "AAPL", "log_market_cap": 25.0}])
    previous_positions = [{"symbol": "AAPL", "target_weight": 1.0}]
    captured = {}

    monkeypatch.setattr(
        cw2_mod, "_resolve_feature_as_of_date", lambda run_date, symbols: as_of_date
    )
    monkeypatch.setattr(cw2_mod, "_cw2_factor_names", lambda config=None: ["pb_ratio"])
    monkeypatch.setattr(
        cw2_mod, "_risk_factor_names", lambda config=None: ["log_market_cap"]
    )
    monkeypatch.setattr(
        cw2_mod, "_load_latest_factor_snapshot", lambda *args, **kwargs: factor_df
    )
    def _capture_financial_snapshot(
        market_as_of_date, publish_cutoff_date, symbols
    ):
        captured["market_as_of_date"] = market_as_of_date
        captured["publish_cutoff_date"] = publish_cutoff_date
        captured["symbols"] = list(symbols)
        return financial_df

    monkeypatch.setattr(cw2_mod, "_load_financial_snapshot", _capture_financial_snapshot)
    monkeypatch.setattr(cw2_mod, "_load_company_info", lambda symbols: company_info)
    monkeypatch.setattr(cw2_mod, "_company_info_map", lambda df: company_info_lookup)
    monkeypatch.setattr(cw2_mod, "_extract_vix_level", lambda df, as_of: 22.0)
    monkeypatch.setattr(
        cw2_mod,
        "_load_macro_factor_history",
        lambda *args, **kwargs: [20.0, 21.0, 22.0],
    )
    monkeypatch.setattr(
        cw2_mod,
        "_load_term_spread_context",
        lambda *args, **kwargs: (-0.15, [-0.05, -0.10, -0.15]),
    )
    monkeypatch.setattr(
        cw2_mod, "_extract_risk_data", lambda df, config=None: risk_data
    )
    monkeypatch.setattr(
        cw2_mod,
        "_load_previous_portfolio_positions",
        lambda *args, **kwargs: previous_positions,
    )

    snapshot = cw2_mod._build_cw2_pit_snapshot(
        requested_as_of_date=requested_as_of,
        symbols=["AAPL"],
        config={"portfolio_construction": {"portfolio_name": "cw2_core_equity"}},
    )

    assert snapshot is not None
    assert snapshot.requested_as_of_date == requested_as_of
    assert snapshot.as_of_date == as_of_date
    assert snapshot.financial_publish_cutoff_date == requested_as_of
    assert captured == {
        "market_as_of_date": as_of_date,
        "publish_cutoff_date": requested_as_of,
        "symbols": ["AAPL"],
    }
    assert snapshot.factor_df.equals(factor_df)
    assert snapshot.financial_df.equals(financial_df)
    assert snapshot.company_info.equals(company_info)
    assert snapshot.company_info_lookup == company_info_lookup
    assert snapshot.sector_map == {"AAPL": "Information Technology"}
    assert snapshot.vix_level == 22.0
    assert snapshot.vix_history == [20.0, 21.0, 22.0]
    assert snapshot.term_spread_level == -0.15
    assert snapshot.term_spread_history == [-0.05, -0.10, -0.15]
    assert snapshot.risk_data.equals(risk_data)
    assert snapshot.previous_positions == previous_positions


def test_load_macro_factor_series_returns_sorted_numeric_series(monkeypatch):
    rows = [
        {"observation_date": "2026-04-14", "factor_value": "4.20"},
        {"observation_date": "2026-04-12", "factor_value": "4.00"},
        {"observation_date": "2026-04-13", "factor_value": "bad"},
    ]
    monkeypatch.setattr(cw2_mod, "get_db_engine", lambda: _FakeEngine(rows))

    series = cw2_mod._load_macro_factor_series(
        date(2026, 4, 14),
        "us_treasury_10y",
        lookback_days=10,
    )

    assert list(series.index) == [date(2026, 4, 12), date(2026, 4, 14)]
    assert list(series.values) == [4.0, 4.2]


def test_evaluate_universe_guards_uses_configured_thresholds():
    guard = cw2_mod._evaluate_universe_guards(
        scoring_universe=28,
        investable_universe=12,
        config={
            "preprocessing": {"min_observations": 30},
            "portfolio_construction": {"min_names": 15, "min_candidate_pool": 10},
            "pipeline_guards": {
                "min_scoring_universe": 35,
                "min_investable_universe": 18,
            },
        },
    )

    assert guard.min_scoring_universe == 35
    assert guard.min_investable_universe == 18
    assert guard.allow_factor_scoring is False
    assert guard.allow_portfolio_construction is False


def test_target_generation_frequency_helper_respects_quarter_boundaries():
    config = {"portfolio_construction": {"target_generation_frequency": "quarterly"}}

    assert (
        cw2_mod._should_refresh_portfolio_targets(
            date(2026, 4, 30),
            config=config,
            previous_target_records=[{"symbol": "AAPL", "target_weight": 1.0}],
        )
        is False
    )
    assert (
        cw2_mod._should_refresh_portfolio_targets(
            date(2026, 6, 30),
            config=config,
            previous_target_records=[{"symbol": "AAPL", "target_weight": 1.0}],
        )
        is True
    )
    assert (
        cw2_mod._should_refresh_portfolio_targets(
            date(2026, 4, 30),
            config=config,
            previous_target_records=[],
        )
        is True
    )


def test_build_carried_forward_portfolio_targets_zeroes_trade_weights():
    records = cw2_mod._build_carried_forward_portfolio_targets(
        as_of_date=date(2026, 4, 30),
        portfolio_name="cw2_test",
        previous_target_records=[
            {
                "symbol": "AAPL",
                "selection_rank": 1,
                "selected_signal": True,
                "target_weight": 0.4,
                "weighting_scheme": "mean_variance",
                "ranking_mode": "global",
                "ranking_score": 1.2,
                "composite_alpha": 1.2,
                "regime": "normal",
                "gics_sector": "Tech",
                "country": "US",
                "turnover_cap": 0.6,
                "turnover_limited": True,
            }
        ],
    )

    assert records == [
        {
            "as_of_date": date(2026, 4, 30),
            "portfolio_name": "cw2_test",
            "symbol": "AAPL",
            "selection_rank": 1,
            "selected_signal": True,
            "target_weight": 0.4,
            "weighting_scheme": "mean_variance",
            "ranking_mode": "global",
            "ranking_score": 1.2,
            "composite_alpha": 1.2,
            "regime": "normal",
            "gics_sector": "Tech",
            "country": "US",
            "previous_weight": 0.4,
            "trade_weight": 0.0,
            "turnover_cap": 0.6,
            "realized_turnover": 0.0,
            "turnover_limited": False,
            "source": "frequency_carry",
        }
    ]


def test_build_and_load_cw2_features_returns_universe_only_when_scoring_guard_fails(
    monkeypatch,
):
    as_of_date = date(2026, 4, 14)
    snapshot = cw2_mod.CW2PITSnapshot(
        requested_as_of_date=as_of_date,
        as_of_date=as_of_date,
        financial_publish_cutoff_date=as_of_date,
        factor_df=pd.DataFrame(),
        financial_df=pd.DataFrame(),
        company_info=pd.DataFrame(),
        company_info_lookup={},
        sector_map={},
        vix_level=None,
        vix_history=[],
        risk_data=pd.DataFrame(),
        previous_positions=[],
    )

    universe_screen_records = [
        {
            "as_of_date": as_of_date,
            "symbol": "AAPL",
            "country": "US",
            "gics_sector": "Information Technology",
            "log_market_cap": 25.0,
            "liquidity_20d": 1_000_000.0,
            "pass_country": True,
            "pass_market_cap": True,
            "pass_liquidity": True,
            "pass_all": True,
        },
        {
            "as_of_date": as_of_date,
            "symbol": "MSFT",
            "country": "US",
            "gics_sector": "Information Technology",
            "log_market_cap": 25.0,
            "liquidity_20d": 1_000_000.0,
            "pass_country": True,
            "pass_market_cap": True,
            "pass_liquidity": True,
            "pass_all": True,
        },
    ]

    def _should_not_run(*args, **kwargs):
        raise AssertionError(
            "downstream factor/portfolio functions should not run when scoring guard fails"
        )

    monkeypatch.setattr(cw2_mod, "_ensure_cw2_schema", lambda: None)
    manifest_payloads = []
    monkeypatch.setattr(
        cw2_mod,
        "_load_cw2_config",
        lambda config_path=None: {
            "preprocessing": {"min_observations": 30},
            "portfolio_construction": {"min_names": 15, "min_candidate_pool": 10},
            "pipeline_guards": {
                "min_scoring_universe": 30,
                "min_investable_universe": 15,
            },
            "governance": {"versions": {"model_version": "cw2-model-test"}},
        },
    )
    monkeypatch.setattr(cw2_mod, "_build_cw2_pit_snapshot", lambda **kwargs: snapshot)
    monkeypatch.setattr(
        cw2_mod, "_write_feature_snapshot_registry", lambda **kwargs: None
    )
    monkeypatch.setattr(cw2_mod, "_persist_covariance_artifact", lambda **kwargs: None)
    monkeypatch.setattr(
        cw2_mod,
        "_write_model_input_manifest",
        lambda **kwargs: manifest_payloads.append(kwargs["payload"]),
    )
    monkeypatch.setattr(
        cw2_mod, "_write_portfolio_snapshot_registry", lambda **kwargs: None
    )
    monkeypatch.setattr(cw2_mod, "_write_cw2_quality_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        cw2_mod,
        "_import_cw2_modules",
        lambda: (
            _should_not_run,
            _should_not_run,
            _should_not_run,
            lambda *a, **k: universe_screen_records,
            _should_not_run,
        ),
    )
    monkeypatch.setattr(cw2_mod, "_upsert_rows", lambda **kwargs: len(kwargs["rows"]))
    monkeypatch.setattr(
        cw2_mod, "_replace_rows_for_scope", lambda **kwargs: len(kwargs["rows"])
    )

    result = cw2_mod.build_and_load_cw2_features(
        run_date="2026-04-14",
        symbols=["AAPL", "MSFT"],
    )

    assert result == {
        "universe_screen": 2,
        "sub_scores": 0,
        "factor_scores": 0,
        "risk_overlay": 0,
        "portfolio_targets": 0,
        "portfolio_diagnostics": 0,
        "covariance_artifact_stored": 0,
        "as_of_date_shifted": 0,
    }
    assert len(manifest_payloads) == 3
    assert all(
        payload["version_bundle"]["model_version"] == "cw2-model-test"
        for payload in manifest_payloads
    )
