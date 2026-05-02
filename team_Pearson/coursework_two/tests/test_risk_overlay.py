"""Unit tests for CW2 risk overlay filters."""

import pandas as pd
import pytest
from team_Pearson.coursework_two.modules.risk.overlay import apply_risk_overlay


@pytest.fixture
def factor_scores():
    return [
        {"as_of_date": "2025-06-30", "symbol": "AAPL"},
        {"as_of_date": "2025-06-30", "symbol": "MSFT"},
        {"as_of_date": "2025-06-30", "symbol": "TINY"},  # small cap
        {"as_of_date": "2025-06-30", "symbol": "ILLQ"},  # illiquid
        {"as_of_date": "2025-06-30", "symbol": "WILD"},  # high vol
    ]


@pytest.fixture
def risk_data():
    return pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT", "TINY", "ILLQ", "WILD"],
            "log_market_cap": [26.0, 27.0, 18.0, 23.0, 24.0],
            "liquidity_20d": [1e9, 8e8, 1e7, 1e5, 5e8],
            "volatility_60d": [0.20, 0.18, 0.25, 0.22, 0.90],
            "realized_vol_60d": [0.21, 0.19, 0.26, 0.24, 0.95],
        }
    )


@pytest.fixture
def sub_score_records():
    """All 15 sub-variables present for AAPL/MSFT, only 5 for TINY."""
    records = []
    all_subs = [
        ("quality", "ebitda_margin"),
        ("quality", "roe"),
        ("quality", "debt_to_equity_inv"),
        ("value", "book_to_price"),
        ("value", "earnings_to_price"),
        ("value", "ebitda_to_ev"),
        ("market_technical", "momentum_1m"),
        ("market_technical", "momentum_6m"),
        ("market_technical", "momentum_12_1m"),
        ("sentiment", "sentiment_7d_avg"),
        ("sentiment", "sentiment_30d_avg"),
        ("sentiment", "sentiment_surprise"),
        ("dividend", "dividend_yield"),
        ("dividend", "dividend_stability"),
        ("dividend", "payout_sustainability"),
    ]
    for sym in ["AAPL", "MSFT", "ILLQ", "WILD"]:
        for fg, sv in all_subs:
            records.append({"symbol": sym, "factor_group": fg, "sub_variable": sv, "z_score": 0.5})
    # TINY only has 5 sub-variables (missing 10 -> 66.7% missing)
    for fg, sv in all_subs[:5]:
        records.append({"symbol": "TINY", "factor_group": fg, "sub_variable": sv, "z_score": 0.3})
    return records


