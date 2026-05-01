"""Regression tests for CW2 config validation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from team_Pearson.coursework_two.modules.utils.config_validation import CW2Config, load_cw2_config

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "conf.yaml"


def _load_raw_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_load_cw2_config_uses_institutional_hybrid_defaults():
    cfg = load_cw2_config(str(CONFIG_PATH))
    portfolio_cfg = cfg["portfolio_construction"]

    assert portfolio_cfg["selection_mode"] == "hybrid"
    assert portfolio_cfg["top_pct"] == pytest.approx(0.12)
    assert portfolio_cfg["hybrid_min_n"] == 25
    assert portfolio_cfg["hybrid_max_n"] == 35
    assert portfolio_cfg["min_names"] == 25
    assert portfolio_cfg["min_candidate_pool"] == 25
    assert portfolio_cfg["min_target_weight"] == pytest.approx(0.005)
    assert portfolio_cfg["max_single_weight"] == pytest.approx(0.05)
    assert cfg["pipeline_guards"]["min_investable_universe"] == 25
    assert cfg["quality_gates"]["min_portfolio_targets"] == 25
    assert cfg["backtest"]["min_eligible_universe"] == 25


def test_portfolio_config_rejects_invalid_hybrid_bounds():
    raw = _load_raw_config()
    raw["portfolio_construction"]["hybrid_min_n"] = 51
    raw["portfolio_construction"]["hybrid_max_n"] = 50

    with pytest.raises(ValidationError, match="hybrid_min_n cannot exceed hybrid_max_n"):
        CW2Config.model_validate(raw)


def test_portfolio_config_rejects_fixed_n_below_required_minimum_names():
    raw = _load_raw_config()
    portfolio_cfg = raw["portfolio_construction"]
    portfolio_cfg["selection_mode"] = "fixed_n"
    portfolio_cfg["top_n"] = 20
    portfolio_cfg["min_names"] = 25

    with pytest.raises(
        ValidationError,
        match="min_names cannot exceed top_n when selection_mode=fixed_n",
    ):
        CW2Config.model_validate(raw)


def test_portfolio_config_requires_enough_single_name_capacity():
    raw = _load_raw_config()
    raw["portfolio_construction"]["max_single_weight"] = 0.03

    with pytest.raises(
        ValidationError,
        match="max_single_weight and min_names must provide enough aggregate capacity",
    ):
        CW2Config.model_validate(raw)


def test_portfolio_config_rejects_min_target_weight_above_single_name_cap():
    raw = _load_raw_config()
    raw["portfolio_construction"]["min_target_weight"] = 0.06

    with pytest.raises(
        ValidationError,
        match="min_target_weight cannot exceed max_single_weight",
    ):
        CW2Config.model_validate(raw)


def test_config_rejects_pipeline_guard_below_candidate_floor():
    raw = _load_raw_config()
    raw["pipeline_guards"]["min_investable_universe"] = 24

    with pytest.raises(
        ValidationError,
        match="pipeline_guards.min_investable_universe cannot be below "
        "portfolio_construction.min_candidate_pool",
    ):
        CW2Config.model_validate(raw)


def test_config_rejects_quality_gate_below_portfolio_minimum():
    raw = _load_raw_config()
    raw["quality_gates"]["min_portfolio_targets"] = 24

    with pytest.raises(
        ValidationError,
        match="quality_gates.min_portfolio_targets cannot be below "
        "portfolio_construction.min_names",
    ):
        CW2Config.model_validate(raw)


def test_config_rejects_backtest_floor_below_portfolio_minimum():
    raw = _load_raw_config()
    raw["backtest"]["min_eligible_universe"] = 24

    with pytest.raises(
        ValidationError,
        match="backtest.min_eligible_universe cannot be below " "portfolio_construction.min_names",
    ):
        CW2Config.model_validate(raw)


def test_hybrid_mode_keeps_top_n_as_optional_legacy_field():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"].pop("top_n", None)

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["portfolio_construction"]["selection_mode"] == "hybrid"
    assert cfg["portfolio_construction"]["top_n"] == 25


def test_portfolio_config_accepts_optional_incumbent_exit_rank():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["incumbent_exit_rank"] = 35

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["portfolio_construction"]["incumbent_exit_rank"] == 35


def test_portfolio_config_accepts_optional_no_trade_band_weight():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["no_trade_band_weight"] = 0.005

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["portfolio_construction"]["no_trade_band_weight"] == pytest.approx(0.005)


def test_portfolio_config_accepts_optional_per_name_max_trade_weight():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["per_name_max_trade_weight"] = 0.03

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["portfolio_construction"]["per_name_max_trade_weight"] == pytest.approx(0.03)


def test_portfolio_config_accepts_optional_max_new_names_per_rebalance():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["max_new_names_per_rebalance"] = 3

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["portfolio_construction"]["max_new_names_per_rebalance"] == 3


def test_portfolio_config_accepts_target_generation_frequency():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["target_generation_frequency"] = "quarterly"

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["portfolio_construction"]["target_generation_frequency"] == "quarterly"


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("portfolio_construction", "portfolio_name"),
        ("backtest", "portfolio_name"),
        ("recommendation", "portfolio_name"),
    ],
)
def test_config_rejects_overlong_portfolio_names(section: str, field: str):
    raw = deepcopy(_load_raw_config())
    raw[section][field] = "x" * 101

    with pytest.raises(
        ValidationError,
        match=rf"{section}\.{field} cannot exceed 100 characters",
    ):
        CW2Config.model_validate(raw)


def test_portfolio_config_accepts_optional_alpha_smoothing_block():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["alpha_smoothing"] = {
        "enabled": True,
        "method": "ewma",
        "half_life_days": 60.0,
        "max_lookback_days": 252,
        "min_history_points": 3,
    }

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["portfolio_construction"]["alpha_smoothing"]["enabled"] is True
    assert cfg["portfolio_construction"]["alpha_smoothing"]["half_life_days"] == pytest.approx(60.0)


def test_portfolio_config_rejects_incumbent_exit_rank_below_hybrid_minimum():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["incumbent_exit_rank"] = 24

    with pytest.raises(
        ValidationError,
        match="incumbent_exit_rank cannot be below min_names",
    ):
        CW2Config.model_validate(raw)


def test_factor_group_accepts_explicit_sub_variable_weights():
    raw = deepcopy(_load_raw_config())
    raw["factors"]["sentiment"]["sub_variables"] = [
        "sentiment_7d_avg",
        "sentiment_30d_avg",
    ]
    raw["factors"]["sentiment"]["weights"] = {
        "sentiment_7d_avg": 0.25,
        "sentiment_30d_avg": 0.75,
    }

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["factors"]["sentiment"]["weights"]["sentiment_30d_avg"] == pytest.approx(0.75)


def test_factor_group_rejects_weight_keys_outside_sub_variables():
    raw = deepcopy(_load_raw_config())
    raw["factors"]["dividend"]["sub_variables"] = ["dividend_yield"]
    raw["factors"]["dividend"]["weights"] = {
        "dividend_yield": 1.0,
        "dividend_stability": 0.0,
    }

    with pytest.raises(
        ValidationError,
        match="factor group weight keys must be declared in sub_variables",
    ):
        CW2Config.model_validate(raw)


def test_factor_group_accepts_regime_specific_sub_variable_weights():
    raw = deepcopy(_load_raw_config())
    raw["factors"]["dividend"]["regime_weights"] = {
        "normal": {
            "dividend_yield": 0.6,
            "dividend_stability": 0.1,
            "payout_sustainability": 0.3,
        },
        "stress": {
            "dividend_yield": 0.25,
            "dividend_stability": 0.0,
            "payout_sustainability": 0.75,
        },
    }

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["factors"]["dividend"]["regime_weights"]["stress"][
        "payout_sustainability"
    ] == pytest.approx(0.75)


def test_factor_group_rejects_unknown_regime_weight_keys():
    raw = deepcopy(_load_raw_config())
    raw["factors"]["dividend"]["regime_weights"] = {
        "panic": {
            "dividend_yield": 1.0,
            "dividend_stability": 0.0,
            "payout_sustainability": 0.0,
        }
    }

    with pytest.raises(
        ValidationError,
        match="factor group regime_weights only supports normal/stress keys",
    ):
        CW2Config.model_validate(raw)


def test_covariance_config_accepts_optional_active_bounds():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["covariance"]["max_active_overweight"] = 0.015
    raw["portfolio_construction"]["covariance"]["max_active_underweight"] = 0.03

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["portfolio_construction"]["covariance"]["max_active_overweight"] == pytest.approx(
        0.015
    )
    assert cfg["portfolio_construction"]["covariance"]["max_active_underweight"] == pytest.approx(
        0.03
    )


def test_covariance_config_accepts_statistical_factor_fields():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["covariance"].update(
        {
            "method": "statistical_factor",
            "factor_count": 5,
            "max_factor_count": 6,
            "factor_variance_target": 0.80,
            "specific_variance_floor_ratio": 0.04,
            "fallback_to_diagonal_shrinkage": True,
        }
    )
    raw["backtest"]["analysis"]["covariance"].update(
        {
            "method": "statistical_factor",
            "n_factors": 5,
            "max_factor_count": 6,
            "specific_variance_floor_ratio": 0.04,
            "fallback_to_diagonal_shrinkage": True,
        }
    )

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    portfolio_cov = cfg["portfolio_construction"]["covariance"]
    analysis_cov = cfg["backtest"]["analysis"]["covariance"]
    assert portfolio_cov["method"] == "statistical_factor"
    assert portfolio_cov["factor_count"] == 5
    assert portfolio_cov["factor_variance_target"] == pytest.approx(0.80)
    assert portfolio_cov["fallback_to_diagonal_shrinkage"] is True
    assert analysis_cov["method"] == "statistical_factor"
    assert analysis_cov["n_factors"] == 5
    assert analysis_cov["specific_variance_floor_ratio"] == pytest.approx(0.04)
    assert analysis_cov["fallback_to_diagonal_shrinkage"] is True


def test_covariance_config_accepts_fundamental_factor_fields():
    raw = deepcopy(_load_raw_config())
    fundamental_fields = {
        "method": "fundamental_factor",
        "style_factors": ["market_beta", "size", "value", "quality"],
        "include_sector_factors": True,
        "exposure_lag_days": 1,
        "max_exposure_staleness_days": 540,
        "min_factor_return_days": 30,
        "min_cross_section": 8,
        "min_sector_members": 2,
        "factor_ridge": 1.0e-4,
        "factor_cov_shrinkage": 0.15,
        "fallback_to_statistical_factor": True,
        "fallback_to_diagonal_shrinkage": True,
    }
    raw["portfolio_construction"]["covariance"].update(fundamental_fields)
    raw["backtest"]["analysis"]["covariance"].update(fundamental_fields)

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    portfolio_cov = cfg["portfolio_construction"]["covariance"]
    analysis_cov = cfg["backtest"]["analysis"]["covariance"]
    assert portfolio_cov["method"] == "fundamental_factor"
    assert portfolio_cov["style_factors"] == [
        "market_beta",
        "size",
        "value",
        "quality",
    ]
    assert portfolio_cov["factor_cov_shrinkage"] == pytest.approx(0.15)
    assert portfolio_cov["fallback_to_statistical_factor"] is True
    assert analysis_cov["method"] == "fundamental_factor"
    assert analysis_cov["min_factor_return_days"] == 30


def test_covariance_config_rejects_conflicting_factor_aliases():
    raw = deepcopy(_load_raw_config())
    raw["portfolio_construction"]["covariance"].update(
        {"method": "statistical_factor", "factor_count": 4, "n_factors": 5}
    )

    with pytest.raises(
        ValidationError,
        match="factor_count and portfolio_construction.covariance.n_factors must match",
    ):
        CW2Config.model_validate(raw)


def test_regime_config_accepts_ic_weighting_block():
    raw = deepcopy(_load_raw_config())
    raw["regime"]["ic_weighting"] = {
        "enabled": True,
        "lookback_months": 24,
        "min_history_months": 12,
        "min_cross_section": 20,
        "ic_method": "spearman",
        "score_metric": "ic_ir",
        "prior_mix": 0.4,
        "score_clip": 1.5,
        "positive_only": True,
        "regime_split": False,
    }

    cfg = CW2Config.model_validate(raw).model_dump(mode="python")

    assert cfg["regime"]["ic_weighting"]["enabled"] is True
    assert cfg["regime"]["ic_weighting"]["lookback_months"] == 24
    assert cfg["regime"]["ic_weighting"]["prior_mix"] == pytest.approx(0.4)


def test_regime_config_rejects_ic_weighting_min_history_above_lookback():
    raw = deepcopy(_load_raw_config())
    raw["regime"]["ic_weighting"] = {
        "enabled": True,
        "lookback_months": 12,
        "min_history_months": 18,
    }

    with pytest.raises(ValidationError, match="min_history_months cannot exceed lookback_months"):
        CW2Config.model_validate(raw)
