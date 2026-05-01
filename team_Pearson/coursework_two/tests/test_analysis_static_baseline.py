"""Unit tests for static baseline analysis helpers."""

from __future__ import annotations

from datetime import date

from team_Pearson.coursework_two.modules.analysis import static_baseline as baseline_mod


def test_build_static_baseline_preserves_as_of_date_for_portfolio_construction(
    monkeypatch,
):
    run_context = {
        "run_id": "run-1",
        "config": {
            "regime": {
                "normal": {
                    "quality": 0.2,
                    "value": 0.2,
                    "market_technical": 0.3,
                    "sentiment": 0.2,
                    "dividend": 0.1,
                }
            }
        },
        "analysis_config": {
            "static_baseline_normal_weights": {"quality": 1.0},
            "static_baseline_cost_bps": 15,
        },
        "run_row": {
            "start_date": date(2026, 2, 1),
            "end_date": date(2026, 4, 14),
            "benchmark_ticker": "SPY",
        },
        "periods": [
            {
                "rebalance_date": date(2026, 2, 27),
                "execution_date": date(2026, 2, 28),
                "period_end_date": date(2026, 4, 1),
            }
        ],
    }
    monkeypatch.setattr(baseline_mod, "load_trading_calendar", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        baseline_mod,
        "_load_static_inputs",
        lambda *args, **kwargs: {
            date(2026, 2, 27): {
                "factor_scores": [
                    {
                        "as_of_date": date(2026, 2, 27),
                        "symbol": "AAA",
                        "quality_score": 1.0,
                        "value_score": 0.5,
                        "market_technical_score": 0.2,
                        "sentiment_score": 0.1,
                        "dividend_score": 0.0,
                    }
                ],
                "risk_overlay": [{"symbol": "AAA", "pass_all": True}],
                "universe_screen": [
                    {
                        "symbol": "AAA",
                        "pass_all": True,
                        "country": "US",
                        "gics_sector": "Tech",
                    }
                ],
                "company_info": {"AAA": {"country": "US", "gics_sector": "Tech"}},
            }
        },
    )
    captured = {"scores": None}

    def _fake_build_portfolio_targets(scores, *args, **kwargs):
        captured["scores"] = scores
        return [{"symbol": "AAA", "target_weight": 1.0}]

    monkeypatch.setattr(baseline_mod, "build_portfolio_targets", _fake_build_portfolio_targets)
    monkeypatch.setattr(baseline_mod, "load_adjusted_close_prices", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        baseline_mod, "compute_period_simple_returns", lambda *args, **kwargs: ({}, {})
    )
    monkeypatch.setattr(baseline_mod, "compute_drifted_weights", lambda *args, **kwargs: {})
    monkeypatch.setattr(baseline_mod, "compute_turnover", lambda *args, **kwargs: (0.0, {}))
    monkeypatch.setattr(baseline_mod, "transaction_cost_from_turnover", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(baseline_mod, "compute_gross_return", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(baseline_mod, "compute_net_return", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(baseline_mod, "update_nav", lambda nav, gross, cost: nav)

    baseline_mod.build_static_baseline_path(
        run_context,
        db_engine=object(),
        period_regimes={},
    )

    assert captured["scores"][0]["as_of_date"] == date(2026, 2, 27)


def test_recompute_static_alpha_forces_normal_regime(monkeypatch):
    captured = {}

    def _fake_compute(records, vix_level, config, forced_regime=None):
        captured["forced_regime"] = forced_regime
        return records

    monkeypatch.setattr(baseline_mod, "compute_composite_alpha", _fake_compute)

    out = baseline_mod._recompute_static_alpha(
        [
            {
                "as_of_date": date(2026, 2, 27),
                "symbol": "AAA",
                "quality_score": 1.0,
            }
        ],
        {"regime": {}},
    )

    assert out[0]["symbol"] == "AAA"
    assert captured["forced_regime"] == "normal"
