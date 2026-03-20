"""Compute the composite Value + Quality factor score.

Factor methodology (Amundi + JPM approach):

    Eligibility (Step 2):
        - EPS > 0: loss-making firms excluded
        - GICS sectors Financials and Real Estate excluded

    Value component - JPM weights (Step 3-5):
        B/P 15%  E/Y 35%  CF/Y 35%  DY 15%

    Quality component - Amundi weights (Step 3-5):
        GPA 33%  WCA 17%  LTDE 33%  ROA 17%

    Per-metric scoring - sector-neutral (Step 4):
        1. Winsorise at 5th/95th percentile within each GICS sector group
        2. Percentile rank 0-1 within sector via rank / (N+1)
        3. Inverse-normal z-score  Z = norm.ppf(p)
        Sectors with fewer than 5 eligible firms are pooled.
        Firms missing a metric are excluded from that metric scoring but
        still scored on remaining metrics.

    Dimension scores (Step 5):
        Weighted sum of per-metric z-scores with weight renormalisation for
        any missing metrics -> re-rank across full universe -> dimension z-score.

    Composite (Step 6):
        50% Value_Z + 50% Quality_Z (renormalise if one dimension missing)
        -> re-rank across full universe -> composite z-score
        -> composite_percentile = rank / N
        -> quintile: Q1 = top 20% (best), Q5 = bottom 20% (worst)
"""

import logging

import numpy as np
import pandas as pd
from scipy.stats import norm

logger = logging.getLogger(__name__)

_EXCLUDED_SECTORS = frozenset({"Financials", "Real Estate"})
_SMALL_SECTOR_MIN = 5
_WINSOR_LOW = 0.05
_WINSOR_HIGH = 0.95

_VALUE_WEIGHTS = {"bp": 0.15, "ey": 0.35, "cfy": 0.35, "dy": 0.15}
_QUALITY_WEIGHTS = {"gpa": 0.33, "wca": 0.17, "ltde": 0.33, "roa": 0.17}


# ---------------------------------------------------------------------------
# Step 2 - Eligibility filter
# ---------------------------------------------------------------------------


def apply_eligibility_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Remove ineligible firms: EPS <= 0 or GICS Financials / Real Estate.

    Args:
        df: Input DataFrame with net_income_ttm, shares_outstanding, gics_sector.

    Returns:
        Filtered DataFrame with index reset.
    """
    eps = df["net_income_ttm"] / df["shares_outstanding"]
    eps_ok = eps > 0
    sector_ok = ~df["gics_sector"].isin(_EXCLUDED_SECTORS)
    mask = eps_ok & sector_ok
    logger.info(
        f"Eligibility filter removed {(~mask).sum()} of {len(df)} companies "
        f"({(~eps_ok).sum()} EPS <= 0, {(~sector_ok).sum()} excluded sector)."
    )
    return df[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Step 3 - Raw metric computation
# ---------------------------------------------------------------------------


def compute_raw_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute 8 raw factor metrics and market_cap.

    Value metrics:
        bp   = book_value / closing_price          exclude if book_value <= 0
        ey   = eps / closing_price                 exclude if eps <= 0
        cfy  = free_cash_flow / market_cap         exclude if FCF null or mktcap <= 0
        dy   = annual_dividend_rate / price        0.0 for non-payers

    Quality metrics:
        gpa  = gross_margin x roa / profit_margin  fallback: gross_margin
               simplifies to gross_profit / total_assets (Novy-Marx 2013)
        wca  = current_assets / current_liabilities  exclude if current_liab <= 0
        ltde = -(total_debt / book_value)           exclude if book_value <= 0
        roa  = net_income_ttm / total_assets        exclude if total_assets <= 0

    Args:
        df: DataFrame from data_loader.load_factor_inputs().

    Returns:
        DataFrame with market_cap, bp, ey, cfy, dy, gpa, wca, ltde, roa added.
    """
    df = df.copy()

    # London-listed stocks (suffix .L) quote in pence (GBX); convert to GBP
    # so price-based metrics are consistent with financials reported in GBP.
    is_london = df["symbol"].str.strip().str.endswith(".L")
    price = df["closing_price"].where(~is_london, df["closing_price"] / 100)

    shares = df["shares_outstanding"]
    net_income = df["net_income_ttm"]
    total_assets = df["total_assets"]
    book_value = df["book_value"]
    revenue = df["revenue"]
    gross_profit = df["gross_profit"]

    market_cap = price * shares
    df["market_cap"] = market_cap

    df["bp"] = np.where(book_value > 0, book_value / price, np.nan)

    eps = net_income / shares
    df["ey"] = np.where(eps > 0, eps / price, np.nan)

    df["cfy"] = np.where(
        df["free_cash_flow"].notna() & (market_cap > 0),
        df["free_cash_flow"] / market_cap,
        np.nan,
    )

    df["dy"] = np.where(price > 0, df["annual_dividend_rate"].fillna(0.0) / price, np.nan)

    valid_rev = revenue.notna() & (revenue > 0)
    valid_assets = total_assets.notna() & (total_assets > 0)

    gross_margin = pd.Series(np.where(valid_rev, gross_profit / revenue, np.nan), index=df.index)
    roa_arr = pd.Series(np.where(valid_assets, net_income / total_assets, np.nan), index=df.index)
    profit_margin = pd.Series(np.where(valid_rev, net_income / revenue, np.nan), index=df.index)

    # GPA = gross_margin x roa / profit_margin; fallback to gross_margin when
    # profit_margin is 0 or NaN to avoid division by zero
    pm_valid = profit_margin.notna() & (profit_margin != 0)
    df["gpa"] = np.where(
        pm_valid & gross_margin.notna() & roa_arr.notna(),
        gross_margin * roa_arr / profit_margin,
        gross_margin,
    )

    df["wca"] = np.where(
        df["current_liabilities"].notna() & (df["current_liabilities"] > 0),
        df["current_assets"] / df["current_liabilities"],
        np.nan,
    )

    df["ltde"] = np.where(book_value > 0, -(df["total_debt"] / book_value), np.nan)
    df["roa"] = np.where(valid_assets, net_income / total_assets, np.nan)

    return df


