"""
Tests for value scoring module.
"""

from datetime import date


class TestComputeValueScores:
    """Tests for compute_value_scores."""

    def test_basic_scoring(self, sample_company_infos):
        from modules.processing.value_scorer import compute_value_scores

        results = compute_value_scores(sample_company_infos, date(2025, 1, 1))
        assert len(results) == 4
        assert all("value_score" in r for r in results)

    def test_score_range(self, sample_company_infos):
        from modules.processing.value_scorer import compute_value_scores

        results = compute_value_scores(sample_company_infos)
        for r in results:
            if r["value_score"] is not None:
                assert 0 <= r["value_score"] <= 100

    def test_date_assignment(self, sample_company_infos):
        from modules.processing.value_scorer import compute_value_scores

        results = compute_value_scores(sample_company_infos, date(2025, 6, 15))
        assert all(r["date"] == "2025-06-15" for r in results)

    def test_empty_input(self):
        from modules.processing.value_scorer import compute_value_scores

        results = compute_value_scores([])
        assert results == []

    def test_missing_ratios(self):
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "TEST",
                "pe_ratio": None,
                "pb_ratio": None,
                "ev_ebitda": None,
                "dividend_yield": None,
                "debt_equity": None,
            }
        ]
        results = compute_value_scores(infos)
        assert len(results) == 1

    def test_partial_ratios(self):
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "A",
                "pe_ratio": 10.0,
                "pb_ratio": None,
                "ev_ebitda": None,
                "dividend_yield": None,
                "debt_equity": None,
            },
            {
                "symbol": "B",
                "pe_ratio": 20.0,
                "pb_ratio": None,
                "ev_ebitda": None,
                "dividend_yield": None,
                "debt_equity": None,
            },
        ]
        results = compute_value_scores(infos)
        assert len(results) == 2
        # Lower P/E should get higher value score
        a_score = next(r for r in results if r["company_id"] == "A")
        b_score = next(r for r in results if r["company_id"] == "B")
        assert a_score["value_score"] > b_score["value_score"]

    def test_value_cheapest_ranks_highest(self, sample_company_infos):
        from modules.processing.value_scorer import compute_value_scores

        results = compute_value_scores(sample_company_infos)
        # XOM has lowest P/E (15), lowest EV/EBITDA (6.5), highest yield → should rank well
        xom = next(r for r in results if r["company_id"] == "XOM")
        assert xom["value_score"] is not None
        assert xom["value_score"] > 50

    def test_record_structure(self, sample_company_infos):
        from modules.processing.value_scorer import compute_value_scores

        results = compute_value_scores(sample_company_infos)
        rec = results[0]
        assert "company_id" in rec
        assert "date" in rec
        assert "pe_ratio" in rec
        assert "pb_ratio" in rec
        assert "ev_ebitda" in rec
        assert "dividend_yield" in rec
        assert "debt_equity" in rec
        assert "value_score" in rec

    def test_negative_pe_excluded(self):
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "A",
                "pe_ratio": -5.0,
                "pb_ratio": 2.0,
                "ev_ebitda": 10.0,
                "dividend_yield": 0.02,
                "debt_equity": 1.0,
            },
            {
                "symbol": "B",
                "pe_ratio": 20.0,
                "pb_ratio": 3.0,
                "ev_ebitda": 15.0,
                "dividend_yield": 0.01,
                "debt_equity": 0.5,
            },
        ]
        results = compute_value_scores(infos)
        a_rec = next(r for r in results if r["company_id"] == "A")
        assert a_rec["pe_ratio"] == -5.0  # Original P/E preserved for storage
        assert a_rec["value_score"] is not None  # Still scored via other ratios (P/E excluded from ranking)

    def test_extreme_pe_excluded(self):
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "A",
                "pe_ratio": 600.0,
                "pb_ratio": 2.0,
                "ev_ebitda": 10.0,
                "dividend_yield": 0.02,
                "debt_equity": 1.0,
            },
            {
                "symbol": "B",
                "pe_ratio": 20.0,
                "pb_ratio": 3.0,
                "ev_ebitda": 15.0,
                "dividend_yield": 0.01,
                "debt_equity": 0.5,
            },
        ]
        results = compute_value_scores(infos)
        a_rec = next(r for r in results if r["company_id"] == "A")
        assert a_rec["pe_ratio"] == 600.0  # Original P/E preserved for storage (excluded from ranking)

    def test_debt_equity_stored_but_not_scored(self):
        from modules.processing.value_scorer import compute_value_scores

        # Verify D/E is stored in output but not used in scoring
        # yfinance returns dividendYield and debtToEquity as PERCENTAGES,
        # so both are divided by 100 in compute_value_scores.
        infos = [
            {
                "symbol": "A",
                "pe_ratio": 10.0,
                "pb_ratio": 2.0,
                "ev_ebitda": 8.0,
                "dividend_yield": 3.0,  # 3.0% from yfinance → 0.03 decimal
                "debt_equity": 50.0,  # 50% from yfinance → 0.5 ratio
            },
            {
                "symbol": "B",
                "pe_ratio": 20.0,
                "pb_ratio": 3.0,
                "ev_ebitda": 12.0,
                "dividend_yield": 2.0,  # 2.0% from yfinance → 0.02 decimal
                "debt_equity": 500.0,  # 500% from yfinance → 5.0 ratio
            },
            {
                "symbol": "C",
                "pe_ratio": 30.0,
                "pb_ratio": 4.0,
                "ev_ebitda": 16.0,
                "dividend_yield": 1.0,  # 1.0% from yfinance → 0.01 decimal
                "debt_equity": 10.0,  # 10% from yfinance → 0.1 ratio
            },
        ]
        results = compute_value_scores(infos)
        for r in results:
            assert "debt_equity" in r
            assert "dividend_yield" in r
        # A has best ratios → highest score regardless of D/E values
        a_rec = next(r for r in results if r["company_id"] == "A")
        c_rec = next(r for r in results if r["company_id"] == "C")
        assert a_rec["value_score"] > c_rec["value_score"]
        assert a_rec["debt_equity"] == 0.5  # 50% from yfinance → 0.5 ratio
        assert a_rec["dividend_yield"] == 0.03  # 3.0% from yfinance → 0.03 decimal


