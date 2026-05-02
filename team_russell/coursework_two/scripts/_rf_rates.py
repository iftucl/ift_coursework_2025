"""Time-varying risk-free rate: 3-month T-bill yields for each holding period.

Source: FRED DGS3MO (3-Month Treasury Constant Maturity Rate), annualised %,
observed at the start of each quarterly holding period (Dec 2015 – Sep 2025).

The 40 start dates exactly match NEW_PERIODS in step02_extend_2015.py.
"""

import pandas as pd

# Annualised T-bill rate (decimal) at the start of each quarterly holding period.
# Key: ISO date string matching start_date column in stock_returns_10year.csv.
_RF_TABLE: dict[str, float] = {
    "2015-12-31": 0.0016,
    "2016-03-31": 0.0021,
    "2016-06-30": 0.0026,
    "2016-09-30": 0.0029,
    "2016-12-31": 0.0051,
    "2017-03-31": 0.0077,
    "2017-06-30": 0.0100,
    "2017-09-30": 0.0106,
    "2017-12-31": 0.0139,
    "2018-03-31": 0.0173,
    "2018-06-30": 0.0193,
    "2018-09-30": 0.0217,
    "2018-12-31": 0.0245,
    "2019-03-31": 0.0240,
    "2019-06-30": 0.0212,
    "2019-09-30": 0.0187,
    "2019-12-31": 0.0157,
    "2020-03-31": 0.0011,
    "2020-06-30": 0.0016,
    "2020-09-30": 0.0008,
    "2020-12-31": 0.0009,
    "2021-03-31": 0.0002,
    "2021-06-30": 0.0004,
    "2021-09-30": 0.0004,
    "2021-12-31": 0.0006,
    "2022-03-31": 0.0052,
    "2022-06-30": 0.0232,
    "2022-09-30": 0.0336,
    "2022-12-31": 0.0442,
    "2023-03-31": 0.0479,
    "2023-06-30": 0.0521,
    "2023-09-30": 0.0545,
    "2023-12-31": 0.0533,
    "2024-03-31": 0.0548,
    "2024-06-30": 0.0536,
    "2024-09-30": 0.0500,
    "2024-12-31": 0.0427,
    "2025-03-31": 0.0434,
    "2025-06-30": 0.0427,
    "2025-09-30": 0.0420,
}


def mean_rf_annual() -> float:
    """Mean annualised T-bill rate across all 40 periods (≈ 2.17%)."""
    return sum(_RF_TABLE.values()) / len(_RF_TABLE)


def get_rf_annual(start_date) -> float:
    """Annualised T-bill rate for the period starting on start_date.

    Falls back to the 40-period mean if the date is not in the table.
    """
    try:
        key = pd.Timestamp(start_date).strftime("%Y-%m-%d")
    except Exception:
        return mean_rf_annual()
    return _RF_TABLE.get(key, mean_rf_annual())


def get_rf_quarterly(start_date) -> float:
    """Quarterly T-bill rate for the period starting on start_date (annual / 4)."""
    return get_rf_annual(start_date) / 4


def rf_quarterly_series(start_dates) -> pd.Series:
    """Return a pd.Series of quarterly T-bill rates aligned to start_dates.

    Parameters
    ----------
    start_dates : pd.Index, pd.Series, or iterable of date-likes

    Returns
    -------
    pd.Series of quarterly rates with the same index as start_dates
    (or a RangeIndex if start_dates has no index).
    """
    if isinstance(start_dates, pd.Index):
        return pd.Series(
            [get_rf_quarterly(d) for d in start_dates],
            index=start_dates,
        )
    if isinstance(start_dates, pd.Series):
        return start_dates.map(get_rf_quarterly).rename("rf_quarterly")
    # fallback for any iterable
    vals = [get_rf_quarterly(d) for d in start_dates]
    return pd.Series(vals)
