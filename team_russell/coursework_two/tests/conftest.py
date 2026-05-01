"""Shared fixtures for CW2 test suite."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Make scripts importable without installing as a package
SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


# ── Output isolation ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _redirect_output_paths(tmp_path, monkeypatch):
    """Redirect all CSV and chart writes to tmp_path for every test.

    Prevents test runs from overwriting real results/ files (e.g. ic_analysis.csv).
    monkeypatch restores the original module-level values automatically after each test.
    """
    import step03_ic_analysis as s03
    import step04_turnover as s04
    import step05_buffer_zone as s05
    import step06_benchmark as s06
    import step08_factor_attribution as s08
    import step09_long_short as s09

    for mod in [s03, s04, s05, s06, s08, s09]:
        monkeypatch.setattr(mod, "RESULTS", tmp_path)
        monkeypatch.setattr(mod, "CHARTS", tmp_path)


# ── Shared DataFrames ─────────────────────────────────────────────────────────


@pytest.fixture
def sample_returns():
    """
    Minimal 40-row stock-returns DataFrame: 4 periods x 2 quintiles x 5 stocks.
    Covers the core columns used across all analysis scripts.
    """
    np.random.seed(0)
    periods = [
        ("2022-03-31", "2022-06-30"),
        ("2022-06-30", "2022-09-30"),
        ("2022-09-30", "2022-12-31"),
        ("2022-12-31", "2023-03-31"),
    ]
    sectors = ["Technology", "Financials", "Health Care", "Industrials", "Energy"]
    rows = []
    for s, e in periods:
        for q in range(1, 6):
            for i in range(10):
                gross = np.random.uniform(-0.05, 0.15)
                rows.append(
                    {
                        "symbol": f"Q{q}SYM{i:02d}",
                        "start_date": pd.Timestamp(s),
                        "end_date": pd.Timestamp(e),
                        "quintile": q,
                        "composite_score": np.random.randn(),
                        "value_score": np.random.uniform(0, 1),
                        "quality_score": np.random.uniform(0, 1),
                        "momentum_score": np.random.randn(),
                        "gross_return": gross,
                        "net_return": gross - 0.004,
                        "gics_sector": sectors[i % len(sectors)],
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture
def sample_price_series():
    """Daily price series covering ~14 months of business days."""
    dates = pd.date_range("2021-01-01", periods=300, freq="B")
    prices = pd.Series(
        100 * np.cumprod(1 + np.random.default_rng(42).normal(0, 0.01, 300)),
        index=dates,
    )
    return prices


@pytest.fixture
def sample_quarterly_returns():
    """Simple quarterly return series (8 periods) for stat functions."""
    return pd.Series([0.05, -0.03, 0.08, 0.02, -0.06, 0.10, 0.04, -0.01])
