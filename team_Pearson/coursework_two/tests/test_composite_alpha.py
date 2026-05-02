"""Unit tests for CW2 composite alpha score and regime switching."""

from decimal import Decimal

import pytest
import team_Pearson.coursework_two.modules.feature.composite_alpha as composite_alpha_mod
from team_Pearson.coursework_two.modules.feature.composite_alpha import (
    compute_composite_alpha,
    determine_regime,
)


class TestDetermineRegime:
    def test_normal_below_threshold(self):
        assert determine_regime(20.0) == "normal"

    def test_stress_at_threshold(self):
        assert determine_regime(25.0) == "stress"

    def test_stress_above_threshold(self):
        assert determine_regime(35.0) == "stress"

    def test_none_vix_defaults_to_normal(self):
        assert determine_regime(None) == "normal"

    def test_custom_threshold(self):
        assert determine_regime(20.0, threshold=15.0) == "stress"
        assert determine_regime(20.0, threshold=25.0) == "normal"

    def test_hysteresis_requires_persistence_for_stress_entry(self):
        assert (
            determine_regime(
                26.0,
                threshold=25.0,
                mode="hysteresis",
                exit_threshold=22.0,
                stress_persistence=2,
                normal_persistence=2,
                vix_history=[24.0, 26.0],
            )
            == "normal"
        )
        assert (
            determine_regime(
                27.0,
                threshold=25.0,
                mode="hysteresis",
                exit_threshold=22.0,
                stress_persistence=2,
                normal_persistence=2,
                vix_history=[24.0, 26.0, 27.0],
            )
            == "stress"
        )

    def test_hysteresis_requires_persistence_for_exit(self):
        assert (
            determine_regime(
                23.0,
                threshold=25.0,
                mode="hysteresis",
                exit_threshold=22.0,
                stress_persistence=2,
                normal_persistence=2,
                vix_history=[26.0, 27.0, 23.5, 23.0],
            )
            == "stress"
        )
        assert (
            determine_regime(
                21.5,
                threshold=25.0,
                mode="hysteresis",
                exit_threshold=22.0,
                stress_persistence=2,
                normal_persistence=2,
                vix_history=[26.0, 27.0, 21.8, 21.5],
            )
            == "normal"
        )


