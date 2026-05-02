"""Unit tests for CW2 factor engine."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from team_Pearson.coursework_two.modules.feature.factor_engine import (
    _extract_sub_variables,
    _get_roe,
    _resolve_factor_group_specs,
    _resolve_sub_variable_weights,
    _serialize_as_of_date,
    _weighted_sub_score,
    aggregate_factor_scores_from_sub_records,
    compute_factor_scores_for_date,
)


def _make_factor_df(rows):
    """Helper: create factor_observations-like DataFrame."""
    return pd.DataFrame(rows, columns=["symbol", "observation_date", "factor_name", "factor_value"])


def _make_financial_df(rows):
    """Helper: create financial_observations-like DataFrame."""
    normalized_rows = []
    for row in rows:
        values = list(row)
        if len(values) == 5:
            values.append("edgar")
        normalized_rows.append(values)
    return pd.DataFrame(
        normalized_rows,
        columns=[
            "symbol",
            "report_date",
            "metric_name",
            "metric_value",
            "publish_date",
            "source",
        ],
    )


@pytest.fixture
def sector_map():
    return {
        "AAPL": "Information Technology",
        "MSFT": "Information Technology",
        "XOM": "Energy",
        "CVX": "Energy",
        "JPM": "Financials",
    }


@pytest.fixture
def sample_factor_df():
    """5 symbols × key factors on 2025-06-30."""
    d = date(2025, 6, 30)
    rows = []
    data = {
        "AAPL": {
            "ebitda_margin": 0.35,
            "debt_to_equity": 1.5,
            "pb_ratio": 40.0,
            "ep_ratio": 0.03,
            "ebitda_to_ev": 0.04,
            "momentum_1m": 0.05,
            "momentum_6m": 0.15,
            "momentum_12m": 0.25,
            "sentiment_7d_avg": 0.3,
            "sentiment_30d_avg": 0.2,
            "sentiment_surprise": 0.1,
            "dividend_yield": 0.005,
            "dividend_stability": 0.92,
            "payout_ratio": 0.15,
        },
        "MSFT": {
            "ebitda_margin": 0.45,
            "debt_to_equity": 0.5,
            "pb_ratio": 12.0,
            "ep_ratio": 0.04,
            "ebitda_to_ev": 0.05,
            "momentum_1m": 0.03,
            "momentum_6m": 0.10,
            "momentum_12m": 0.20,
            "sentiment_7d_avg": 0.4,
            "sentiment_30d_avg": 0.35,
            "sentiment_surprise": 0.05,
            "dividend_yield": 0.008,
            "dividend_stability": 0.95,
            "payout_ratio": 0.25,
        },
        "XOM": {
            "ebitda_margin": 0.20,
            "debt_to_equity": 0.8,
            "pb_ratio": 2.0,
            "ep_ratio": 0.08,
            "ebitda_to_ev": 0.10,
            "momentum_1m": -0.02,
            "momentum_6m": -0.05,
            "momentum_12m": 0.05,
            "sentiment_7d_avg": -0.1,
            "sentiment_30d_avg": -0.05,
            "sentiment_surprise": -0.05,
            "dividend_yield": 0.035,
            "dividend_stability": 0.70,
            "payout_ratio": 0.60,
        },
        "CVX": {
            "ebitda_margin": 0.22,
            "debt_to_equity": 0.6,
            "pb_ratio": 1.8,
            "ep_ratio": 0.09,
            "ebitda_to_ev": 0.11,
            "momentum_1m": -0.01,
            "momentum_6m": -0.03,
            "momentum_12m": 0.08,
            "sentiment_7d_avg": 0.0,
            "sentiment_30d_avg": 0.02,
            "sentiment_surprise": -0.02,
            "dividend_yield": 0.040,
            "dividend_stability": 0.78,
            "payout_ratio": 0.55,
        },
        "JPM": {
            "ebitda_margin": 0.30,
            "debt_to_equity": 2.0,
            "pb_ratio": 1.5,
            "ep_ratio": 0.07,
            "ebitda_to_ev": 0.08,
            "momentum_1m": 0.02,
            "momentum_6m": 0.08,
            "momentum_12m": 0.15,
            "sentiment_7d_avg": 0.1,
            "sentiment_30d_avg": 0.15,
            "sentiment_surprise": -0.05,
            "dividend_yield": 0.025,
            "dividend_stability": 0.82,
            "payout_ratio": 0.35,
        },
    }
    for sym, factors in data.items():
        for fname, fval in factors.items():
            rows.append([sym, d, fname, fval])
    return _make_factor_df(rows)


@pytest.fixture
def sample_financial_df():
    """ROE data from financial_observations."""
    d = date(2025, 3, 31)
    return _make_financial_df(
        [
            ["AAPL", d, "roe", 1.5, d],
            ["MSFT", d, "roe", 0.4, d],
            ["XOM", d, "roe", 0.15, d],
            ["CVX", d, "roe", 0.12, d],
            ["JPM", d, "roe", 0.13, d],
        ]
    )


class TestExtractSubVariables:
    def test_all_groups_populated(self, sample_factor_df, sample_financial_df, sector_map):
        result = _extract_sub_variables(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        for group in ["quality", "value", "market_technical", "sentiment", "dividend"]:
            assert not result[group].empty, f"{group} should have data"

    def test_quality_has_three_sub_vars(self, sample_factor_df, sample_financial_df, sector_map):
        result = _extract_sub_variables(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        quality_subs = set(result["quality"]["sub_variable"].unique())
        assert quality_subs == {"ebitda_margin", "roe", "debt_to_equity_inv"}

    def test_value_has_three_sub_vars(self, sample_factor_df, sample_financial_df, sector_map):
        result = _extract_sub_variables(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        value_subs = set(result["value"]["sub_variable"].unique())
        assert value_subs == {"book_to_price", "earnings_to_price", "ebitda_to_ev"}

    def test_dividend_has_professional_sub_vars(
        self, sample_factor_df, sample_financial_df, sector_map
    ):
        result = _extract_sub_variables(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        dividend_subs = set(result["dividend"]["sub_variable"].unique())
        assert dividend_subs == {
            "dividend_yield",
            "dividend_stability",
            "payout_sustainability",
        }

    def test_debt_to_equity_inverted(self, sample_factor_df, sample_financial_df, sector_map):
        result = _extract_sub_variables(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        de_inv = result["quality"][result["quality"]["sub_variable"] == "debt_to_equity_inv"]
        # Original D/E for AAPL = 1.5, inverted = -1.5
        aapl_de = de_inv[de_inv["symbol"] == "AAPL"]["raw_value"].iloc[0]
        assert aapl_de == -1.5

    def test_book_to_price_is_inverse_pb(self, sample_factor_df, sample_financial_df, sector_map):
        result = _extract_sub_variables(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        bp = result["value"][result["value"]["sub_variable"] == "book_to_price"]
        # AAPL P/B = 40, so B/P = 1/40 = 0.025
        aapl_bp = bp[bp["symbol"] == "AAPL"]["raw_value"].iloc[0]
        assert abs(aapl_bp - 0.025) < 1e-10

    def test_payout_sustainability_penalises_unsustainable_payout(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        factor_df = sample_factor_df.copy()
        factor_df.loc[
            (factor_df["symbol"] == "XOM") & (factor_df["factor_name"] == "payout_ratio"),
            "factor_value",
        ] = 0.95
        result = _extract_sub_variables(
            factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        payout = result["dividend"][result["dividend"]["sub_variable"] == "payout_sustainability"]
        aapl = payout[payout["symbol"] == "AAPL"]["raw_value"].iloc[0]
        xom = payout[payout["symbol"] == "XOM"]["raw_value"].iloc[0]
        assert aapl > xom

    def test_empty_date_returns_empty(self, sample_factor_df, sample_financial_df, sector_map):
        result = _extract_sub_variables(
            sample_factor_df,
            sample_financial_df,
            date(2020, 1, 1),
            sector_map,
        )
        for group in result.values():
            assert group.empty

    def test_latest_snapshot_on_or_before_as_of_date_is_used(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        factor_df = sample_factor_df.copy()
        factor_df = factor_df[
            ~((factor_df["symbol"] == "AAPL") & (factor_df["factor_name"] == "momentum_1m"))
        ].copy()
        factor_df = pd.concat(
            [
                factor_df,
                _make_factor_df(
                    [
                        ["AAPL", date(2025, 6, 27), "momentum_1m", 0.04],
                        ["AAPL", date(2025, 7, 1), "momentum_1m", 0.99],
                    ]
                ),
            ],
            ignore_index=True,
        )

        result = _extract_sub_variables(
            factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        market_tech = result["market_technical"]
        aapl_mom = market_tech[
            (market_tech["symbol"] == "AAPL") & (market_tech["sub_variable"] == "momentum_1m")
        ]["raw_value"].iloc[0]
        assert aapl_mom == pytest.approx(0.04)


class TestGetRoe:
    def test_from_financial_observations(self, sample_factor_df, sample_financial_df):
        roe = _get_roe("AAPL", date(2025, 6, 30), sample_factor_df, sample_financial_df)
        assert roe == 1.5

    def test_fallback_computed(self, sample_factor_df):
        fin_df = _make_financial_df(
            [
                [
                    "AAPL",
                    date(2025, 3, 31),
                    "net_income",
                    100e9,
                    date(2025, 3, 31),
                    "edgar",
                ],
                [
                    "AAPL",
                    date(2025, 3, 31),
                    "stockholders_equity",
                    50e9,
                    date(2025, 3, 31),
                    "edgar",
                ],
            ]
        )
        roe = _get_roe("AAPL", date(2025, 6, 30), sample_factor_df, fin_df)
        assert abs(roe - 2.0) < 1e-10

    def test_fallback_uses_mixed_source_when_sources_do_not_match(self, sample_factor_df):
        fin_df = _make_financial_df(
            [
                [
                    "AAPL",
                    date(2025, 3, 31),
                    "net_income",
                    100e9,
                    date(2025, 3, 31),
                    "edgar",
                ],
                [
                    "AAPL",
                    date(2025, 3, 31),
                    "stockholders_equity",
                    50e9,
                    date(2025, 3, 31),
                    "yfinance",
                ],
            ]
        )
        roe = _get_roe("AAPL", date(2025, 6, 30), sample_factor_df, fin_df)
        assert abs(roe - 2.0) < 1e-10

    def test_missing_returns_none(self, sample_factor_df):
        empty_fin = _make_financial_df([])
        roe = _get_roe("AAPL", date(2025, 6, 30), sample_factor_df, empty_fin)
        assert roe is None

    def test_invalid_precomputed_roe_falls_back_to_latest_financial_pair(self, sample_factor_df):
        fin_df = _make_financial_df(
            [
                ["AAPL", date(2025, 3, 31), "roe", "not-a-number", date(2025, 4, 15), "edgar"],
                ["AAPL", date(2025, 3, 31), "net_income", 120.0, date(2025, 4, 15), "edgar"],
                [
                    "AAPL",
                    date(2025, 3, 31),
                    "stockholders_equity",
                    60.0,
                    date(2025, 4, 15),
                    "edgar",
                ],
            ]
        )

        roe = _get_roe("AAPL", date(2025, 6, 30), sample_factor_df, fin_df)

        assert roe == pytest.approx(2.0)

    def test_roe_ignores_unpublished_future_financials(self, sample_factor_df):
        fin_df = _make_financial_df(
            [
                ["AAPL", date(2025, 3, 31), "roe", 0.8, date(2025, 7, 15), "edgar"],
                ["AAPL", date(2024, 12, 31), "roe", 0.4, date(2025, 2, 15), "edgar"],
            ]
        )

        roe = _get_roe("AAPL", date(2025, 6, 30), sample_factor_df, fin_df)

        assert roe == pytest.approx(0.4)


class TestComputeFactorScores:
    def test_produces_scores_for_all_symbols(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        sub_records, factor_records = compute_factor_scores_for_date(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        symbols = {r["symbol"] for r in factor_records}
        assert symbols == {"AAPL", "MSFT", "XOM", "CVX", "JPM"}

    def test_factor_scores_have_all_fields(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        _, factor_records = compute_factor_scores_for_date(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        for rec in factor_records:
            assert "quality_score" in rec
            assert "value_score" in rec
            assert "market_technical_score" in rec
            assert "sentiment_score" in rec
            assert "dividend_score" in rec

    def test_sub_scores_have_preprocessing_columns(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        sub_records, _ = compute_factor_scores_for_date(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        for rec in sub_records:
            assert "raw_value" in rec
            assert "factor_group" in rec
            assert "sub_variable" in rec

    def test_z_scores_approximately_centered(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        sub_records, _ = compute_factor_scores_for_date(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
        )
        z_values = [r["z_score"] for r in sub_records if r["z_score"] is not None]
        if z_values:
            mean_z = np.mean(z_values)
            assert abs(mean_z) < 0.5  # should be roughly centered

    def test_config_can_prune_disabled_sub_variables(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        config = {
            "factors": {
                "dividend": {
                    "sub_variables": ["dividend_yield", "payout_sustainability"],
                    "weights": {
                        "dividend_yield": 0.25,
                        "payout_sustainability": 0.75,
                    },
                }
            }
        }

        sub_records, factor_records = compute_factor_scores_for_date(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
            config=config,
        )

        dividend_subs = {
            rec["sub_variable"] for rec in sub_records if rec["factor_group"] == "dividend"
        }
        assert dividend_subs == {"dividend_yield", "payout_sustainability"}

        payout_lookup = {
            rec["symbol"]: rec["z_score"]
            for rec in sub_records
            if rec["factor_group"] == "dividend" and rec["sub_variable"] == "payout_sustainability"
        }
        yield_lookup = {
            rec["symbol"]: rec["z_score"]
            for rec in sub_records
            if rec["factor_group"] == "dividend" and rec["sub_variable"] == "dividend_yield"
        }
        for rec in factor_records:
            pieces = []
            if yield_lookup[rec["symbol"]] is not None:
                pieces.append((0.25, yield_lookup[rec["symbol"]]))
            if payout_lookup[rec["symbol"]] is not None:
                pieces.append((0.75, payout_lookup[rec["symbol"]]))
            expected = sum(weight * score for weight, score in pieces) / sum(
                weight for weight, _ in pieces
            )
            assert rec["dividend_score"] == pytest.approx(expected)

    def test_config_can_reweight_sentiment_sub_variables(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        config = {
            "factors": {
                "sentiment": {
                    "sub_variables": ["sentiment_7d_avg", "sentiment_30d_avg"],
                    "weights": {
                        "sentiment_7d_avg": 0.25,
                        "sentiment_30d_avg": 0.75,
                    },
                }
            }
        }

        sub_records, factor_records = compute_factor_scores_for_date(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
            config=config,
        )

        surprise_rows = [
            rec
            for rec in sub_records
            if rec["factor_group"] == "sentiment" and rec["sub_variable"] == "sentiment_surprise"
        ]
        assert surprise_rows == []

        score_lookup = {rec["symbol"]: rec["sentiment_score"] for rec in factor_records}
        z7_lookup = {
            rec["symbol"]: rec["z_score"]
            for rec in sub_records
            if rec["factor_group"] == "sentiment" and rec["sub_variable"] == "sentiment_7d_avg"
        }
        z30_lookup = {
            rec["symbol"]: rec["z_score"]
            for rec in sub_records
            if rec["factor_group"] == "sentiment" and rec["sub_variable"] == "sentiment_30d_avg"
        }
        for symbol, score in score_lookup.items():
            expected = 0.25 * z7_lookup[symbol] + 0.75 * z30_lookup[symbol]
            assert score == pytest.approx(expected)

    def test_dividend_factor_supports_regime_specific_weights(
        self,
        sample_factor_df,
        sample_financial_df,
        sector_map,
    ):
        config = {
            "factors": {
                "dividend": {
                    "sub_variables": [
                        "dividend_yield",
                        "dividend_stability",
                        "payout_sustainability",
                    ],
                    "weights": {
                        "dividend_yield": 0.60,
                        "dividend_stability": 0.10,
                        "payout_sustainability": 0.30,
                    },
                    "regime_weights": {
                        "normal": {
                            "dividend_yield": 0.60,
                            "dividend_stability": 0.10,
                            "payout_sustainability": 0.30,
                        },
                        "stress": {
                            "dividend_yield": 0.25,
                            "dividend_stability": 0.00,
                            "payout_sustainability": 0.75,
                        },
                    },
                }
            }
        }

        sub_records, normal_records = compute_factor_scores_for_date(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
            config=config,
            regime="normal",
        )
        _, stress_records = compute_factor_scores_for_date(
            sample_factor_df,
            sample_financial_df,
            date(2025, 6, 30),
            sector_map,
            config=config,
            regime="stress",
        )

        yield_lookup = {
            rec["symbol"]: rec["z_score"]
            for rec in sub_records
            if rec["factor_group"] == "dividend" and rec["sub_variable"] == "dividend_yield"
        }
        stability_lookup = {
            rec["symbol"]: rec["z_score"]
            for rec in sub_records
            if rec["factor_group"] == "dividend" and rec["sub_variable"] == "dividend_stability"
        }
        payout_lookup = {
            rec["symbol"]: rec["z_score"]
            for rec in sub_records
            if rec["factor_group"] == "dividend" and rec["sub_variable"] == "payout_sustainability"
        }
        normal_lookup = {rec["symbol"]: rec["dividend_score"] for rec in normal_records}
        stress_lookup = {rec["symbol"]: rec["dividend_score"] for rec in stress_records}

        for symbol in normal_lookup:
            normal_pieces = []
            if yield_lookup[symbol] is not None:
                normal_pieces.append((0.60, yield_lookup[symbol]))
            if stability_lookup[symbol] is not None:
                normal_pieces.append((0.10, stability_lookup[symbol]))
            if payout_lookup[symbol] is not None:
                normal_pieces.append((0.30, payout_lookup[symbol]))
            stress_pieces = []
            if yield_lookup[symbol] is not None:
                stress_pieces.append((0.25, yield_lookup[symbol]))
            if payout_lookup[symbol] is not None:
                stress_pieces.append((0.75, payout_lookup[symbol]))
            expected_normal = sum(weight * score for weight, score in normal_pieces) / sum(
                weight for weight, _ in normal_pieces
            )
            expected_stress = sum(weight * score for weight, score in stress_pieces) / sum(
                weight for weight, _ in stress_pieces
            )
            assert normal_lookup[symbol] == pytest.approx(expected_normal)
            assert stress_lookup[symbol] == pytest.approx(expected_stress)

    def test_single_observation_sub_variable_is_preserved_without_z_score(self, sector_map):
        factor_df = _make_factor_df(
            [
                ["AAPL", date(2025, 6, 30), "sentiment_surprise", 0.2],
            ]
        )
        financial_df = _make_financial_df([])

        sub_records, factor_records = compute_factor_scores_for_date(
            factor_df,
            financial_df,
            date(2025, 6, 30),
            sector_map,
        )

        assert sub_records == [
            {
                "as_of_date": "2025-06-30",
                "symbol": "AAPL",
                "factor_group": "sentiment",
                "sub_variable": "sentiment_surprise",
                "raw_value": 0.2,
                "winsorized_value": None,
                "neutralized_value": None,
                "z_score": None,
                "gics_sector": "Information Technology",
            }
        ]
        assert factor_records == []

    def test_aggregate_skips_invalid_symbols_and_disabled_sub_variables(self):
        records = [
            {
                "as_of_date": date(2025, 6, 30),
                "symbol": "AAA",
                "factor_group": "quality",
                "sub_variable": "roe",
                "z_score": 1.0,
            },
            {
                "as_of_date": date(2025, 6, 30),
                "symbol": "AAA",
                "factor_group": "quality",
                "sub_variable": "debt_to_equity_inv",
                "z_score": "bad",
            },
            {
                "as_of_date": date(2025, 6, 30),
                "symbol": "",
                "factor_group": "quality",
                "sub_variable": "roe",
                "z_score": 99.0,
            },
            {
                "as_of_date": date(2025, 6, 30),
                "symbol": "AAA",
                "factor_group": "unknown",
                "sub_variable": "roe",
                "z_score": 99.0,
            },
        ]

        out = aggregate_factor_scores_from_sub_records(
            records,
            config={"factors": {"quality": {"sub_variables": ["roe"]}}},
        )

        assert out == [
            {
                "as_of_date": "2025-06-30",
                "symbol": "AAA",
                "quality_score": 1.0,
                "value_score": None,
                "market_technical_score": None,
                "sentiment_score": None,
                "dividend_score": None,
            }
        ]


class TestFactorConfigHelpers:
    def test_serializes_non_date_value_as_is(self):
        assert _serialize_as_of_date("2025-06-30") == "2025-06-30"

    def test_resolve_factor_specs_rejects_unsupported_weight_mode(self):
        with pytest.raises(ValueError, match="Unsupported weight mode"):
            _resolve_factor_group_specs({"factors": {"quality": {"weights": "rank"}}})

    def test_resolve_sub_variable_weights_rejects_bad_inputs(self):
        with pytest.raises(ValueError, match="weights must be"):
            _resolve_sub_variable_weights(
                factor_group="quality",
                sub_variables=["roe"],
                raw_weights=["roe"],
            )

        with pytest.raises(ValueError, match="cannot be negative"):
            _resolve_sub_variable_weights(
                factor_group="quality",
                sub_variables=["roe"],
                raw_weights={"roe": -1.0},
            )

        with pytest.raises(ValueError, match="positive total"):
            _resolve_sub_variable_weights(
                factor_group="quality",
                sub_variables=["roe"],
                raw_weights={"roe": 0.0},
            )

    def test_weighted_sub_score_handles_empty_and_zero_weight_cases(self):
        assert _weighted_sub_score({}, None) is None
        assert _weighted_sub_score({"roe": 1.0}, {"roe": 0.0}) is None
        assert _weighted_sub_score({"roe": 1.0, "margin": -1.0}, {"roe": 2.0}) == 1.0
