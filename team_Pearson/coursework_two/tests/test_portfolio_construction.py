"""Unit tests for CW2 portfolio target construction."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from team_Pearson.coursework_two.modules.portfolio import construction as construction_mod
from team_Pearson.coursework_two.modules.portfolio.construction import (
    _apply_alpha_smoothing,
    _apply_min_target_weight_floor,
    _apply_weight_constraints,
    _minimum_feasible_sector_cap,
    _stabilize_optimizer_breadth,
    build_portfolio_targets,
)


def _base_inputs():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAPL",
            "composite_alpha": 1.80,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "MSFT",
            "composite_alpha": 1.70,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "NVDA",
            "composite_alpha": 1.60,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "XOM",
            "composite_alpha": 1.50,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "CVX",
            "composite_alpha": 1.40,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "JPM",
            "composite_alpha": 1.30,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": "AAPL", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "MSFT", "pass_all": True, "volatility_60d": 0.18},
        {"symbol": "NVDA", "pass_all": True, "volatility_60d": 0.30},
        {"symbol": "XOM", "pass_all": True, "volatility_60d": 0.25},
        {"symbol": "CVX", "pass_all": True, "volatility_60d": 0.22},
        {"symbol": "JPM", "pass_all": True, "volatility_60d": 0.16},
    ]
    universe_screen = [{"symbol": rec["symbol"], "pass_all": True} for rec in factor_scores]
    company_info = {
        "AAPL": {"gics_sector": "Information Technology", "country": "US"},
        "MSFT": {"gics_sector": "Information Technology", "country": "US"},
        "NVDA": {"gics_sector": "Information Technology", "country": "US"},
        "XOM": {"gics_sector": "Energy", "country": "US"},
        "CVX": {"gics_sector": "Energy", "country": "US"},
        "JPM": {"gics_sector": "Financials", "country": "US"},
    }
    return factor_scores, risk_overlay, universe_screen, company_info


def test_portfolio_targets_apply_sector_cap_and_equal_weights():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "portfolio_name": "test_portfolio",
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "equal",
            "max_single_weight": 0.30,
            "max_sector_weight": 0.50,
            "relax_sector_cap_if_needed": True,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    symbols = [row["symbol"] for row in out]
    assert len(out) == 4
    assert symbols[0] == "AAPL"
    assert len({row["selection_rank"] for row in out}) == 4
    assert {row["target_weight"] for row in out} == {0.25}


def test_portfolio_targets_support_top_percent_selection():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "top_pct",
            "top_pct": 0.50,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "equal",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.60,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    assert len(out) == 3
    assert [row["symbol"] for row in out] == ["AAPL", "MSFT", "XOM"]


def test_portfolio_targets_deduplicate_share_classes_by_issuer():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "GOOG",
            "composite_alpha": 1.90,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "GOOGL",
            "composite_alpha": 1.85,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "MSFT",
            "composite_alpha": 1.70,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "XOM",
            "composite_alpha": 1.50,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": "GOOG", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "GOOGL", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "MSFT", "pass_all": True, "volatility_60d": 0.18},
        {"symbol": "XOM", "pass_all": True, "volatility_60d": 0.25},
    ]
    universe_screen = [
        {"symbol": "GOOG", "pass_all": True, "liquidity_20d": 12_000_000.0},
        {"symbol": "GOOGL", "pass_all": True, "liquidity_20d": 11_500_000.0},
        {"symbol": "MSFT", "pass_all": True, "liquidity_20d": 15_000_000.0},
        {"symbol": "XOM", "pass_all": True, "liquidity_20d": 9_000_000.0},
    ]
    company_info = {
        "GOOG": {
            "security": "Alphabet Class C",
            "gics_sector": "Communication Services",
            "country": "US",
        },
        "GOOGL": {
            "security": "Alphabet Class A",
            "gics_sector": "Communication Services",
            "country": "US",
        },
        "MSFT": {
            "security": "Microsoft Corp",
            "gics_sector": "Information Technology",
            "country": "US",
        },
        "XOM": {
            "security": "Exxon Mobil Corp",
            "gics_sector": "Energy",
            "country": "US",
        },
    }
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "equal",
            "max_single_weight": 0.40,
            "max_sector_weight": 1.00,
            "deduplicate_issuer_positions": True,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )

    assert [row["symbol"] for row in out] == ["GOOG", "MSFT", "XOM"]
    assert "GOOGL" not in {row["symbol"] for row in out}


def test_portfolio_targets_support_hybrid_selection_mode():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "hybrid",
            "top_pct": 0.80,
            "hybrid_min_n": 2,
            "hybrid_max_n": 4,
            "min_names": 2,
            "min_candidate_pool": 2,
            "weighting": "equal",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.60,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    assert len(out) == 4


def test_alpha_smoothing_ewma_blends_current_and_historical_scores():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAPL",
            "composite_alpha": 2.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "MSFT",
            "composite_alpha": 1.0,
            "regime": "normal",
        },
    ]
    config = {
        "portfolio_construction": {
            "alpha_smoothing": {
                "enabled": True,
                "method": "ewma",
                "half_life_days": 30.0,
                "max_lookback_days": 180,
                "min_history_points": 2,
            }
        }
    }

    def _fake_history_loader(*, as_of_date, symbols, max_lookback_days):
        assert str(as_of_date) == "2026-04-14"
        assert sorted(symbols) == ["AAPL", "MSFT"]
        assert max_lookback_days == 180
        return {
            "AAPL": [
                (pd.Timestamp("2026-03-14").date(), 1.0),
                (pd.Timestamp("2026-02-14").date(), 0.0),
            ],
            "MSFT": [(pd.Timestamp("2026-03-14").date(), 0.5)],
        }

    smoothed = _apply_alpha_smoothing(
        factor_scores,
        config=config,
        history_loader=_fake_history_loader,
    )
    aapl = next(row for row in smoothed if row["symbol"] == "AAPL")
    msft = next(row for row in smoothed if row["symbol"] == "MSFT")
    weight_recent = 0.5 ** (31.0 / 30.0)
    weight_older = 0.5 ** (59.0 / 30.0)
    expected_aapl = (2.0 + weight_recent * 1.0 + weight_older * 0.0) / (
        1.0 + weight_recent + weight_older
    )
    assert aapl["raw_composite_alpha"] == pytest.approx(2.0)
    assert aapl["composite_alpha"] == pytest.approx(expected_aapl)
    assert aapl["alpha_smoothing_history_points"] == 2
    assert msft["composite_alpha"] == pytest.approx(1.0)


def test_portfolio_targets_support_score_weighting():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "score_weighted",
            "max_single_weight": 0.35,
            "max_sector_weight": 0.60,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    weights = {row["symbol"]: row["target_weight"] for row in out}
    assert math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-8)
    assert [row["symbol"] for row in out] == ["AAPL", "MSFT", "XOM", "CVX"]
    assert weights["AAPL"] > weights["MSFT"] > weights["XOM"] > weights["CVX"]


def test_portfolio_targets_support_equal_tilt_weighting():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "equal_tilt",
            "max_single_weight": 0.40,
            "max_sector_weight": 1.00,
            "alpha_tilt": {
                "signal": "composite_alpha",
                "transform": "clipped_zscore",
                "clip": 2.0,
                "budget": 0.20,
                "max_active_per_name": 0.06,
            },
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    weights = {row["symbol"]: row["target_weight"] for row in out}
    base_weight = 0.25
    assert [row["symbol"] for row in out] == ["AAPL", "MSFT", "NVDA", "XOM"]
    assert math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-8)
    assert {row["weighting_scheme"] for row in out} == {"equal_tilt"}
    assert weights["AAPL"] > weights["MSFT"] > weights["NVDA"] > weights["XOM"]
    assert all(abs(weights[sym] - base_weight) <= 0.06 + 1e-8 for sym in weights)


def test_portfolio_targets_support_inverse_vol_weighting():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "inverse_volatility",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.70,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    weights = {row["symbol"]: row["target_weight"] for row in out}
    assert [row["symbol"] for row in out] == ["AAPL", "MSFT", "NVDA", "XOM"]
    assert weights["MSFT"] > weights["AAPL"] > weights["NVDA"]
    assert weights["XOM"] > weights["NVDA"]
    assert math.isclose(
        weights["AAPL"] + weights["MSFT"] + weights["NVDA"],
        0.70,
        rel_tol=0,
        abs_tol=1e-8,
    )


def test_equal_tilt_reverts_to_equal_weights_for_flat_signal():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAA",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "BBB",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "CCC",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": "AAA", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "BBB", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "CCC", "pass_all": True, "volatility_60d": 0.20},
    ]
    universe_screen = [{"symbol": rec["symbol"], "pass_all": True} for rec in factor_scores]
    company_info = {
        "AAA": {"gics_sector": "Tech", "country": "US"},
        "BBB": {"gics_sector": "Tech", "country": "US"},
        "CCC": {"gics_sector": "Energy", "country": "US"},
    }
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "equal_tilt",
            "max_single_weight": 0.60,
            "max_sector_weight": 1.00,
            "alpha_tilt": {
                "budget": 0.20,
                "max_active_per_name": 0.10,
            },
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    weights = {row["symbol"]: row["target_weight"] for row in out}
    assert {row["weighting_scheme"] for row in out} == {"equal_tilt"}
    assert weights["AAA"] == pytest.approx(1.0 / 3.0, abs=1e-8)
    assert weights["BBB"] == pytest.approx(1.0 / 3.0, abs=1e-8)
    assert weights["CCC"] == pytest.approx(1.0 / 3.0, abs=1e-8)


def test_portfolio_targets_validate_final_sector_caps():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "score_weighted",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.55,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )

    sector_weights = {}
    for row in out:
        sector = company_info[row["symbol"]]["gics_sector"]
        sector_weights[sector] = sector_weights.get(sector, 0.0) + float(row["target_weight"])

    assert all(weight <= 0.55 + 1e-8 for weight in sector_weights.values())


def test_portfolio_targets_enforce_min_candidate_pool_guard():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 10,
            "weighting": "equal",
            "max_single_weight": 0.30,
            "max_sector_weight": 0.60,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    assert out == []


def test_portfolio_targets_support_sector_relative_ranking():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "ranking_mode": "sector_relative",
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "equal",
            "max_single_weight": 0.40,
            "max_sector_weight": 1.00,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )
    assert [row["symbol"] for row in out] == ["AAPL", "XOM", "JPM"]
    assert {row["ranking_mode"] for row in out} == {"sector_relative"}


def test_portfolio_targets_apply_turnover_cap_with_carryover_names():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    previous_positions = [
        {"symbol": "AAPL", "target_weight": 0.25},
        {"symbol": "MSFT", "target_weight": 0.25},
        {"symbol": "XOM", "target_weight": 0.25},
        {"symbol": "CVX", "target_weight": 0.25},
    ]
    config = {
        "portfolio_construction": {
            "ranking_mode": "global",
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "equal",
            "turnover_cap": 0.10,
            "max_single_weight": 0.40,
            "max_sector_weight": 0.70,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        previous_positions=previous_positions,
        config=config,
    )
    weights = {row["symbol"]: row["target_weight"] for row in out}
    selected_signal = {row["symbol"]: row["selected_signal"] for row in out}
    assert math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-8)
    assert math.isclose(weights["NVDA"], 0.08235294, rel_tol=0, abs_tol=1e-8)
    assert math.isclose(weights["CVX"], 0.16176471, rel_tol=0, abs_tol=1e-8)
    assert selected_signal["NVDA"] is True
    assert selected_signal["CVX"] is False
    assert all(row["turnover_limited"] is True for row in out)
    assert all(math.isclose(row["realized_turnover"], 0.10, rel_tol=0, abs_tol=1e-7) for row in out)


def test_portfolio_targets_retain_incumbents_within_exit_rank_buffer():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    previous_positions = [
        {"symbol": "CVX", "target_weight": 0.25},
        {"symbol": "JPM", "target_weight": 0.25},
    ]
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "equal",
            "incumbent_exit_rank": 5,
            "max_single_weight": 0.40,
            "max_sector_weight": 1.00,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        previous_positions=previous_positions,
        config=config,
    )

    symbols = [row["symbol"] for row in out]

    assert len(out) == 5
    assert symbols == ["AAPL", "MSFT", "NVDA", "XOM", "CVX"]
    assert all(row["selected_signal"] is True for row in out)


def test_portfolio_targets_support_mean_variance_weighting():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAA",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "BBB",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "CCC",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": "AAA", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "BBB", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "CCC", "pass_all": True, "volatility_60d": 0.20},
    ]
    universe_screen = [{"symbol": rec["symbol"], "pass_all": True} for rec in factor_scores]
    company_info = {
        "AAA": {"gics_sector": "Tech", "country": "US"},
        "BBB": {"gics_sector": "Tech", "country": "US"},
        "CCC": {"gics_sector": "Energy", "country": "US"},
    }
    covariance_matrix = pd.DataFrame(
        [
            [0.09, 0.085, 0.010],
            [0.085, 0.09, 0.010],
            [0.010, 0.010, 0.09],
        ],
        index=["AAA", "BBB", "CCC"],
        columns=["AAA", "BBB", "CCC"],
    )
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "mean_variance",
            "max_single_weight": 0.60,
            "max_sector_weight": 1.00,
            "covariance": {
                "alpha_signal": "composite_alpha",
                "risk_aversion": 4.0,
                "ridge_penalty": 0.05,
                "max_iter": 400,
                "tolerance": 1e-8,
            },
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        covariance_matrix=covariance_matrix,
        covariance_meta={"covariance_method": "unit_test", "lookback_days": 252},
        config=config,
    )
    weights = {row["symbol"]: row["target_weight"] for row in out}
    assert math.isclose(sum(weights.values()), 1.0, rel_tol=0, abs_tol=1e-8)
    assert {row["weighting_scheme"] for row in out} == {"mean_variance"}
    assert weights["AAA"] == pytest.approx(1.0 / 3.0, abs=1e-8)
    assert weights["BBB"] == pytest.approx(1.0 / 3.0, abs=1e-8)
    assert weights["CCC"] == pytest.approx(1.0 / 3.0, abs=1e-8)


def test_mean_variance_turnover_penalty_keeps_weights_closer_to_previous():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAA",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "BBB",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "CCC",
            "composite_alpha": 1.20,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": "AAA", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "BBB", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "CCC", "pass_all": True, "volatility_60d": 0.20},
    ]
    universe_screen = [{"symbol": rec["symbol"], "pass_all": True} for rec in factor_scores]
    company_info = {
        "AAA": {"gics_sector": "Tech", "country": "US"},
        "BBB": {"gics_sector": "Tech", "country": "US"},
        "CCC": {"gics_sector": "Energy", "country": "US"},
    }
    covariance_matrix = pd.DataFrame(
        [
            [0.09, 0.085, 0.010],
            [0.085, 0.09, 0.010],
            [0.010, 0.010, 0.09],
        ],
        index=["AAA", "BBB", "CCC"],
        columns=["AAA", "BBB", "CCC"],
    )
    previous_positions = [
        {"symbol": "AAA", "target_weight": 0.50},
        {"symbol": "BBB", "target_weight": 0.50},
    ]
    base_config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "mean_variance",
            "max_single_weight": 0.60,
            "max_sector_weight": 1.00,
            "covariance": {
                "alpha_signal": "composite_alpha",
                "risk_aversion": 4.0,
                "ridge_penalty": 0.05,
                "turnover_penalty": 0.0,
                "max_iter": 400,
                "tolerance": 1e-8,
            },
        }
    }

    out_base = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        covariance_matrix=covariance_matrix,
        covariance_meta={"covariance_method": "unit_test", "lookback_days": 252},
        previous_positions=previous_positions,
        config=base_config,
    )
    penalty_config = {
        "portfolio_construction": {
            **base_config["portfolio_construction"],
            "covariance": {
                **base_config["portfolio_construction"]["covariance"],
                "turnover_penalty": 0.25,
            },
        }
    }
    out_penalty = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        covariance_matrix=covariance_matrix,
        covariance_meta={"covariance_method": "unit_test", "lookback_days": 252},
        previous_positions=previous_positions,
        config=penalty_config,
    )

    weights_base = {row["symbol"]: row["target_weight"] for row in out_base}
    weights_penalty = {row["symbol"]: row["target_weight"] for row in out_penalty}

    turnover_base = 0.5 * sum(
        abs(weights_base.get(sym, 0.0) - prev)
        for sym, prev in {"AAA": 0.50, "BBB": 0.50, "CCC": 0.0}.items()
    )
    turnover_penalty = 0.5 * sum(
        abs(weights_penalty.get(sym, 0.0) - prev)
        for sym, prev in {"AAA": 0.50, "BBB": 0.50, "CCC": 0.0}.items()
    )

    assert turnover_penalty < turnover_base
    assert weights_penalty["AAA"] > weights_base["AAA"]
    assert weights_penalty["BBB"] > weights_base["BBB"]
    assert weights_penalty["CCC"] < weights_base["CCC"]


def test_no_trade_band_freezes_small_surviving_weight_changes_only():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAA",
            "composite_alpha": 4.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "BBB",
            "composite_alpha": 3.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "CCC",
            "composite_alpha": 2.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "DDD",
            "composite_alpha": 1.0,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": rec["symbol"], "pass_all": True, "volatility_60d": 0.20} for rec in factor_scores
    ]
    universe_screen = [{"symbol": rec["symbol"], "pass_all": True} for rec in factor_scores]
    company_info = {
        rec["symbol"]: {"gics_sector": "Tech", "country": "US"} for rec in factor_scores
    }
    previous_positions = [
        {"symbol": "AAA", "target_weight": 0.334},
        {"symbol": "BBB", "target_weight": 0.331},
        {"symbol": "DDD", "target_weight": 0.335},
    ]
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "equal",
            "max_single_weight": 0.60,
            "max_sector_weight": 1.00,
            "no_trade_band_weight": 0.005,
            "covariance": {
                "alpha_signal": "composite_alpha",
                "risk_aversion": 4.0,
                "ridge_penalty": 0.05,
                "max_iter": 400,
                "tolerance": 1e-8,
            },
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        previous_positions=previous_positions,
        config=config,
    )

    weights = {row["symbol"]: row["target_weight"] for row in out}
    assert set(weights) == {"AAA", "BBB", "CCC"}
    assert weights["AAA"] == pytest.approx(0.334, abs=1e-8)
    assert weights["BBB"] == pytest.approx(0.331, abs=1e-8)
    assert weights["CCC"] == pytest.approx(0.335, abs=1e-8)
    assert "DDD" not in weights


def test_per_name_trade_cap_clips_large_surviving_reweights():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAA",
            "composite_alpha": 4.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "BBB",
            "composite_alpha": 3.0,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": rec["symbol"], "pass_all": True, "volatility_60d": 0.20} for rec in factor_scores
    ]
    universe_screen = [{"symbol": rec["symbol"], "pass_all": True} for rec in factor_scores]
    company_info = {
        rec["symbol"]: {"gics_sector": "Tech", "country": "US"} for rec in factor_scores
    }
    previous_positions = [
        {"symbol": "AAA", "target_weight": 0.70},
        {"symbol": "BBB", "target_weight": 0.30},
    ]
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 2,
            "min_names": 2,
            "min_candidate_pool": 2,
            "weighting": "equal",
            "max_single_weight": 0.80,
            "max_sector_weight": 1.00,
            "per_name_max_trade_weight": 0.10,
            "covariance": {
                "alpha_signal": "composite_alpha",
                "risk_aversion": 4.0,
                "ridge_penalty": 0.05,
                "max_iter": 400,
                "tolerance": 1e-8,
            },
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        previous_positions=previous_positions,
        config=config,
    )

    weights = {row["symbol"]: row["target_weight"] for row in out}
    assert set(weights) == {"AAA", "BBB"}
    assert weights["AAA"] == pytest.approx(0.60, abs=1e-8)
    assert weights["BBB"] == pytest.approx(0.40, abs=1e-8)


def test_max_new_names_cap_defers_extra_entrants_with_previous_replacements():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "CCC",
            "composite_alpha": 5.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "EEE",
            "composite_alpha": 4.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAA",
            "composite_alpha": 3.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "BBB",
            "composite_alpha": 2.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "DDD",
            "composite_alpha": 1.0,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": rec["symbol"], "pass_all": True, "volatility_60d": 0.20} for rec in factor_scores
    ]
    universe_screen = [{"symbol": rec["symbol"], "pass_all": True} for rec in factor_scores]
    company_info = {
        rec["symbol"]: {"gics_sector": "Tech", "country": "US"} for rec in factor_scores
    }
    previous_positions = [
        {"symbol": "AAA", "target_weight": 0.34},
        {"symbol": "BBB", "target_weight": 0.33},
        {"symbol": "DDD", "target_weight": 0.33},
    ]
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "equal",
            "max_single_weight": 0.60,
            "max_sector_weight": 1.00,
            "max_new_names_per_rebalance": 1,
            "covariance": {
                "alpha_signal": "composite_alpha",
                "risk_aversion": 4.0,
                "ridge_penalty": 0.05,
                "max_iter": 400,
                "tolerance": 1e-8,
            },
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        previous_positions=previous_positions,
        config=config,
    )

    weights = {row["symbol"]: row["target_weight"] for row in out}
    assert set(weights) == {"AAA", "BBB", "CCC"}
    assert "EEE" not in weights


def test_mean_variance_active_overweight_cap_limits_top_name():
    factor_scores = [
        {
            "as_of_date": "2026-04-14",
            "symbol": "AAA",
            "composite_alpha": 3.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "BBB",
            "composite_alpha": 0.0,
            "regime": "normal",
        },
        {
            "as_of_date": "2026-04-14",
            "symbol": "CCC",
            "composite_alpha": -3.0,
            "regime": "normal",
        },
    ]
    risk_overlay = [
        {"symbol": "AAA", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "BBB", "pass_all": True, "volatility_60d": 0.20},
        {"symbol": "CCC", "pass_all": True, "volatility_60d": 0.20},
    ]
    universe_screen = [{"symbol": rec["symbol"], "pass_all": True} for rec in factor_scores]
    company_info = {
        "AAA": {"gics_sector": "Tech", "country": "US"},
        "BBB": {"gics_sector": "Tech", "country": "US"},
        "CCC": {"gics_sector": "Energy", "country": "US"},
    }
    covariance_matrix = pd.DataFrame(
        [
            [0.09, 0.00, 0.00],
            [0.00, 0.09, 0.00],
            [0.00, 0.00, 0.09],
        ],
        index=["AAA", "BBB", "CCC"],
        columns=["AAA", "BBB", "CCC"],
    )
    base_config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "mean_variance",
            "max_single_weight": 0.60,
            "max_sector_weight": 1.00,
            "covariance": {
                "alpha_signal": "composite_alpha",
                "risk_aversion": 0.10,
                "ridge_penalty": 0.00,
                "max_iter": 400,
                "tolerance": 1e-8,
            },
        }
    }
    capped_config = {
        "portfolio_construction": {
            **base_config["portfolio_construction"],
            "covariance": {
                **base_config["portfolio_construction"]["covariance"],
                "max_active_overweight": 0.02,
            },
        }
    }

    out_base = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        covariance_matrix=covariance_matrix,
        covariance_meta={"covariance_method": "unit_test", "lookback_days": 252},
        config=base_config,
    )
    out_capped = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        covariance_matrix=covariance_matrix,
        covariance_meta={"covariance_method": "unit_test", "lookback_days": 252},
        config=capped_config,
    )

    weights_base = {row["symbol"]: row["target_weight"] for row in out_base}
    weights_capped = {row["symbol"]: row["target_weight"] for row in out_capped}
    anchor_weight = 1.0 / 3.0

    assert weights_base["AAA"] > anchor_weight + 0.02
    assert weights_capped["AAA"] <= anchor_weight + 0.02 + 1e-8
    assert weights_capped["AAA"] < weights_base["AAA"]
    assert math.isclose(sum(weights_capped.values()), 1.0, rel_tol=0, abs_tol=1e-8)


def test_min_target_weight_floor_prunes_small_tail_positions():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    candidate_map = {
        rec["symbol"]: {
            **rec,
            "symbol": rec["symbol"],
            "gics_sector": company_info[rec["symbol"]]["gics_sector"],
        }
        for rec in factor_scores
    }
    weights = {
        "AAPL": 0.40,
        "MSFT": 0.30,
        "NVDA": 0.12,
        "XOM": 0.08,
        "CVX": 0.06,
        "JPM": 0.04,
    }

    pruned, meta = _apply_min_target_weight_floor(
        weights,
        candidate_map,
        previous_weights={},
        min_target_weight=0.10,
        min_names=3,
        max_single_weight=0.50,
        max_sector_weight=1.00,
        turnover_meta={"turnover_cap": 0.40, "realized_turnover": 0.0},
    )

    assert set(pruned) == {"AAPL", "MSFT", "NVDA"}
    assert math.isclose(sum(pruned.values()), 1.0, rel_tol=0, abs_tol=1e-8)
    assert all(weight >= 0.10 - 1e-8 for weight in pruned.values())
    assert math.isclose(meta["realized_turnover"], 0.5, rel_tol=0, abs_tol=1e-8)


def test_stabilize_optimizer_breadth_restores_minimum_active_names():
    optimized = np.array([1.0 / 21.0] * 21 + [0.0] * 4, dtype=float)
    initial = np.array([1.0 / 25.0] * 25, dtype=float)

    stabilized = _stabilize_optimizer_breadth(
        optimized,
        initial,
        min_active_names=25,
        min_weight_floor=0.001,
    )

    assert math.isclose(float(stabilized.sum()), 1.0, rel_tol=0, abs_tol=1e-10)
    assert int(np.sum(stabilized >= 0.001 - 1e-12)) >= 25


def test_minimum_feasible_sector_cap_relaxes_when_sector_capacity_is_too_tight():
    selected = [
        {"symbol": f"T{i:02d}", "gics_sector": "Tech", "ranking_score": 1.0 - i * 0.001}
        for i in range(10)
    ]
    selected += [
        {
            "symbol": f"C{i:02d}",
            "gics_sector": "Consumer",
            "ranking_score": 0.9 - i * 0.001,
        }
        for i in range(10)
    ]
    selected += [
        {
            "symbol": f"I{i:02d}",
            "gics_sector": "Industrials",
            "ranking_score": 0.8 - i * 0.001,
        }
        for i in range(3)
    ]
    selected += [
        {
            "symbol": f"H{i:02d}",
            "gics_sector": "Health",
            "ranking_score": 0.7 - i * 0.001,
        }
        for i in range(2)
    ]

    relaxed = _minimum_feasible_sector_cap(selected, 0.05)

    assert relaxed is not None
    assert relaxed > 0.25
    assert math.isclose(relaxed, 0.375, rel_tol=0, abs_tol=1e-6)


def test_portfolio_targets_expand_selection_when_fixed_target_is_capacity_infeasible():
    factor_scores = []
    risk_overlay = []
    universe_screen = []
    company_info = {}

    def add_symbol(symbol: str, alpha: float, sector: str) -> None:
        factor_scores.append(
            {
                "as_of_date": "2026-04-14",
                "symbol": symbol,
                "composite_alpha": alpha,
                "regime": "normal",
            }
        )
        risk_overlay.append({"symbol": symbol, "pass_all": True, "volatility_60d": 0.20})
        universe_screen.append({"symbol": symbol, "pass_all": True})
        company_info[symbol] = {"gics_sector": sector, "country": "US"}

    alpha = 2.0
    for i in range(10):
        add_symbol(f"T{i:02d}", alpha, "Tech")
        alpha -= 0.01
    for i in range(10):
        add_symbol(f"C{i:02d}", alpha, "Consumer")
        alpha -= 0.01
    for i in range(3):
        add_symbol(f"I{i:02d}", alpha, "Industrials")
        alpha -= 0.01
    for i in range(2):
        add_symbol(f"H{i:02d}", alpha, "Health")
        alpha -= 0.01
    for i in range(2):
        add_symbol(f"IX{i:02d}", alpha, "Industrials")
        alpha -= 0.01
    for i in range(3):
        add_symbol(f"HX{i:02d}", alpha, "Health")
        alpha -= 0.01

    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 25,
            "min_names": 25,
            "min_candidate_pool": 25,
            "weighting": "equal",
            "max_single_weight": 0.05,
            "max_sector_weight": 0.25,
            "relax_sector_cap_if_needed": True,
        }
    }

    out = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
    )

    assert len(out) >= 25
    assert math.isclose(
        sum(float(row["target_weight"]) for row in out),
        1.0,
        rel_tol=0,
        abs_tol=1e-6,
    )

    sector_weights = {}
    for row in out:
        sector = company_info[row["symbol"]]["gics_sector"]
        sector_weights[sector] = sector_weights.get(sector, 0.0) + float(row["target_weight"])
    assert all(weight <= 0.25 + 1e-6 for weight in sector_weights.values())


def test_apply_weight_constraints_respects_member_headroom_inside_receiving_sector():
    sector_specs = [
        (
            "Consumer Discretionary",
            [
                0.05087478,
                0.04998022,
                0.04966105,
                0.04939541,
                0.04938223,
                0.04914070,
                0.00108664,
            ],
        ),
        (
            "Information Technology",
            [0.05150670, 0.04995973, 0.04921535, 0.04913017, 0.03004995, 0.02001502],
        ),
        ("Health Care", [0.05017624, 0.04993044, 0.04989877, 0.04917955]),
        ("Energy", [0.04927277, 0.00100000]),
        ("Consumer Staples", [0.05074129]),
        ("Financials", [0.04997378]),
        ("Communication Services", [0.04935809]),
        ("Real Estate", [0.04901524]),
        ("Industrials", [0.00103417]),
        ("Materials", [0.00102170]),
    ]

    selected = []
    raw_preferences = {}
    symbol_idx = 0
    for sector, weights in sector_specs:
        for weight in weights:
            symbol = f"S{symbol_idx:02d}"
            symbol_idx += 1
            selected.append({"symbol": symbol, "gics_sector": sector})
            raw_preferences[symbol] = weight

    constrained = _apply_weight_constraints(
        selected,
        raw_preferences,
        max_single_weight=0.05,
        max_sector_weight=0.25,
    )

    assert math.isclose(sum(constrained.values()), 1.0, rel_tol=0, abs_tol=1e-6)
    sector_weights = {}
    for rec in selected:
        symbol = rec["symbol"]
        sector = rec["gics_sector"]
        sector_weights[sector] = sector_weights.get(sector, 0.0) + constrained.get(symbol, 0.0)
    assert all(weight <= 0.25 + 1e-6 for weight in sector_weights.values())


def test_portfolio_targets_return_diagnostics_capture_constraint_deltas():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "score_weighted",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.50,
        }
    }

    out, diagnostics = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
        return_diagnostics=True,
    )

    assert len(out) == 4
    by_symbol = {row["symbol"]: row for row in diagnostics.records}
    assert by_symbol["AAPL"]["raw_preference_weight"] > by_symbol["MSFT"]["raw_preference_weight"]
    assert by_symbol["AAPL"]["pre_constraint_weight"] > by_symbol["AAPL"]["constrained_weight"]
    assert by_symbol["AAPL"]["sector_cap_binding"] is True
    assert diagnostics.summary["constraint_binding_counts"]["sector_cap"] >= 1


def test_portfolio_targets_return_diagnostics_capture_sector_diversification_drop():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "equal",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.34,
            "relax_sector_cap_if_needed": True,
        }
    }

    out, diagnostics = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
        return_diagnostics=True,
    )

    assert [row["symbol"] for row in out] == ["AAPL", "XOM", "JPM"]
    by_symbol = {row["symbol"]: row for row in diagnostics.records}
    assert by_symbol["MSFT"]["selection_drop_reason"] == "sector_diversification"
    assert by_symbol["NVDA"]["selection_drop_reason"] == "sector_diversification"
    assert diagnostics.summary["drop_reason_counts"]["sector_diversification"] >= 1


def test_portfolio_targets_return_diagnostics_when_relaxed_sector_retry_fails(
    monkeypatch,
):
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "score_weighted",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.25,
            "relax_sector_cap_if_needed": True,
        }
    }

    calls = {"count": 0}
    original_constraints = construction_mod._apply_weight_constraints

    def _flaky_constraints(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise ValueError("no capacity available for mass allocation")
        return original_constraints(*args, **kwargs)

    monkeypatch.setattr(
        construction_mod,
        "_apply_weight_constraints",
        _flaky_constraints,
    )
    monkeypatch.setattr(
        construction_mod,
        "_minimum_feasible_sector_cap",
        lambda *_args, **_kwargs: 0.30,
    )

    out, diagnostics = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
        return_diagnostics=True,
    )

    assert out == []
    assert calls["count"] == 2
    assert diagnostics.summary["status"] == "constraint_application_failed"


def test_portfolio_targets_return_diagnostics_when_selection_below_minimum():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    company_info = {
        symbol: {**info, "gics_sector": "Information Technology"}
        for symbol, info in company_info.items()
    }
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 4,
            "min_names": 4,
            "min_candidate_pool": 4,
            "weighting": "equal",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.25,
            "relax_sector_cap_if_needed": False,
        }
    }

    out, diagnostics = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
        return_diagnostics=True,
    )

    assert out == []
    assert diagnostics.summary["status"] == "selected_names_below_minimum"
    assert diagnostics.summary["selected_signal_count"] < 4


def test_portfolio_targets_return_diagnostics_when_constraints_fail_without_relaxation():
    factor_scores, risk_overlay, universe_screen, company_info = _base_inputs()
    config = {
        "portfolio_construction": {
            "selection_mode": "fixed_n",
            "top_n": 3,
            "min_names": 3,
            "min_candidate_pool": 3,
            "weighting": "equal",
            "max_single_weight": 0.40,
            "max_sector_weight": 0.20,
            "relax_sector_cap_if_needed": False,
        }
    }

    out, diagnostics = build_portfolio_targets(
        factor_scores,
        risk_overlay,
        universe_screen,
        company_info,
        config=config,
        return_diagnostics=True,
    )

    assert out == []
    assert diagnostics.summary["status"] == "constraint_application_failed"
    assert diagnostics.summary["requested_weighting"] == "equal"


def test_weighting_schemes_cover_tilt_and_optimizer_fallback_paths():
    candidates = [
        {"symbol": "AAA", "composite_alpha": 2.0, "gics_sector": "Tech"},
        {"symbol": "BBB", "composite_alpha": 1.0, "gics_sector": "Health Care"},
        {"symbol": "CCC", "composite_alpha": -1.0, "gics_sector": "Energy"},
    ]
    risk_lookup = {
        "AAA": {"volatility_60d": 0.20},
        "BBB": {"volatility_60d": 0.30},
        "CCC": {"volatility_60d": 0.40},
    }

    assert construction_mod.EqualTiltScheme().compute_raw_weights([], risk_lookup).raw_weights == {}

    flat_tilt = construction_mod.EqualTiltScheme().compute_raw_weights(
        [{"symbol": "BAD", "composite_alpha": "not-a-number"}],
        risk_lookup,
    )
    assert flat_tilt.applied_scheme == "equal_tilt"
    assert flat_tilt.metadata["tilt_applied"] is False
    assert flat_tilt.metadata["tilt_reason"] == "flat_signal_or_zero_budget"

    tilted = construction_mod.EqualTiltScheme().compute_raw_weights(
        candidates,
        risk_lookup,
        config={
            "portfolio_construction": {
                "alpha_tilt": {
                    "signal": "composite_alpha",
                    "budget": 0.30,
                    "max_active_per_name": 0.20,
                }
            }
        },
        optimization_context={"max_single_weight": 0.60},
    )
    assert tilted.applied_scheme == "equal_tilt"
    assert tilted.metadata["tilt_applied"] is True
    assert tilted.raw_weights["AAA"] > tilted.raw_weights["CCC"]

    optimizer = construction_mod.MeanVarianceScheme()
    fallback = optimizer.compute_raw_weights(
        candidates,
        risk_lookup,
        config={
            "portfolio_construction": {
                "covariance": {"alpha_signal": "composite_alpha"},
            }
        },
        optimization_context={"max_single_weight": 0.20},
    )
    assert fallback.metadata["optimizer_requested"] == "mean_variance"
    assert fallback.metadata["fallback_reason"] == "single_name_cap_infeasible"

    covariance = pd.DataFrame(
        [[0.04, 0.01, 0.00], [0.01, 0.05, 0.00], [0.00, 0.00, 0.06]],
        index=["AAA", "BBB", "CCC"],
        columns=["AAA", "BBB", "CCC"],
    )
    optimized = optimizer.compute_raw_weights(
        candidates,
        risk_lookup,
        config={
            "portfolio_construction": {
                "min_names": 3,
                "covariance": {
                    "alpha_signal": "composite_alpha",
                    "risk_aversion": 2.0,
                    "ridge_penalty": 0.05,
                    "max_iter": 100,
                    "annualize_covariance": False,
                },
            }
        },
        optimization_context={
            "covariance_matrix": covariance,
            "max_single_weight": 0.80,
            "max_sector_weight": 1.00,
            "reference_weights": {"AAA": 0.50, "BBB": 0.30, "CCC": 0.20},
            "sector_map": {"AAA": "Tech", "BBB": "Health Care", "CCC": "Energy"},
        },
    )
    assert optimized.applied_scheme == "mean_variance"
    assert math.isclose(sum(optimized.raw_weights.values()), 1.0, abs_tol=1e-8)
    assert optimized.metadata["reference_weights_available"] is True


def test_weighting_scheme_defensive_fallback_paths(monkeypatch):
    candidates = [
        {"symbol": "AAA", "composite_alpha": 2.0, "gics_sector": "Tech"},
        {"symbol": "BBB", "composite_alpha": 1.0, "gics_sector": "Health Care"},
        {"symbol": "CCC", "composite_alpha": -1.0, "gics_sector": "Energy"},
    ]
    risk_lookup = {rec["symbol"]: {"volatility_60d": 0.20} for rec in candidates}

    one_sided_tilt = construction_mod.EqualTiltScheme().compute_raw_weights(
        candidates,
        risk_lookup,
        config={
            "portfolio_construction": {
                "alpha_tilt": {
                    "budget": 0.30,
                    "max_active_per_name": 0.20,
                }
            }
        },
        optimization_context={"max_single_weight": 1.0 / 3.0},
    )
    assert one_sided_tilt.metadata["tilt_reason"] == "one_sided_signal"

    optimizer = construction_mod.MeanVarianceScheme()
    assert optimizer.compute_raw_weights([], risk_lookup).raw_weights == {}

    anchor_failed = optimizer.compute_raw_weights(
        candidates,
        risk_lookup,
        config={
            "portfolio_construction": {
                "covariance": {"anchor_scheme": "inverse_volatility"},
            }
        },
        optimization_context={"max_single_weight": 0.80, "max_sector_weight": 0.20},
    )
    assert anchor_failed.metadata["fallback_reason"] == "anchor_construction_failed"

    monkeypatch.setattr(
        construction_mod, "_solve_mean_variance_weights", lambda *args, **kwargs: None
    )
    optimizer_failed = optimizer.compute_raw_weights(
        candidates,
        risk_lookup,
        config={
            "portfolio_construction": {
                "covariance": {"annualize_covariance": False},
            }
        },
        optimization_context={"max_single_weight": 0.80, "max_sector_weight": 1.00},
    )
    assert optimizer_failed.metadata["fallback_reason"] == "optimizer_failed"


def test_portfolio_helper_guards_and_ranking_modes():
    candidates = [
        {"symbol": "AAA", "composite_alpha": 3.0, "gics_sector": "Tech"},
        {"symbol": "BBB", "composite_alpha": 2.0, "gics_sector": "Tech"},
        {"symbol": "CCC", "composite_alpha": 1.0, "gics_sector": "Energy"},
    ]

    assert (
        construction_mod._select_candidates_with_sector_diversification(
            candidates,
            target_count=0,
            max_sector_weight=0.50,
            relax_sector_cap=True,
        )
        == []
    )
    assert (
        construction_mod._select_candidates_with_sector_diversification(
            candidates,
            target_count=2,
            max_sector_weight=None,
            relax_sector_cap=False,
        )
        == candidates[:2]
    )

    with pytest.raises(ValueError, match="Invalid top_pct"):
        construction_mod._resolve_target_count(
            candidate_count=3,
            selection_mode="top_pct",
            cfg={"top_pct": 1.5},
            min_names=1,
        )
    with pytest.raises(ValueError, match="Unsupported selection_mode"):
        construction_mod._resolve_target_count(
            candidate_count=3,
            selection_mode="bottom_n",
            cfg={},
            min_names=1,
        )
    with pytest.raises(ValueError, match="Unsupported ranking_mode"):
        construction_mod._annotate_ranking_scores(
            candidates,
            ranking_mode="unknown",
            blend_global_weight=0.5,
        )

    blended = construction_mod._annotate_ranking_scores(
        candidates,
        ranking_mode="blended",
        blend_global_weight=2.0,
    )
    assert blended[0]["ranking_score"] == pytest.approx(blended[0]["global_rank_score"])
    assert construction_mod._canonical_issuer_security_name("Alphabet Class A") == "alphabet"
    assert construction_mod._issuer_key_for_candidate({"symbol": "GOOG", "security": ""}) == "GOOG"


def test_portfolio_targets_filter_invalid_candidates_to_empty_diagnostics():
    out, diagnostics = build_portfolio_targets(
        [
            {"symbol": "", "composite_alpha": 1.0},
            {"symbol": "BAD_ALPHA", "composite_alpha": "not-a-number"},
            {"symbol": "NAN", "composite_alpha": float("nan")},
            {"symbol": "RISK_FAIL", "composite_alpha": 1.0},
            {"symbol": "UNIVERSE_FAIL", "composite_alpha": 1.0},
        ],
        [{"symbol": "RISK_FAIL", "pass_all": False}, {"symbol": "UNIVERSE_FAIL", "pass_all": True}],
        [
            {"symbol": "RISK_FAIL", "pass_all": True},
            {"symbol": "UNIVERSE_FAIL", "pass_all": False},
        ],
        {},
        config={"portfolio_construction": {"weighting": "equal"}},
        return_diagnostics=True,
    )

    assert out == []
    assert diagnostics.summary["status"] == "no_eligible_candidates"
    assert diagnostics.summary["candidate_count"] == 0


def test_trade_control_helpers_apply_caps_and_bands():
    candidate_map = {
        "AAA": {"symbol": "AAA", "gics_sector": "Tech", "composite_alpha": 3.0},
        "BBB": {"symbol": "BBB", "gics_sector": "Energy", "composite_alpha": 2.0},
        "CCC": {"symbol": "CCC", "gics_sector": "Health Care", "composite_alpha": 1.0},
    }
    target = {"AAA": 0.60, "BBB": 0.30, "CCC": 0.10}
    previous = {"AAA": 0.55, "BBB": 0.25, "CCC": 0.20}

    no_trade, no_trade_meta = construction_mod._apply_no_trade_band(
        target,
        candidate_map,
        previous,
        no_trade_band_weight=0.06,
        max_single_weight=0.80,
        max_sector_weight=1.00,
    )
    assert no_trade_meta["no_trade_band_applied"] is True
    assert no_trade["AAA"] == pytest.approx(0.55)

    trade_capped, trade_cap_meta = construction_mod._apply_per_name_trade_cap(
        target,
        candidate_map,
        previous,
        per_name_max_trade_weight=0.05,
        max_single_weight=0.80,
        max_sector_weight=1.00,
    )
    assert trade_cap_meta["per_name_max_trade_applied"] is True
    assert abs(trade_capped["CCC"] - previous["CCC"]) <= 0.05 + 1e-8

    turnover_limited, turnover_meta = construction_mod._apply_turnover_overlay(
        target,
        candidate_map,
        previous,
        turnover_cap=0.04,
        max_single_weight=0.80,
        max_sector_weight=1.00,
    )
    assert turnover_meta["turnover_limited"] is True
    assert construction_mod._portfolio_turnover(previous, turnover_limited) <= 0.04 + 1e-8

    projected = construction_mod._project_weight_map_to_bounded_simplex(
        {"AAA": 0.90, "BBB": 0.05, "CCC": 0.05},
        lower_bounds={"AAA": 0.30, "BBB": 0.20, "CCC": 0.10},
        upper_bounds={"AAA": 0.70, "BBB": 0.60, "CCC": 0.50},
    )
    assert math.isclose(sum(projected.values()), 1.0, abs_tol=1e-10)

    with pytest.raises(ValueError, match="bounded simplex is infeasible"):
        construction_mod._project_weight_map_to_bounded_simplex(
            {"AAA": 1.0},
            lower_bounds={"AAA": 1.2},
            upper_bounds={"AAA": 1.0},
        )


def test_selection_and_floor_helpers_handle_capacity_and_incumbents():
    candidates = [
        {"symbol": "AAA", "composite_alpha": 5.0, "ranking_score": 1.0, "gics_sector": "Tech"},
        {"symbol": "BBB", "composite_alpha": 4.0, "ranking_score": 0.8, "gics_sector": "Tech"},
        {"symbol": "CCC", "composite_alpha": 3.0, "ranking_score": 0.6, "gics_sector": "Tech"},
        {"symbol": "DDD", "composite_alpha": 2.0, "ranking_score": 0.4, "gics_sector": "Energy"},
        {
            "symbol": "EEE",
            "composite_alpha": 1.0,
            "ranking_score": 0.2,
            "gics_sector": "Health Care",
        },
    ]
    selected = candidates[:3]

    repaired = construction_mod._repair_selection_for_capacity(
        candidates,
        selected,
        target_count=3,
        max_single_weight=0.40,
        max_sector_weight=0.50,
    )
    assert {rec["symbol"] for rec in repaired} == {"AAA", "DDD", "EEE"}

    buffered = construction_mod._apply_incumbent_exit_buffer(
        candidates,
        selected=[candidates[0], candidates[3]],
        previous_weights={"BBB": 0.20, "CCC": 0.20, "DDD": 0.20},
        incumbent_exit_rank=3,
    )
    assert {rec["symbol"] for rec in buffered} == {"AAA", "BBB", "CCC"}

    capped, meta = construction_mod._apply_new_name_cap(
        candidates,
        selected=candidates[:4],
        previous_weights={"AAA": 0.40, "DDD": 0.30},
        max_new_names_per_rebalance=1,
    )
    assert meta["new_name_cap_applied"] is True
    assert {rec["symbol"] for rec in capped} == {"AAA", "BBB", "DDD"}

    floored, floor_meta = construction_mod._apply_min_target_weight_floor(
        {"AAA": 0.70, "BBB": 0.20, "CCC": 0.05, "DDD": 0.05},
        {rec["symbol"]: rec for rec in candidates},
        previous_weights={"AAA": 0.50, "BBB": 0.30, "CCC": 0.10, "DDD": 0.10},
        min_target_weight=0.10,
        min_names=2,
        max_single_weight=0.80,
        max_sector_weight=1.00,
        turnover_meta={},
    )
    assert set(floored) == {"AAA", "BBB"}
    assert floor_meta["realized_turnover"] >= 0.0


def test_covariance_and_optimizer_numeric_guards():
    risk_lookup = {"AAA": {"volatility_60d": 0.20}, "BBB": {"volatility_60d": 0.30}}
    cov = construction_mod._build_candidate_covariance_matrix(
        ["AAA", "BBB", "CCC"],
        pd.DataFrame([[0.04]], index=["AAA"], columns=["AAA"]),
        risk_lookup,
    )
    assert list(cov.index) == ["AAA", "BBB", "CCC"]
    assert np.all(np.linalg.eigvalsh(cov.to_numpy()) > 0.0)

    assert construction_mod._reference_weight_vector([], {"AAA": 1.0}) is None
    assert construction_mod._reference_weight_vector(["AAA"], None) is None
    assert construction_mod._active_weight_bounds(
        np.array([0.6, 0.4]),
        np.array([0.5]),
        max_active_overweight=None,
        max_active_underweight=None,
    ) == (None, None)
    assert construction_mod._optimizer_breadth_floor(
        min_target_weight=None,
        max_single_weight=0.20,
    ) == pytest.approx(0.001)
    stabilized = construction_mod._stabilize_optimizer_breadth(
        np.array([0.98, 0.01, 0.01]),
        np.array([0.50, 0.30, 0.20]),
        min_active_names=3,
        min_weight_floor=0.05,
    )
    assert np.sum(stabilized >= 0.05 - 1e-12) == 3

    assert (
        construction_mod._solve_mean_variance_weights(
            np.array([]),
            np.empty((0, 0)),
            np.array([]),
            risk_aversion=1.0,
            ridge_penalty=0.0,
            turnover_penalty=0.0,
            reference_weights=None,
            anchor_weights=np.array([]),
            use_active_risk=True,
            max_iter=10,
            tolerance=1e-8,
            configured_step_size=None,
            initial_weights=np.array([]),
            lower_bounds=None,
            upper_bounds=None,
        )
        is None
    )
    assert (
        construction_mod._project_to_capped_simplex(
            np.array([0.5, 0.5]),
            np.array([0.4, 0.4]),
            total_weight=1.0,
        )
        is None
    )
    assert construction_mod._safe_float("bad") is None
    assert construction_mod._median([]) == 1.0


def test_alpha_smoothing_edge_paths():
    records = [{"symbol": "AAA", "composite_alpha": 1.0, "as_of_date": "2026-04-20"}]
    with pytest.raises(ValueError, match="Unsupported alpha_smoothing.method"):
        _apply_alpha_smoothing(
            records,
            config={
                "portfolio_construction": {
                    "alpha_smoothing": {"enabled": True, "method": "simple_average"}
                }
            },
        )

    assert _apply_alpha_smoothing(
        [{"symbol": "AAA", "composite_alpha": 1.0}],
        config={"portfolio_construction": {"alpha_smoothing": {"enabled": True}}},
    ) == [{"symbol": "AAA", "composite_alpha": 1.0}]

    assert _apply_alpha_smoothing(
        [{"symbol": "", "composite_alpha": 1.0, "as_of_date": "2026-04-20"}],
        config={"portfolio_construction": {"alpha_smoothing": {"enabled": True}}},
    ) == [{"symbol": "", "composite_alpha": 1.0, "as_of_date": "2026-04-20"}]

    smoothed = _apply_alpha_smoothing(
        records,
        config={
            "portfolio_construction": {
                "alpha_smoothing": {
                    "enabled": True,
                    "half_life_days": 30,
                    "max_lookback_days": 60,
                    "min_history_points": 1,
                }
            }
        },
        history_loader=lambda **kwargs: {"AAA": [(date(2026, 3, 20), 0.0)]},
    )
    assert smoothed[0]["raw_composite_alpha"] == 1.0
    assert smoothed[0]["composite_alpha"] < 1.0
    assert smoothed[0]["alpha_smoothing_history_points"] == 1