class TestRiskOverlay:
    def test_aapl_passes_all(self, factor_scores, risk_data, sub_score_records):
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records)
        aapl = [r for r in results if r["symbol"] == "AAPL"][0]
        assert aapl["pass_all"] is True

    def test_tiny_fails_market_cap(self, factor_scores, risk_data, sub_score_records):
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records)
        tiny = [r for r in results if r["symbol"] == "TINY"][0]
        assert tiny["pass_market_cap"] is False
        assert tiny["pass_all"] is False

    def test_illq_fails_liquidity(self, factor_scores, risk_data, sub_score_records):
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records)
        illq = [r for r in results if r["symbol"] == "ILLQ"][0]
        assert illq["pass_liquidity"] is False
        assert illq["pass_all"] is False

    def test_wild_fails_volatility(self, factor_scores, risk_data, sub_score_records):
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records)
        wild = [r for r in results if r["symbol"] == "WILD"][0]
        assert wild["pass_volatility"] is False
        assert wild["pass_all"] is False

    def test_tiny_fails_data_quality(self, factor_scores, risk_data, sub_score_records):
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records)
        tiny = [r for r in results if r["symbol"] == "TINY"][0]
        assert tiny["pass_data_quality"] is False
        assert tiny["missing_factor_pct"] > 0.40

    def test_custom_config_thresholds(self, factor_scores, risk_data, sub_score_records):
        # Lower market cap threshold so TINY passes
        config = {"risk_overlay": {"min_market_cap_log": 15.0}}
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records, config=config)
        tiny = [r for r in results if r["symbol"] == "TINY"][0]
        assert tiny["pass_market_cap"] is True

    def test_all_symbols_present_in_results(self, factor_scores, risk_data, sub_score_records):
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records)
        result_symbols = {r["symbol"] for r in results}
        assert result_symbols == {"AAPL", "MSFT", "TINY", "ILLQ", "WILD"}

    def test_optional_blacklist_metric_can_fail_symbol(
        self, factor_scores, risk_data, sub_score_records
    ):
        config = {
            "risk_overlay": {
                "optional_percentile_blacklists": [
                    {"column": "realized_vol_60d", "percentile": 0.80},
                ]
            }
        }
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records, config=config)
        wild = [r for r in results if r["symbol"] == "WILD"][0]
        assert wild["pass_all"] is False

    def test_factor_group_coverage_can_be_enforced(self, risk_data, sub_score_records):
        factor_scores = [
            {
                "as_of_date": "2025-06-30",
                "symbol": "AAPL",
                "quality_score": 1.0,
                "value_score": 1.0,
                "market_technical_score": 1.0,
                "sentiment_score": None,
                "dividend_score": None,
            },
            {
                "as_of_date": "2025-06-30",
                "symbol": "MSFT",
                "quality_score": 1.0,
                "value_score": None,
                "market_technical_score": 1.0,
                "sentiment_score": None,
                "dividend_score": None,
            },
        ]
        cfg = {
            "risk_overlay": {
                "min_market_cap_log": None,
                "min_liquidity_20d": None,
                "min_factor_groups_present": 3,
                "required_factor_groups": ["quality", "value", "market_technical"],
            }
        }
        results = apply_risk_overlay(factor_scores, risk_data, sub_score_records, config=cfg)
        lookup = {row["symbol"]: row for row in results if row["symbol"] in {"AAPL", "MSFT"}}
        assert lookup["AAPL"]["pass_factor_coverage"] is True
        assert lookup["MSFT"]["pass_factor_coverage"] is False

    def test_missingness_defaults_to_required_factor_groups(self, risk_data):
        factor_scores = [
            {
                "as_of_date": "2025-06-30",
                "symbol": "AAPL",
                "quality_score": 1.0,
                "value_score": 1.0,
                "market_technical_score": 1.0,
                "sentiment_score": None,
                "dividend_score": None,
            }
        ]
        sub_score_records = []
        core_subs = [
            ("quality", "ebitda_margin"),
            ("quality", "roe"),
            ("quality", "debt_to_equity_inv"),
            ("value", "book_to_price"),
            ("value", "earnings_to_price"),
            ("value", "ebitda_to_ev"),
            ("market_technical", "momentum_1m"),
            ("market_technical", "momentum_6m"),
            ("market_technical", "momentum_12_1m"),
        ]
        for factor_group, sub_variable in core_subs:
            sub_score_records.append(
                {
                    "symbol": "AAPL",
                    "factor_group": factor_group,
                    "sub_variable": sub_variable,
                    "z_score": 0.5,
                }
            )

        cfg = {
            "factors": {
                "quality": {"sub_variables": ["ebitda_margin", "roe", "debt_to_equity_inv"]},
                "value": {
                    "sub_variables": [
                        "book_to_price",
                        "earnings_to_price",
                        "ebitda_to_ev",
                    ]
                },
                "market_technical": {
                    "sub_variables": ["momentum_1m", "momentum_6m", "momentum_12_1m"]
                },
                "sentiment": {
                    "sub_variables": [
                        "sentiment_7d_avg",
                        "sentiment_30d_avg",
                        "sentiment_surprise",
                    ]
                },
                "dividend": {
                    "sub_variables": [
                        "dividend_yield",
                        "dividend_stability",
                        "payout_sustainability",
                    ]
                },
            },
            "risk_overlay": {
                "min_market_cap_log": None,
                "min_liquidity_20d": None,
                "max_missing_factor_pct": 0.10,
                "min_factor_groups_present": 3,
                "required_factor_groups": ["quality", "value", "market_technical"],
            },
        }

        results = apply_risk_overlay(
            factor_scores,
            risk_data[risk_data["symbol"] == "AAPL"],
            sub_score_records,
            config=cfg,
        )

        aapl = results[0]
        assert aapl["missing_factor_pct"] == 0.0
        assert aapl["pass_factor_coverage"] is True
        assert aapl["pass_data_quality"] is True
        assert aapl["pass_all"] is True