class TestCompositeAlpha:
    @pytest.fixture
    def factor_scores(self):
        return [
            {
                "as_of_date": "2025-06-30",
                "symbol": "AAPL",
                "quality_score": 1.0,
                "value_score": 0.5,
                "market_technical_score": 0.8,
                "sentiment_score": 0.3,
                "dividend_score": -0.2,
            },
            {
                "as_of_date": "2025-06-30",
                "symbol": "XOM",
                "quality_score": -0.5,
                "value_score": 1.2,
                "market_technical_score": -0.3,
                "sentiment_score": -0.1,
                "dividend_score": 0.9,
            },
        ]

    def test_normal_regime_weights(self, factor_scores):
        result = compute_composite_alpha(factor_scores, vix_level=18.0)
        aapl = result[0]
        assert aapl["regime"] == "normal"
        # Normal: Q=0.2, V=0.2, M=0.3, S=0.2, D=0.1
        expected = 0.2 * 1.0 + 0.2 * 0.5 + 0.3 * 0.8 + 0.2 * 0.3 + 0.1 * (-0.2)
        assert abs(aapl["composite_alpha"] - expected) < 1e-10

    def test_stress_regime_weights(self, factor_scores):
        result = compute_composite_alpha(factor_scores, vix_level=30.0)
        aapl = result[0]
        assert aapl["regime"] == "stress"
        # Stress: Q=0.3, V=0.2, M=0.1, S=0.1, D=0.3
        expected = 0.3 * 1.0 + 0.2 * 0.5 + 0.1 * 0.8 + 0.1 * 0.3 + 0.3 * (-0.2)
        assert abs(aapl["composite_alpha"] - expected) < 1e-10

    def test_vix_level_stored(self, factor_scores):
        result = compute_composite_alpha(factor_scores, vix_level=22.5)
        for rec in result:
            assert rec["vix_level"] == 22.5

    def test_missing_factor_rescales(self):
        scores = [
            {
                "as_of_date": "2025-06-30",
                "symbol": "TEST",
                "quality_score": 1.0,
                "value_score": None,
                "market_technical_score": None,
                "sentiment_score": None,
                "dividend_score": None,
            }
        ]
        result = compute_composite_alpha(scores, vix_level=18.0)
        # Only quality is available (weight 0.2), should rescale to 1.0 * (0.2/0.2) = 1.0
        assert abs(result[0]["composite_alpha"] - 1.0) < 1e-10

    def test_all_missing_returns_none(self):
        scores = [
            {
                "as_of_date": "2025-06-30",
                "symbol": "TEST",
                "quality_score": None,
                "value_score": None,
                "market_technical_score": None,
                "sentiment_score": None,
                "dividend_score": None,
            }
        ]
        result = compute_composite_alpha(scores, vix_level=18.0)
        assert result[0]["composite_alpha"] is None

    def test_custom_config_weights(self, factor_scores):
        config = {
            "regime": {
                "vix_stress_threshold": 20,
                "normal": {
                    "quality": 0.5,
                    "value": 0.5,
                    "market_technical": 0,
                    "sentiment": 0,
                    "dividend": 0,
                },
            }
        }
        result = compute_composite_alpha(factor_scores, vix_level=15.0, config=config)
        aapl = result[0]
        # Only quality and value matter: (0.5 * 1.0 + 0.5 * 0.5) / 1.0 = 0.75
        assert abs(aapl["composite_alpha"] - 0.75) < 1e-10

    def test_hysteresis_mode_uses_vix_history(self, factor_scores):
        config = {
            "regime": {
                "mode": "hysteresis",
                "vix_stress_threshold": 25,
                "vix_exit_threshold": 22,
                "stress_persistence": 2,
                "normal_persistence": 2,
            }
        }
        result = compute_composite_alpha(
            factor_scores,
            vix_level=26.0,
            config=config,
            vix_history=[23.0, 26.0],
        )
        assert result[0]["regime"] == "normal"
        result = compute_composite_alpha(
            factor_scores,
            vix_level=27.0,
            config=config,
            vix_history=[23.0, 26.0, 27.0],
        )
        assert result[0]["regime"] == "stress"

    def test_multi_signal_regime_uses_term_spread_confirmation(self, factor_scores):
        config = {
            "regime": {
                "signal_model": "vix_term_spread",
                "mode": "hysteresis",
                "vix_stress_threshold": 25,
                "vix_warning_threshold": 20,
                "term_spread_stress_threshold": 0.0,
                "term_spread_confirm_days": 2,
            }
        }
        result = compute_composite_alpha(
            factor_scores,
            vix_level=22.0,
            config=config,
            vix_history=[21.0, 22.0],
            macro_context={
                "term_spread_level": -0.2,
                "term_spread_history": [-0.1, -0.2],
            },
        )
        assert result[0]["regime"] == "stress"

    def test_multi_signal_regime_does_not_trigger_without_term_spread_confirmation(
        self, factor_scores
    ):
        config = {
            "regime": {
                "signal_model": "vix_term_spread",
                "mode": "hysteresis",
                "vix_stress_threshold": 25,
                "vix_warning_threshold": 20,
                "term_spread_stress_threshold": 0.0,
                "term_spread_confirm_days": 2,
            }
        }
        result = compute_composite_alpha(
            factor_scores,
            vix_level=22.0,
            config=config,
            vix_history=[21.0, 22.0],
            macro_context={"term_spread_level": 0.4, "term_spread_history": [0.5, 0.4]},
        )
        assert result[0]["regime"] == "normal"

    def test_decimal_scores_from_sql_rows_are_supported(self):
        scores = [
            {
                "as_of_date": "2026-04-14",
                "symbol": "TEST",
                "quality_score": Decimal("1.0"),
                "value_score": Decimal("0.5"),
                "market_technical_score": Decimal("0.25"),
                "sentiment_score": Decimal("0.0"),
                "dividend_score": Decimal("-0.1"),
            }
        ]
        result = compute_composite_alpha(scores, vix_level=18.0)
        expected = 0.2 * 1.0 + 0.2 * 0.5 + 0.3 * 0.25 + 0.2 * 0.0 + 0.1 * (-0.1)
        assert abs(result[0]["composite_alpha"] - expected) < 1e-10

    def test_ic_weighting_uses_dynamic_weights_when_enabled(self, factor_scores, monkeypatch):
        composite_alpha_mod._IC_WEIGHT_CACHE.clear()

        def _fake_ic_weights(*, as_of_date, regime, base_weights, ic_cfg):
            assert regime == "normal"
            assert as_of_date.isoformat() == "2025-06-30"
            return {
                "quality": 0.50,
                "value": 0.30,
                "market_technical": 0.20,
                "sentiment": 0.0,
                "dividend": 0.0,
            }

        monkeypatch.setattr(
            composite_alpha_mod,
            "_compute_ic_weighted_factor_weights",
            _fake_ic_weights,
        )
        config = {
            "regime": {
                "normal": {
                    "quality": 0.2,
                    "value": 0.2,
                    "market_technical": 0.3,
                    "sentiment": 0.2,
                    "dividend": 0.1,
                },
                "stress": {
                    "quality": 0.4,
                    "value": 0.1,
                    "market_technical": 0.05,
                    "sentiment": 0.05,
                    "dividend": 0.4,
                },
                "ic_weighting": {
                    "enabled": True,
                    "lookback_months": 36,
                    "min_history_months": 12,
                    "min_cross_section": 25,
                    "ic_method": "spearman",
                    "score_metric": "ic_ir",
                    "prior_mix": 0.5,
                    "score_clip": 2.0,
                    "positive_only": True,
                    "regime_split": False,
                },
            }
        }

        result = compute_composite_alpha(factor_scores, vix_level=18.0, config=config)
        expected = 0.50 * 1.0 + 0.30 * 0.5 + 0.20 * 0.8
        assert result[0]["composite_alpha"] == pytest.approx(expected)

    def test_ic_weighting_formula_shrinks_toward_prior(self, monkeypatch):
        history = {
            "quality": [0.10, 0.12, 0.11],
            "value": [0.05, 0.04, 0.06],
            "market_technical": [-0.03, -0.02, -0.01],
            "sentiment": [0.0, 0.0, 0.0],
            "dividend": [0.02, 0.01, 0.03],
        }
        monkeypatch.setattr(
            composite_alpha_mod,
            "_load_factor_ic_history",
            lambda **kwargs: history,
        )
        base = {
            "quality": 0.20,
            "value": 0.20,
            "market_technical": 0.30,
            "sentiment": 0.20,
            "dividend": 0.10,
        }
        weights = composite_alpha_mod._compute_ic_weighted_factor_weights(
            as_of_date=composite_alpha_mod._coerce_date("2025-06-30"),
            regime="normal",
            base_weights=base,
            ic_cfg={
                "lookback_months": 3,
                "min_history_months": 3,
                "min_cross_section": 3,
                "ic_method": "spearman",
                "score_metric": "ic_mean",
                "prior_mix": 0.5,
                "score_clip": 2.0,
                "positive_only": True,
                "regime_split": False,
            },
        )
        # Positive-only signal weights: Q 0.6111, V 0.2778, D 0.1111.
        assert weights["quality"] == pytest.approx(0.405556, rel=1e-5)
        assert weights["value"] == pytest.approx(0.238889, rel=1e-5)
        assert weights["market_technical"] == pytest.approx(0.15, rel=1e-5)
        assert weights["sentiment"] == pytest.approx(0.10, rel=1e-5)
        assert weights["dividend"] == pytest.approx(0.105556, rel=1e-5)
        assert sum(weights.values()) == pytest.approx(1.0)
