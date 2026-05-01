from __future__ import annotations

import pytest
from team_Pearson.coursework_two.modules.utils.config_contract import (
    evaluate_upstream_history_contract,
    validate_shared_runtime_contract,
)


def test_validate_shared_runtime_contract_accepts_matching_parent_child_scope():
    contract = validate_shared_runtime_contract(
        {
            "universe": {"country_allowlist": ["US", "CA"]},
            "market_factors": {"benchmark_ticker": "SPY"},
        },
        {
            "investable_universe": {"country_allowlist": ["US"]},
            "backtest": {"benchmark_ticker": "SPY"},
        },
    )

    assert contract == {
        "shared_benchmark_ticker": "SPY",
        "cw1_upstream_country_allowlist": ["CA", "US"],
        "cw2_investable_country_allowlist": ["US"],
        "effective_investable_country_allowlist": ["US"],
    }


def test_validate_shared_runtime_contract_rejects_benchmark_mismatch():
    with pytest.raises(ValueError, match="benchmark_ticker must match"):
        validate_shared_runtime_contract(
            {"market_factors": {"benchmark_ticker": "SPY"}},
            {"backtest": {"benchmark_ticker": "QQQ"}},
        )


def test_validate_shared_runtime_contract_rejects_country_superset():
    with pytest.raises(ValueError, match="must be a subset"):
        validate_shared_runtime_contract(
            {"universe": {"country_allowlist": ["US"]}},
            {"investable_universe": {"country_allowlist": ["US", "CA"]}},
        )


def test_evaluate_upstream_history_contract_rejects_shorter_backfill_than_backtest():
    with pytest.raises(ValueError, match="must be at least as large as the CW2 backtest window"):
        evaluate_upstream_history_contract(
            {
                "pipeline": {"backfill_years": 4},
                "market_factors": {"beta_window_days": 252},
            },
            {
                "backtest": {
                    "lookback_years": 5,
                    "intraday_triggers": {"stop_loss_vol_lookback_days": 20},
                },
                "portfolio_construction": {"covariance": {"lookback_days": 252}},
                "regime": {"history_lookback_days": 60},
            },
        )


def test_evaluate_upstream_history_contract_warns_when_no_warmup_buffer():
    report = evaluate_upstream_history_contract(
        {
            "pipeline": {"backfill_years": 5},
            "market_factors": {"beta_window_days": 252},
        },
        {
            "backtest": {
                "lookback_years": 5,
                "intraday_triggers": {"stop_loss_vol_lookback_days": 20},
            },
            "portfolio_construction": {"covariance": {"lookback_days": 252}},
            "regime": {"history_lookback_days": 60},
        },
    )

    assert report["cw1_backfill_years"] == 5
    assert report["cw2_lookback_years"] == 5
    assert report["recommended_backfill_years"] == 6
    assert "Recommended backfill_years >= 6" in str(report["warning"])


def test_evaluate_upstream_history_contract_clears_warning_with_buffer():
    report = evaluate_upstream_history_contract(
        {
            "pipeline": {"backfill_years": 6},
            "market_factors": {"beta_window_days": 252},
        },
        {
            "backtest": {
                "lookback_years": 5,
                "intraday_triggers": {"stop_loss_vol_lookback_days": 20},
            },
            "portfolio_construction": {"covariance": {"lookback_days": 252}},
            "regime": {"history_lookback_days": 60},
        },
    )

    assert report["recommended_backfill_years"] == 6
    assert report["warning"] is None
