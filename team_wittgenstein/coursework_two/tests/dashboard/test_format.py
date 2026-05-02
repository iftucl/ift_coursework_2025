"""Tests for dashboard.lib.format - pure formatting helpers.

The format module has no dependencies on Streamlit or DB - just number,
percent, and date formatting. Easy to test in isolation.
"""

# Import using path adjustment since dashboard/ isn't in the package path
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dashboard"))

from lib.format import (  # noqa: E402
    big_num,
    fmt_date,
    fmt_date_range,
    num,
    num_signed,
    pct,
    pct_signed,
    safe_get,
    scenario_label,
)

# ---------------------------------------------------------------------------
# Percentage formatting
# ---------------------------------------------------------------------------


class TestPct:
    def test_simple_percentage(self):
        assert pct(0.0316) == "3.16%"

    def test_zero(self):
        assert pct(0.0) == "0.00%"

    def test_negative(self):
        assert pct(-0.10) == "-10.00%"

    def test_custom_places(self):
        assert pct(0.123456, places=4) == "12.3456%"

    def test_none_returns_dash(self):
        assert pct(None) == "-"

    def test_nan_returns_dash(self):
        assert pct(np.nan) == "-"


class TestPctSigned:
    def test_positive_has_plus(self):
        assert pct_signed(0.05) == "+5.00%"

    def test_negative_has_minus(self):
        assert pct_signed(-0.05) == "-5.00%"

    def test_zero_no_sign(self):
        # Zero is not strictly positive, so no + sign
        assert pct_signed(0.0) == "0.00%"

    def test_none_returns_dash(self):
        assert pct_signed(None) == "-"


# ---------------------------------------------------------------------------
# Numeric formatting
# ---------------------------------------------------------------------------


class TestNum:
    def test_three_places_default(self):
        # Python uses banker's rounding (round-half-to-even); 0.6275 -> 0.627
        assert num(0.6276) == "0.628"

    def test_custom_places(self):
        assert num(1.5, places=1) == "1.5"

    def test_negative(self):
        assert num(-1.5) == "-1.500"

    def test_none_returns_dash(self):
        assert num(None) == "-"

    def test_nan_returns_dash(self):
        assert num(float("nan")) == "-"


class TestNumSigned:
    def test_positive_has_plus(self):
        assert num_signed(0.5) == "+0.500"

    def test_negative_has_minus(self):
        assert num_signed(-0.5) == "-0.500"


# ---------------------------------------------------------------------------
# Big number formatting (compact)
# ---------------------------------------------------------------------------


class TestBigNum:
    def test_billions(self):
        assert big_num(1_500_000_000) == "1.5B"

    def test_millions(self):
        assert big_num(50_000_000) == "50.0M"

    def test_thousands(self):
        assert big_num(1500) == "1.5K"

    def test_small(self):
        assert big_num(432) == "432"

    def test_below_one(self):
        assert big_num(0.5) == "0.50"

    def test_zero(self):
        # Values below 1 use 2-decimal float format
        assert big_num(0) == "0.00"

    def test_none(self):
        assert big_num(None) == "-"


# ---------------------------------------------------------------------------
# Date formatting
# ---------------------------------------------------------------------------


class TestFmtDate:
    def test_datetime(self):
        assert fmt_date(datetime(2024, 3, 1)) == "Mar 2024"

    def test_date(self):
        assert fmt_date(date(2024, 3, 1)) == "Mar 2024"

    def test_string(self):
        assert fmt_date("2024-03-01") == "Mar 2024"

    def test_custom_format(self):
        assert fmt_date(date(2024, 3, 1), format="%Y-%m") == "2024-03"

    def test_none(self):
        assert fmt_date(None) == "-"

    def test_nan(self):
        assert fmt_date(np.nan) == "-"


class TestFmtDateRange:
    def test_basic(self):
        result = fmt_date_range(date(2021, 3, 1), date(2026, 3, 1))
        assert result == "Mar 2021 - Mar 2026"


# ---------------------------------------------------------------------------
# Safe getter
# ---------------------------------------------------------------------------


class TestSafeGet:
    def test_valid_key(self):
        s = pd.Series({"a": 1.5, "b": 2.5})
        assert safe_get(s, "a") == 1.5

    def test_missing_key(self):
        s = pd.Series({"a": 1.5})
        assert pd.isna(safe_get(s, "missing"))

    def test_missing_with_default(self):
        s = pd.Series({"a": 1.5})
        assert safe_get(s, "missing", default=0.0) == 0.0

    def test_nan_value(self):
        s = pd.Series({"a": np.nan})
        assert pd.isna(safe_get(s, "a"))

    def test_none_series(self):
        assert pd.isna(safe_get(None, "a"))

    def test_empty_series(self):
        assert pd.isna(safe_get(pd.Series(dtype=float), "a"))


# ---------------------------------------------------------------------------
# Scenario label parsing
# ---------------------------------------------------------------------------


class TestScenarioLabel:
    def test_baseline(self):
        assert scenario_label("baseline") == "Baseline (default parameters)"

    def test_known_cost(self):
        assert scenario_label("cost_low") == "Cost: Low (10 bps)"

    def test_known_exclusion(self):
        assert scenario_label("excl_quality") == "Exclude Quality factor"

    def test_sens_selection(self):
        result = scenario_label("sens_sel_0.05")
        assert "selection threshold" in result
        assert "0.05" in result

    def test_sens_ic_lookback(self):
        result = scenario_label("sens_ic_24")
        assert "IC lookback" in result
        assert "24" in result

    def test_sens_ewma(self):
        result = scenario_label("sens_ewma_0.97")
        assert "EWMA" in result
        assert "0.97" in result

    def test_unknown_falls_back_to_id(self):
        # Truly unknown scenarios should round-trip the id
        assert scenario_label("custom_xyz_42") == "custom_xyz_42"

    def test_partial_sens_falls_back_to_id(self):
        # A sens_ string that doesn't match the known pattern returns as-is
        assert scenario_label("sens_") == "sens_"
