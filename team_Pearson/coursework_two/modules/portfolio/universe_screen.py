"""Investable universe screen for CW2 portfolio construction.

This stage sits before portfolio selection. It removes names that are not
appropriate for the live candidate universe because they are too small,
insufficiently liquid, or outside the desired country scope.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_MIN_LOG_MARKET_CAP = 20.0
_DEFAULT_MIN_LIQUIDITY_20D = 2_000_000.0
_DEFAULT_MARKET_CAP_BOTTOM_PERCENTILE = 0.20
_DEFAULT_LIQUIDITY_BOTTOM_PERCENTILE = 0.20


def build_investable_universe(
    risk_data: pd.DataFrame,
    company_info: pd.DataFrame,
    *,
    as_of_date: date,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return per-symbol universe eligibility records.

    The screen combines hard floors and cross-sectional percentile filters for
    size and liquidity. This is more robust than a single absolute threshold
    when the upstream universe may mix large-cap and mid-cap names.
    """
    cfg = (config or {}).get("investable_universe", {})
    country_allowlist = {
        str(x).strip().upper() for x in (cfg.get("country_allowlist") or []) if str(x).strip()
    }
    min_log_mcap = _safe_float(cfg.get("min_market_cap_log", _DEFAULT_MIN_LOG_MARKET_CAP))
    min_liq = _safe_float(cfg.get("min_liquidity_20d", _DEFAULT_MIN_LIQUIDITY_20D))
    market_cap_bottom_pct = _safe_float(
        cfg.get("market_cap_bottom_percentile", _DEFAULT_MARKET_CAP_BOTTOM_PERCENTILE)
    )
    liquidity_bottom_pct = _safe_float(
        cfg.get("liquidity_bottom_percentile", _DEFAULT_LIQUIDITY_BOTTOM_PERCENTILE)
    )

    if risk_data is None or risk_data.empty:
        return []

    info = (
        company_info.copy()
        if company_info is not None and not company_info.empty
        else pd.DataFrame(columns=["symbol", "gics_sector", "country"])
    )
    if "symbol" not in info.columns:
        info["symbol"] = []
    if "gics_sector" not in info.columns:
        info["gics_sector"] = "Unknown"
    if "country" not in info.columns:
        info["country"] = None

    df = risk_data.copy()
    df = df.merge(
        info[["symbol", "gics_sector", "country"]].drop_duplicates(subset=["symbol"]),
        on="symbol",
        how="left",
    )
    df["gics_sector"] = df["gics_sector"].fillna("Unknown")
    df["country"] = df["country"].where(df["country"].notna(), None)

    df["pass_country"] = True
    if country_allowlist:
        df["pass_country"] = df["country"].astype(str).str.upper().isin(country_allowlist)

    eligible_for_cutoffs = df[df["pass_country"]].copy()

    market_cap_cutoff = None
    if (
        market_cap_bottom_pct is not None
        and 0.0 < market_cap_bottom_pct < 1.0
        and not eligible_for_cutoffs["log_market_cap"].dropna().empty
    ):
        market_cap_cutoff = float(
            np.percentile(
                eligible_for_cutoffs["log_market_cap"].dropna(),
                market_cap_bottom_pct * 100.0,
            )
        )

    liquidity_cutoff = None
    if (
        liquidity_bottom_pct is not None
        and 0.0 < liquidity_bottom_pct < 1.0
        and not eligible_for_cutoffs["liquidity_20d"].dropna().empty
    ):
        liquidity_cutoff = float(
            np.percentile(
                eligible_for_cutoffs["liquidity_20d"].dropna(),
                liquidity_bottom_pct * 100.0,
            )
        )

    df["pass_market_cap"] = df["log_market_cap"].apply(
        lambda v: _passes_floor_and_percentile(v, min_log_mcap, market_cap_cutoff)
    )
    df["pass_liquidity"] = df["liquidity_20d"].apply(
        lambda v: _passes_floor_and_percentile(v, min_liq, liquidity_cutoff)
    )
    df["pass_all"] = df["pass_country"] & df["pass_market_cap"] & df["pass_liquidity"]

    records: List[Dict[str, Any]] = []
    for _, row in df.sort_values("symbol").iterrows():
        records.append(
            {
                "as_of_date": as_of_date.isoformat(),
                "symbol": row["symbol"],
                "country": row.get("country"),
                "gics_sector": row.get("gics_sector"),
                "log_market_cap": _safe_float(row.get("log_market_cap")),
                "liquidity_20d": _safe_float(row.get("liquidity_20d")),
                "pass_country": bool(row.get("pass_country")),
                "pass_market_cap": bool(row.get("pass_market_cap")),
                "pass_liquidity": bool(row.get("pass_liquidity")),
                "pass_all": bool(row.get("pass_all")),
            }
        )

    passed = sum(1 for rec in records if rec["pass_all"])
    logger.info(
        "investable_universe: as_of=%s total=%d passed=%d "
        "(country_filter=%s market_cap_floor=%s market_cap_cutoff=%s liquidity_floor=%s liquidity_cutoff=%s)",
        as_of_date,
        len(records),
        passed,
        sorted(country_allowlist) if country_allowlist else "ALL",
        f"{min_log_mcap:.2f}" if min_log_mcap is not None else "disabled",
        f"{market_cap_cutoff:.2f}" if market_cap_cutoff is not None else "disabled",
        f"{min_liq:.0f}" if min_liq is not None else "disabled",
        f"{liquidity_cutoff:.0f}" if liquidity_cutoff is not None else "disabled",
    )
    return records


def _passes_floor_and_percentile(
    value: Any,
    floor_value: Optional[float],
    percentile_cutoff: Optional[float],
) -> bool:
    numeric = _safe_float(value)
    if numeric is None:
        return False
    if floor_value is not None and numeric < floor_value:
        return False
    if percentile_cutoff is not None and numeric < percentile_cutoff:
        return False
    return True


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None