# ---------------------------------------------------------------------------
# Step 4 - Sector-neutral 3-step scoring
# ---------------------------------------------------------------------------


def _assign_groups(df: pd.DataFrame) -> pd.Series:
    """Pool small sectors (< _SMALL_SECTOR_MIN firms) into '__pooled__'."""
    counts = df["gics_sector"].value_counts()
    small = counts[counts < _SMALL_SECTOR_MIN].index
    groups = df["gics_sector"].copy()
    groups[groups.isin(small)] = "__pooled__"
    return groups


def _winsorise(series: pd.Series) -> pd.Series:
    """Clip values at the 5th and 95th percentiles within the group."""
    valid = series.dropna()
    if len(valid) < 2:
        return series
    lo, hi = valid.quantile([_WINSOR_LOW, _WINSOR_HIGH])
    return series.clip(lower=lo, upper=hi)


def _to_zscore(series: pd.Series) -> pd.Series:
    """Convert values to inverse-normal z-scores via percentile rank.

    Uses rank / (N+1) so percentiles never reach exactly 0 or 1,
    avoiding +/-inf from norm.ppf.
    """
    valid_mask = series.notna()
    n = valid_mask.sum()
    if n < 2:
        return pd.Series(np.nan, index=series.index)
    result = pd.Series(np.nan, index=series.index, dtype=float)
    ranks = series[valid_mask].rank(method="average")
    p = ranks / (n + 1)
    result[valid_mask] = p.apply(norm.ppf)
    return result


