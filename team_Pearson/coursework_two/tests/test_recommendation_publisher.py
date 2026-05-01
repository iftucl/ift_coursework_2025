"""Unit tests for the CW2 recommendation publishing layer."""

from __future__ import annotations

from datetime import date

import pytest
from team_Pearson.coursework_two.modules.recommendation import publisher as publisher_mod


def test_classify_position_action_variants():
    assert publisher_mod._classify_position_action(0.0, 0.05, 0.05) == "new_entry"
    assert publisher_mod._classify_position_action(0.03, 0.02, 0.05) == "increase"
    assert publisher_mod._classify_position_action(0.08, -0.03, 0.05) == "decrease"
    assert publisher_mod._classify_position_action(0.05, 0.0, 0.05) == "hold"


def test_publish_recommendation_from_config_returns_metadata(monkeypatch):
    quality = {}
    monkeypatch.setattr(
        publisher_mod,
        "_load_config",
        lambda _: {
            "portfolio_construction": {"portfolio_name": "cw2_core_equity"},
            "governance": {
                "versions": {
                    "recommendation_version": "rec-v2",
                    "model_version": "model-v2",
                }
            },
        },
    )
    monkeypatch.setattr(publisher_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(publisher_mod, "ensure_recommendation_schema", lambda engine: None)
    monkeypatch.setattr(
        publisher_mod,
        "_resolve_recommendation_as_of_date",
        lambda engine, requested_date, portfolio_name: publisher_mod.date(2026, 4, 14),
    )
    monkeypatch.setattr(
        publisher_mod,
        "_load_portfolio_targets",
        lambda engine, as_of_date, portfolio_name: [
            {
                "symbol": "AAA",
                "selection_rank": 1,
                "target_weight": 0.6,
                "weighting_scheme": "mean_variance",
                "ranking_mode": "global",
                "ranking_score": 1.23,
                "composite_alpha": 2.5,
                "regime": "normal",
                "gics_sector": "Tech",
                "country": "US",
                "previous_weight": 0.5,
                "trade_weight": 0.1,
                "turnover_limited": False,
            },
            {
                "symbol": "BBB",
                "selection_rank": 2,
                "target_weight": 0.4,
                "weighting_scheme": "mean_variance",
                "ranking_mode": "global",
                "ranking_score": 1.1,
                "composite_alpha": 1.5,
                "regime": "normal",
                "gics_sector": "Health",
                "country": "US",
                "previous_weight": 0.0,
                "trade_weight": 0.4,
                "turnover_limited": False,
            },
        ],
    )
    monkeypatch.setattr(
        publisher_mod,
        "_load_factor_scores",
        lambda engine, as_of_date, symbols: {
            "AAA": {
                "quality_score": 1.0,
                "value_score": 0.5,
                "market_technical_score": 0.3,
                "sentiment_score": 0.2,
                "dividend_score": 0.1,
            },
            "BBB": {
                "quality_score": 0.9,
                "value_score": 0.4,
                "market_technical_score": 0.2,
                "sentiment_score": 0.1,
                "dividend_score": 0.0,
            },
        },
    )
    monkeypatch.setattr(
        publisher_mod,
        "_load_overlay_lookup",
        lambda engine, as_of_date, symbols: {
            "AAA": {
                "pass_all": True,
                "missing_factor_pct": 0.1,
                "factor_groups_present": 5,
            },
            "BBB": {
                "pass_all": True,
                "missing_factor_pct": 0.2,
                "factor_groups_present": 4,
            },
        },
    )
    captured = {"header": None, "items": None, "events": None}
    monkeypatch.setattr(
        publisher_mod,
        "_write_header",
        lambda engine, row: captured.__setitem__("header", row),
    )
    monkeypatch.setattr(
        publisher_mod,
        "_write_items",
        lambda engine, rows: captured.__setitem__("items", rows),
    )
    monkeypatch.setattr(
        publisher_mod,
        "_write_events",
        lambda engine, rows: captured.__setitem__("events", rows),
    )
    monkeypatch.setattr(
        publisher_mod,
        "record_quality_snapshot",
        lambda **kwargs: quality.update(kwargs),
    )

    result = publisher_mod.publish_recommendation_from_config(run_date="2026-04-14")

    assert result["as_of_date"] == "2026-04-14"
    assert result["portfolio_name"] == "cw2_core_equity"
    assert result["num_items"] == 2
    assert captured["header"]["recommendation_status"] == "proposed"
    assert captured["header"]["recommendation_version"] == "rec-v2"
    assert captured["header"]["model_version"] == "model-v2"
    assert '"recommendation_version": "rec-v2"' in captured["header"]["summary_json"]
    assert len(captured["items"]) == 2
    assert captured["items"][0]["position_action"] == "increase"
    assert captured["items"][1]["position_action"] == "new_entry"
    assert captured["events"][0]["event_type"] == "proposed"
    assert quality["dataset_name"] == "portfolio_recommendations"
    assert quality["quality_report"]["passed"] is True
    assert quality["quality_report"]["item_count_matches_header"] is True


def test_apply_recommendation_decision_updates_status_and_audit(monkeypatch):
    monkeypatch.setattr(
        publisher_mod,
        "_load_config",
        lambda _: {"recommendation": {"approval_required": True}},
    )
    monkeypatch.setattr(publisher_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(publisher_mod, "ensure_recommendation_schema", lambda engine: None)
    monkeypatch.setattr(
        publisher_mod,
        "_load_recommendation_header",
        lambda engine, recommendation_id=None, recommendation_name=None: {
            "recommendation_id": "rec-123",
            "recommendation_name": "cw2_rec",
            "recommendation_status": "proposed",
            "approved_at": None,
            "approved_by": None,
        },
    )
    captured = {"update": None, "decisions": None, "events": None}
    monkeypatch.setattr(
        publisher_mod,
        "_update_recommendation_status",
        lambda engine, row: captured.__setitem__("update", row),
    )
    monkeypatch.setattr(
        publisher_mod,
        "_write_decisions",
        lambda engine, rows: captured.__setitem__("decisions", rows),
    )
    monkeypatch.setattr(
        publisher_mod,
        "_write_events",
        lambda engine, rows: captured.__setitem__("events", rows),
    )

    result = publisher_mod.apply_recommendation_decision(
        recommendation_id="rec-123",
        decision_type="approve",
        actor="pm_user",
        notes="approved for release",
    )

    assert result["recommendation_id"] == "rec-123"
    assert result["status"] == "approved"
    assert captured["update"]["recommendation_status"] == "approved"
    assert captured["update"]["approved_by"] == "pm_user"
    assert captured["decisions"][0]["decision_type"] == "approve"
    assert captured["events"][0]["event_type"] == "approved"


def test_publish_requires_approved_when_approval_required(monkeypatch):
    with pytest.raises(ValueError):
        publisher_mod._resolve_recommendation_status_transition(
            current_status="proposed",
            decision_type="publish",
            approval_required=True,
        )


def test_load_recommendation_package_decodes_json_fields(monkeypatch):
    monkeypatch.setattr(publisher_mod, "_load_config", lambda _: {})
    monkeypatch.setattr(publisher_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(publisher_mod, "ensure_recommendation_schema", lambda engine: None)
    monkeypatch.setattr(
        publisher_mod,
        "_load_recommendation_header",
        lambda engine, recommendation_id=None, recommendation_name=None: {
            "recommendation_id": "rec-123",
            "recommendation_name": "cw2_rec",
            "summary_json": '{"top_positions": [{"symbol": "AAA"}]}',
        },
    )
    monkeypatch.setattr(
        publisher_mod,
        "_load_recommendation_items",
        lambda engine, recommendation_id: [
            {
                "symbol": "AAA",
                "rationale_json": '{"position_action": "new_entry"}',
            }
        ],
    )
    monkeypatch.setattr(
        publisher_mod,
        "_load_recommendation_events",
        lambda engine, recommendation_id: [
            {
                "event_type": "proposed",
                "payload_json": '{"num_positions": 1}',
            }
        ],
    )
    monkeypatch.setattr(
        publisher_mod,
        "_load_recommendation_decisions",
        lambda engine, recommendation_id: [],
    )

    package = publisher_mod.load_recommendation_package(recommendation_id="rec-123")

    assert package["header"]["summary_json"]["top_positions"][0]["symbol"] == "AAA"
    assert package["items"][0]["rationale_json"]["position_action"] == "new_entry"
    assert package["events"][0]["payload_json"]["num_positions"] == 1


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class _FakeRecommendationConnection:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ARG002
        return False

    def execute(self, sql, params=None):  # noqa: ANN001
        sql_text = str(sql)
        self.engine.calls.append((sql_text, params or {}))
        if "MAX(as_of_date)" in sql_text:
            return _Rows([{"as_of_date": date(2026, 3, 31)}])
        if "FROM systematic_equity.portfolio_target_positions" in sql_text:
            return _Rows(
                [
                    {
                        "symbol": "AAA",
                        "selection_rank": 1,
                        "target_weight": 0.5,
                        "weighting_scheme": "mean_variance",
                    }
                ]
            )
        if "FROM systematic_equity.feature_factor_scores" in sql_text:
            return _Rows([{"symbol": "AAA", "quality_score": 1.0}])
        if "FROM systematic_equity.feature_risk_overlay" in sql_text:
            return _Rows([{"symbol": "AAA", "pass_all": True}])
        if "FROM systematic_equity.portfolio_recommendations" in sql_text:
            return _Rows([{"recommendation_id": "rec-1", "recommendation_name": "demo"}])
        if "FROM systematic_equity.portfolio_recommendation_items" in sql_text:
            return _Rows([{"symbol": "AAA", "selection_rank": 1}])
        if "FROM systematic_equity.portfolio_recommendation_events" in sql_text:
            return _Rows([{"event_type": "proposed"}])
        if "FROM systematic_equity.portfolio_recommendation_decisions" in sql_text:
            return _Rows([{"decision_type": "approve"}])
        return _Rows([])


class _FakeRecommendationEngine:
    def __init__(self):
        self.calls = []

    def connect(self):
        return _FakeRecommendationConnection(self)


def test_recommendation_database_load_helpers_use_expected_queries():
    engine = _FakeRecommendationEngine()

    as_of = publisher_mod._resolve_recommendation_as_of_date(engine, date(2026, 4, 20), "formal")
    targets = publisher_mod._load_portfolio_targets(engine, as_of, "formal")
    empty_scores = publisher_mod._load_factor_scores(engine, as_of, [])
    scores = publisher_mod._load_factor_scores(engine, as_of, ["AAA"])
    empty_overlay = publisher_mod._load_overlay_lookup(engine, as_of, [])
    overlay = publisher_mod._load_overlay_lookup(engine, as_of, ["AAA"])
    header_by_id = publisher_mod._load_recommendation_header(engine, recommendation_id="rec-1")
    header_by_name = publisher_mod._load_recommendation_header(engine, recommendation_name="demo")
    items = publisher_mod._load_recommendation_items(engine, "rec-1")
    events = publisher_mod._load_recommendation_events(engine, "rec-1")
    decisions = publisher_mod._load_recommendation_decisions(engine, "rec-1")

    assert as_of == date(2026, 3, 31)
    assert targets[0]["symbol"] == "AAA"
    assert empty_scores == {}
    assert scores["AAA"]["quality_score"] == 1.0
    assert empty_overlay == {}
    assert overlay["AAA"]["pass_all"] is True
    assert header_by_id["recommendation_id"] == "rec-1"
    assert header_by_name["recommendation_name"] == "demo"
    assert items[0]["selection_rank"] == 1
    assert events[0]["event_type"] == "proposed"
    assert decisions[0]["decision_type"] == "approve"
    assert any("portfolio_target_positions" in sql for sql, _ in engine.calls)


def test_ensure_recommendation_schema_executes_sql():
    class _Cursor:
        def __init__(self, engine):
            self.engine = engine

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ARG002
            return False

        def execute(self, sql_text):
            self.engine.sql_text = sql_text

    class _RawConn:
        def __init__(self, engine):
            self.engine = engine

        def cursor(self):
            return _Cursor(self.engine)

        def commit(self):
            self.engine.committed = True

        def close(self):
            self.engine.closed = True

    class _Engine:
        def raw_connection(self):
            return _RawConn(self)

    engine = _Engine()

    publisher_mod.ensure_recommendation_schema(engine)

    assert "portfolio_recommendations" in engine.sql_text
    assert engine.committed is True
    assert engine.closed is True


def test_recommendation_public_apis_validate_required_arguments():
    with pytest.raises(ValueError, match="decision_type"):
        publisher_mod.apply_recommendation_decision(
            decision_type="bad",
            actor="pm_user",
            recommendation_id="rec-1",
            db_engine=object(),
        )
    with pytest.raises(ValueError, match="actor"):
        publisher_mod.apply_recommendation_decision(
            decision_type="approve",
            actor="",
            recommendation_id="rec-1",
            db_engine=object(),
        )
    with pytest.raises(ValueError, match="recommendation_id or recommendation_name"):
        publisher_mod.apply_recommendation_decision(
            decision_type="approve",
            actor="pm_user",
            db_engine=object(),
        )
    with pytest.raises(ValueError, match="recommendation_id or recommendation_name"):
        publisher_mod.load_recommendation_package(db_engine=object())


def test_publish_recommendation_validates_missing_snapshot_or_targets(monkeypatch):
    monkeypatch.setattr(
        publisher_mod,
        "_load_config",
        lambda _: {"portfolio_construction": {"portfolio_name": "formal"}},
    )
    monkeypatch.setattr(publisher_mod, "ensure_recommendation_schema", lambda engine: None)
    monkeypatch.setattr(
        publisher_mod,
        "_resolve_recommendation_as_of_date",
        lambda engine, requested_date, portfolio_name: None,
    )

    with pytest.raises(ValueError, match="No portfolio_target_positions"):
        publisher_mod.publish_recommendation_from_config(
            run_date="2026-04-20",
            db_engine=object(),
        )

    monkeypatch.setattr(
        publisher_mod,
        "_resolve_recommendation_as_of_date",
        lambda engine, requested_date, portfolio_name: date(2026, 3, 31),
    )
    monkeypatch.setattr(publisher_mod, "_load_portfolio_targets", lambda *args: [])

    with pytest.raises(ValueError, match="No non-zero portfolio_target_positions"):
        publisher_mod.publish_recommendation_from_config(
            run_date="2026-04-20",
            db_engine=object(),
        )


def test_apply_recommendation_decision_reject_clears_pending_approval(monkeypatch):
    monkeypatch.setattr(
        publisher_mod,
        "_load_config",
        lambda _: {"recommendation": {"approval_required": True}},
    )
    monkeypatch.setattr(publisher_mod, "ensure_recommendation_schema", lambda engine: None)
    monkeypatch.setattr(
        publisher_mod,
        "_load_recommendation_header",
        lambda engine, recommendation_id=None, recommendation_name=None: {
            "recommendation_id": "rec-123",
            "recommendation_name": "cw2_rec",
            "recommendation_status": "proposed",
            "approved_at": "stale",
            "approved_by": "old_pm",
        },
    )
    captured = {}
    monkeypatch.setattr(
        publisher_mod,
        "_update_recommendation_status",
        lambda engine, row: captured.update(row),
    )
    monkeypatch.setattr(publisher_mod, "_write_decisions", lambda engine, rows: None)
    monkeypatch.setattr(publisher_mod, "_write_events", lambda engine, rows: None)

    result = publisher_mod.apply_recommendation_decision(
        decision_type="reject",
        actor="pm_user",
        recommendation_id="rec-123",
        db_engine=object(),
    )

    assert result["status"] == "rejected"
    assert captured["recommendation_status"] == "rejected"
    assert captured["approved_at"] is None
    assert captured["approved_by"] is None


def test_recommendation_loaders_raise_when_header_missing(monkeypatch):
    monkeypatch.setattr(publisher_mod, "_load_config", lambda _: {})
    monkeypatch.setattr(publisher_mod, "ensure_recommendation_schema", lambda engine: None)
    monkeypatch.setattr(publisher_mod, "_load_recommendation_header", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="Recommendation not found"):
        publisher_mod.apply_recommendation_decision(
            decision_type="approve",
            actor="pm_user",
            recommendation_id="rec-missing",
            db_engine=object(),
        )

    with pytest.raises(ValueError, match="Recommendation not found"):
        publisher_mod.load_recommendation_package(
            recommendation_id="rec-missing",
            db_engine=object(),
        )


def test_recommendation_status_transition_rejects_invalid_lifecycle_moves():
    with pytest.raises(ValueError, match="immutable"):
        publisher_mod._resolve_recommendation_status_transition(
            current_status="published",
            decision_type="approve",
            approval_required=True,
        )
    with pytest.raises(ValueError, match="cannot be approved"):
        publisher_mod._resolve_recommendation_status_transition(
            current_status="rejected",
            decision_type="approve",
            approval_required=True,
        )
    with pytest.raises(ValueError, match="cannot be published"):
        publisher_mod._resolve_recommendation_status_transition(
            current_status="rejected",
            decision_type="publish",
            approval_required=False,
        )
    with pytest.raises(ValueError, match="Unsupported"):
        publisher_mod._resolve_recommendation_status_transition(
            current_status="proposed",
            decision_type="archive",
            approval_required=False,
        )
