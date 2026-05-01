from __future__ import annotations

import numpy as np
import pandas as pd


def _normalise_weights(values: pd.Series) -> pd.Series:
    total = values.sum()
    if total <= 0:
        return pd.Series(np.repeat(1 / len(values), len(values)), index=values.index)
    return values / total


def _apply_sector_weight_cap(portfolio: pd.DataFrame, sector_cap_weight: float) -> pd.DataFrame:
    if "sector" not in portfolio.columns or sector_cap_weight <= 0 or sector_cap_weight >= 1.0:
        return portfolio

    weights = portfolio["weight"].copy().astype(float)
    sectors = portfolio["sector"].values

    for _ in range(50):
        temp = pd.DataFrame({"weight": weights, "sector": sectors})
        sector_total = temp.groupby("sector")["weight"].transform("sum")
        if not (sector_total > sector_cap_weight + 1e-9).any():
            break
        scale = (sector_cap_weight / sector_total).clip(upper=1.0)
        weights = weights * scale.values
        total = weights.sum()
        if total > 0:
            weights /= total

    result = portfolio.copy()
    result["weight"] = weights
    return result


def build_portfolio(selections: pd.DataFrame, config: dict, weighting_method: str | None = None) -> pd.DataFrame:
    if selections.empty:
        return selections.copy()

    portfolio = selections.copy()
    method = weighting_method or config["portfolio"].get("baseline_weighting", "equal_weight")
    max_names = config["portfolio"].get("max_names", len(portfolio))
    sector_cap_weight = float(config["portfolio"].get("sector_cap_weight", 1.0))
    portfolio = portfolio.head(max_names).copy()

    if method == "rank_weighted" and "selection_rank" in portfolio.columns:
        raw_weights = (len(portfolio) + 1) - portfolio["selection_rank"]
    elif method == "inverse_volatility" and "atr_14" in portfolio.columns:
        raw_weights = 1 / portfolio["atr_14"].replace(0, np.nan).fillna(np.nan)
        raw_weights = raw_weights.replace([np.inf, -np.inf], np.nan).fillna(0)
    else:
        raw_weights = pd.Series(np.ones(len(portfolio)), index=portfolio.index)
        method = "equal_weight"

    portfolio["weight"] = _normalise_weights(raw_weights)
    portfolio = _apply_sector_weight_cap(portfolio, sector_cap_weight)
    portfolio["weighting_method"] = method
    return portfolio.reset_index(drop=True)
