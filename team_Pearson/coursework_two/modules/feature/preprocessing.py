"""Cross-sectional preprocessing pipeline for factor sub-variables.

Each sub-variable passes through:
1. PIT availability filter  — only use data published on or before as_of_date
2. Missing-value filter     — drop symbols with insufficient coverage
3. Winsorization            — clip extreme values at configurable percentiles
4. Industry neutralization  — demean within GICS sector groups
5. Z-score standardization  — cross-sectional z-score (mean=0, std=1)

All operations are cross-sectional: they operate on a single date's snapshot
across all symbols.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def winsorize_cross_section(
    series: pd.Series,
    lower_pct: float = 0.025,
    upper_pct: float = 0.975,
) -> pd.Series:
    """Clip values at cross-sectional percentiles.

    :param series: Raw values indexed by symbol.
    :param lower_pct: Lower percentile threshold (default 2.5%).
    :param upper_pct: Upper percentile threshold (default 97.5%).
    :returns: Winsorized series.
    """
    if series.dropna().empty:
        return series
    lower = series.quantile(lower_pct)
    upper = series.quantile(upper_pct)
    return series.clip(lower=lower, upper=upper)


def neutralize_by_group(
    df: pd.DataFrame,
    value_col: str,
    group_col: str = "gics_sector",
) -> pd.Series:
    """Industry-neutralize values by demeaning within groups.

    For each group (e.g. GICS sector), subtract the group mean so that
    the resulting values reflect within-sector relative positioning.

    Symbols in groups with fewer than 2 members retain their raw values
    (no neutralization applied).

    :param df: DataFrame with at least ``value_col`` and ``group_col``.
    :param value_col: Column name holding the numeric values.
    :param group_col: Column name for grouping (default: ``gics_sector``).
    :returns: Neutralized values as a Series aligned to df's index.
    """
    result = df[value_col].copy()
    if group_col not in df.columns:
        logger.warning(
            "neutralize_by_group: column '%s' not found, skipping neutralization",
            group_col,
        )
        return result

    for group_name, group_df in df.groupby(group_col):
        valid = group_df[value_col].dropna()
        if len(valid) < 2:
            continue
        group_mean = valid.mean()
        result.loc[group_df.index] = group_df[value_col] - group_mean

    return result


def zscore_cross_section(series: pd.Series) -> pd.Series:
    """Compute cross-sectional Z-score (mean=0, std=1).

    :param series: Values indexed by symbol.
    :returns: Z-scored series. Returns NaN where std=0 or insufficient data.
    """
    valid = series.dropna()
    if len(valid) < 2:
        return pd.Series(np.nan, index=series.index)
    mean = valid.mean()
    std = valid.std(ddof=1)
    if std == 0 or not np.isfinite(std):
        return pd.Series(np.nan, index=series.index)
    return (series - mean) / std


def preprocess_cross_section(
    df: pd.DataFrame,
    value_col: str = "raw_value",
    group_col: str = "gics_sector",
    lower_pct: float = 0.025,
    upper_pct: float = 0.975,
    min_observations: int = 2,
) -> pd.DataFrame:
    """Run the full preprocessing pipeline on a single cross-sectional snapshot.

    Expects ``df`` to contain at minimum:
    - ``symbol``
    - ``value_col`` (raw sub-variable value)
    - ``group_col`` (e.g. ``gics_sector``) for neutralization

    Returns a copy of ``df`` with added columns:
    - ``winsorized_value``
    - ``neutralized_value``
    - ``z_score``

    :param df: Cross-sectional DataFrame (one row per symbol).
    :param value_col: Column holding raw numeric values.
    :param group_col: Column for industry neutralization grouping.
    :param lower_pct: Lower winsorization percentile.
    :param upper_pct: Upper winsorization percentile.
    :param min_observations: Minimum valid observations required for a usable
        cross-sectional score.
    :returns: DataFrame with preprocessing columns appended.
    """
    out = df.copy()
    valid_count = int(out[value_col].dropna().shape[0])

    # Step 1: Winsorize
    out["winsorized_value"] = winsorize_cross_section(
        out[value_col],
        lower_pct=lower_pct,
        upper_pct=upper_pct,
    )

    # Step 2: Industry neutralize
    out["neutralized_value"] = neutralize_by_group(
        out,
        value_col="winsorized_value",
        group_col=group_col,
    )

    # Step 3: Z-score
    if valid_count < max(2, int(min_observations)):
        out["z_score"] = np.nan
    else:
        out["z_score"] = zscore_cross_section(out["neutralized_value"])

    return out