class TestPercentileRank:
    """Tests for percentile ranking helper."""

    def test_basic_ranking(self):
        from modules.processing.value_scorer import _percentile_rank

        ranks = _percentile_rank([10.0, 20.0, 30.0])
        assert ranks[0] == 0.0  # Lowest
        assert ranks[1] == 0.5  # Middle
        assert ranks[2] == 1.0  # Highest

    def test_with_none_values(self):
        from modules.processing.value_scorer import _percentile_rank

        ranks = _percentile_rank([10.0, None, 30.0])
        assert ranks[1] is None
        assert ranks[0] == 0.0
        assert ranks[2] == 1.0

    def test_single_value(self):
        from modules.processing.value_scorer import _percentile_rank

        ranks = _percentile_rank([42.0])
        assert ranks[0] == 0.5

    def test_all_none(self):
        from modules.processing.value_scorer import _percentile_rank

        ranks = _percentile_rank([None, None])
        assert ranks == [None, None]

    def test_equal_values(self):
        from modules.processing.value_scorer import _percentile_rank

        ranks = _percentile_rank([5.0, 5.0, 5.0])
        # All have same value, so ranks may vary but should be valid
        assert all(r is not None for r in ranks)


class TestSafeFloat:
    """Tests for _safe_float helper."""

    def test_valid_float(self):
        from modules.processing.value_scorer import _safe_float

        assert _safe_float(42.5) == 42.5

    def test_none(self):
        from modules.processing.value_scorer import _safe_float

        assert _safe_float(None) is None

    def test_nan(self):
        from modules.processing.value_scorer import _safe_float

        assert _safe_float(float("nan")) is None

    def test_inf(self):
        from modules.processing.value_scorer import _safe_float

        assert _safe_float(float("inf")) is None

    def test_string_number(self):
        from modules.processing.value_scorer import _safe_float

        assert _safe_float("not_a_number") is None

    def test_integer(self):
        from modules.processing.value_scorer import _safe_float

        assert _safe_float(10) == 10.0