def score_all_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Apply 3-step Amundi scoring to all 8 metrics, sector-neutrally.

    Adds columns z_bp, z_ey, z_cfy, z_dy, z_gpa, z_wca, z_ltde, z_roa.

    Args:
        df: DataFrame with raw metric columns and gics_sector.

    Returns:
        DataFrame with z-score columns and internal __group__ column added.
    """
    df = df.copy()
    df["__group__"] = _assign_groups(df)

    for metric in list(_VALUE_WEIGHTS) + list(_QUALITY_WEIGHTS):
        z_col = f"z_{metric}"
        result = pd.Series(np.nan, index=df.index, dtype=float)
        for group, idx in df.groupby("__group__").groups.items():
            s = _winsorise(df.loc[idx, metric].copy())
            result.loc[idx] = _to_zscore(s).values
        df[z_col] = result

    return df


# ---------------------------------------------------------------------------
# Step 5 - Weighted dimension scores -> re-rank to dimension z-score
# ---------------------------------------------------------------------------


def _weighted_dimension(df: pd.DataFrame, z_cols: list, base_weights: dict) -> pd.Series:
    """Weighted sum of z-scores with renormalisation for missing metrics.

    Args:
        df: DataFrame with z-score columns.
        z_cols: List of z-score column names (e.g. ['z_bp', 'z_ey', ...]).
        base_weights: Dict mapping metric name -> weight (keys without 'z_' prefix).

    Returns:
        Series of raw weighted dimension scores (before re-ranking).
    """
    raw = pd.Series(np.nan, index=df.index, dtype=float)
    for i in df.index:
        available = {col: base_weights[col[2:]] for col in z_cols if pd.notna(df.loc[i, col])}
        if not available:
            continue
        total_w = sum(available.values())
        raw[i] = sum(df.loc[i, col] * w for col, w in available.items()) / total_w
    return raw


def compute_value_score(df: pd.DataFrame) -> pd.DataFrame:
    """Weighted value z-scores -> re-rank across universe -> value_score.

    Args:
        df: DataFrame with z_bp, z_ey, z_cfy, z_dy columns.

    Returns:
        DataFrame with value_score (z-score) column added.
    """
    df = df.copy()
    z_cols = [f"z_{m}" for m in _VALUE_WEIGHTS]
    raw = _weighted_dimension(df, z_cols, _VALUE_WEIGHTS)
    df["value_score"] = _to_zscore(raw)
    return df


def compute_quality_score(df: pd.DataFrame) -> pd.DataFrame:
    """Weighted quality z-scores -> re-rank across universe -> quality_score.

    Args:
        df: DataFrame with z_gpa, z_wca, z_ltde, z_roa columns.

    Returns:
        DataFrame with quality_score (z-score) column added.
    """
    df = df.copy()
    z_cols = [f"z_{m}" for m in _QUALITY_WEIGHTS]
    raw = _weighted_dimension(df, z_cols, _QUALITY_WEIGHTS)
    df["quality_score"] = _to_zscore(raw)
    return df


# ---------------------------------------------------------------------------
# Step 6 - Composite score, percentile, and quintile
# ---------------------------------------------------------------------------


def compute_composite(df: pd.DataFrame) -> pd.DataFrame:
    """50% Value_Z + 50% Quality_Z -> re-rank -> composite_score, percentile, quintile.

    Missing dimension: renormalise to full weight on the available dimension.

    Args:
        df: DataFrame with value_score and quality_score columns.

    Returns:
        DataFrame with composite_score, composite_percentile, quintile added.
    """
    df = df.copy()

    has_v = df["value_score"].notna()
    has_q = df["quality_score"].notna()

    composite_raw = pd.Series(np.nan, index=df.index, dtype=float)
    both = has_v & has_q
    composite_raw[both] = 0.5 * df.loc[both, "value_score"] + 0.5 * df.loc[both, "quality_score"]
    composite_raw[has_v & ~has_q] = df.loc[has_v & ~has_q, "value_score"]
    composite_raw[~has_v & has_q] = df.loc[~has_v & has_q, "quality_score"]

    df["composite_score"] = _to_zscore(composite_raw)

    valid = df["composite_score"].notna()
    n = valid.sum()
    pct = pd.Series(np.nan, index=df.index, dtype=float)
    if n > 0:
        ranks = df.loc[valid, "composite_score"].rank(method="average")
        pct[valid] = ranks / n
    df["composite_percentile"] = pct

    def _quintile(p):
        if pd.isna(p):
            return None
        if p >= 0.80:
            return 1
        if p >= 0.60:
            return 2
        if p >= 0.40:
            return 3
        if p >= 0.20:
            return 4
        return 5

    df["quintile"] = df["composite_percentile"].apply(_quintile)
    return df


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_factor_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    """Full pipeline: eligibility -> raw metrics -> sector z-scores -> composite.

    Args:
        df: DataFrame from data_loader.load_factor_inputs().

    Returns:
        DataFrame of eligible companies with all factor columns added.
        Internal column __group__ is dropped before return.
    """
    df = apply_eligibility_filter(df)
    df = compute_raw_metrics(df)
    df = score_all_metrics(df)
    df = compute_value_score(df)
    df = compute_quality_score(df)
    df = compute_composite(df)

    q_counts = df["quintile"].value_counts().sort_index().to_dict()
    logger.info(
        f"Factor pipeline complete: {len(df)} eligible companies - "
        f"{df['composite_score'].notna().sum()} composite scores. "
        f"Quintile distribution: {q_counts}"
    )

    df = df.drop(columns=["__group__"], errors="ignore")
    return df


# Backward-compatible alias (main.py calls run_value_factor before [0.4.0])
run_value_factor = run_factor_pipeline
