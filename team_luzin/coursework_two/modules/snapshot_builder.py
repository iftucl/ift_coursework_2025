from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _resolve_factor_windows(config: dict) -> tuple[int, int, int, int]:
    min_rows = int(config.get("universe", {}).get("min_rows_per_symbol", 24))
    base_window = max(min_rows, 2)
    momentum_window = base_window
    volatility_window = base_window
    liquidity_window = max(min(60, base_window), 2)
    var_window = max(base_window - 1, 2)
    return momentum_window, volatility_window, liquidity_window, var_window


def _normalise_price_columns(price_history: pd.DataFrame) -> pd.DataFrame:
    if price_history.empty:
        return price_history.copy()

    renamed = price_history.rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "close",
            "Volume": "volume",
        }
    ).copy()
    if "date" in renamed.columns:
        renamed["date"] = pd.to_datetime(renamed["date"], errors="coerce", utc=True).dt.tz_localize(None)
    return renamed.dropna(subset=["date"]).reset_index(drop=True)


def _build_sector_metadata(cw1_inputs) -> pd.DataFrame:
    candidates = [
        getattr(cw1_inputs, "factors", pd.DataFrame()),
        getattr(cw1_inputs, "selections", pd.DataFrame()),
        getattr(cw1_inputs, "universe_snapshot", pd.DataFrame()),
        getattr(cw1_inputs, "historical_factors", pd.DataFrame()),
    ]
    for candidate in candidates:
        if candidate.empty or "symbol" not in candidate.columns:
            continue
        metadata = candidate.copy()
        if "normalized_sector" in metadata.columns and "sector" not in metadata.columns:
            metadata["sector"] = metadata["normalized_sector"]
        if "gics_sector" not in metadata.columns and "sector" in metadata.columns:
            metadata["gics_sector"] = metadata["sector"]
        available = [column for column in ["symbol", "gics_sector", "sector"] if column in metadata.columns]
        if len(available) >= 2:
            return metadata[available].drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    return pd.DataFrame(columns=["symbol", "gics_sector", "sector"])


def _calculate_symbol_factor_history(
    symbol_prices: pd.DataFrame,
    momentum_window: int,
    volatility_window: int,
    liquidity_window: int,
    var_window: int,
) -> pd.DataFrame:
    df = symbol_prices.sort_values("date").copy()
    if df.empty:
        return df

    df["log_return"] = np.log(df["close"] / df["close"].shift(1))
    annualisation_scale = math.sqrt(min(volatility_window, 252))
    df["momentum_252"] = df["close"] / df["close"].shift(momentum_window) - 1
    df["volatility_252"] = (
        df["log_return"].rolling(volatility_window, min_periods=volatility_window).std(ddof=1) * annualisation_scale
    )
    df["risk_adjusted_momentum_252"] = df["momentum_252"] / df["volatility_252"].replace(0, np.nan)
    df["volume_60d_avg"] = (
        (df["close"] * df["volume"]).rolling(liquidity_window, min_periods=liquidity_window).mean()
    )
    df["var_95"] = df["log_return"].rolling(var_window, min_periods=var_window).quantile(0.05)

    previous_close = df["close"].shift(1)
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - previous_close).abs()
    low_close = (df["low"] - previous_close).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr_14"] = true_range.ewm(span=14, adjust=False).mean()
    df["atr_pct"] = (df["atr_14"] / df["close"]) * 100
    return df


def _select_month_end_rows(df: pd.DataFrame) -> pd.DataFrame:
    month_end_rows = (
        df.sort_values("date")
        .groupby(pd.Grouper(key="date", freq="ME"))
        .tail(1)
        .copy()
    )
    month_end_rows["snapshot_date"] = month_end_rows["date"].dt.to_period("M").dt.to_timestamp("M")
    return month_end_rows


def _compute_sector_relative_scores(factors_history: pd.DataFrame) -> pd.DataFrame:
    if factors_history.empty:
        return factors_history.copy()

    df = factors_history.copy()
    df["sector"] = df["sector"].fillna("Unknown")
    required = ["risk_adjusted_momentum_252", "volume_60d_avg", "var_95"]
    df = df.dropna(subset=[column for column in required if column in df.columns]).copy()
    if df.empty:
        return df

    grouped = df.groupby(["snapshot_date", "sector"], dropna=False)
    df["z_momentum"] = grouped["risk_adjusted_momentum_252"].transform(
        lambda series: ((series - series.mean()) / series.std(ddof=1)).replace([np.inf, -np.inf], np.nan).fillna(0)
    )
    df["z_liquidity"] = grouped["volume_60d_avg"].transform(
        lambda series: ((series - series.mean()) / series.std(ddof=1)).replace([np.inf, -np.inf], np.nan).fillna(0)
    )
    df["risk_proxy"] = -df["var_95"]
    df["z_risk"] = grouped["risk_proxy"].transform(
        lambda series: ((series - series.mean()) / series.std(ddof=1)).replace([np.inf, -np.inf], np.nan).fillna(0)
    )
    df["composite_score"] = 0.6 * df["z_momentum"] + 0.2 * df["z_liquidity"] - 0.2 * df["z_risk"]
    df["composite_rank"] = df.groupby("snapshot_date")["composite_score"].rank(ascending=False, method="min").astype(int)
    return df.drop(columns=["risk_proxy"])


def _build_selection_history(scored_factors: pd.DataFrame) -> pd.DataFrame:
    if scored_factors.empty:
        return pd.DataFrame()

    selected_frames = []
    for (snapshot_date, sector), sector_frame in scored_factors.groupby(["snapshot_date", "sector"], dropna=False):
        ranked = sector_frame.sort_values(["composite_score", "symbol"], ascending=[False, True]).copy()
        n_select = max(1, int(np.ceil(len(ranked) * 0.20)))
        ranked["sector_rank"] = range(1, len(ranked) + 1)
        selected = ranked.head(n_select).copy()
        selected["snapshot_date"] = snapshot_date
        selected["sector"] = sector
        selected_frames.append(selected)

    if not selected_frames:
        return pd.DataFrame()

    selection_history = pd.concat(selected_frames, ignore_index=True)
    selection_history = selection_history.sort_values(["snapshot_date", "composite_score"], ascending=[True, False])
    columns = [
        "snapshot_date",
        "symbol",
        "gics_sector",
        "sector",
        "composite_score",
        "sector_rank",
        "z_momentum",
        "z_liquidity",
        "z_risk",
    ]
    available = [column for column in columns if column in selection_history.columns]
    return selection_history[available].reset_index(drop=True)


def build_monthly_snapshot_history(cw1_inputs, config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = _normalise_price_columns(getattr(cw1_inputs, "price_history", pd.DataFrame()))
    required_columns = {"symbol", "date", "open", "high", "low", "close", "volume"}
    if prices.empty or not required_columns.issubset(prices.columns):
        return pd.DataFrame(), pd.DataFrame()

    metadata = _build_sector_metadata(cw1_inputs)
    min_rows = config.get("universe", {}).get("min_rows_per_symbol", 252)
    momentum_window, volatility_window, liquidity_window, var_window = _resolve_factor_windows(config)
    valid_symbols = prices.groupby("symbol").size()
    valid_symbols = valid_symbols[
        valid_symbols >= max(min_rows, momentum_window, volatility_window, liquidity_window, var_window + 1)
    ].index
    prices = prices[prices["symbol"].isin(valid_symbols)].copy()
    if prices.empty:
        return pd.DataFrame(), pd.DataFrame()

    factor_frames = []
    for symbol, symbol_prices in prices.groupby("symbol", sort=True):
        history = _calculate_symbol_factor_history(
            symbol_prices,
            momentum_window,
            volatility_window,
            liquidity_window,
            var_window,
        )
        history = _select_month_end_rows(history)
        history["symbol"] = symbol
        factor_frames.append(history)

    if not factor_frames:
        return pd.DataFrame(), pd.DataFrame()

    factors_history = pd.concat(factor_frames, ignore_index=True)
    factors_history = factors_history.merge(metadata, on="symbol", how="left")
    if "sector" not in factors_history.columns and "gics_sector" in factors_history.columns:
        factors_history["sector"] = factors_history["gics_sector"]

    factors_history = factors_history.dropna(
        subset=["snapshot_date", "momentum_252", "volatility_252", "risk_adjusted_momentum_252", "volume_60d_avg", "var_95"]
    ).copy()
    if factors_history.empty:
        return pd.DataFrame(), pd.DataFrame()

    factor_columns = [
        "snapshot_date",
        "symbol",
        "gics_sector",
        "sector",
        "momentum_252",
        "volatility_252",
        "risk_adjusted_momentum_252",
        "volume_60d_avg",
        "var_95",
        "atr_pct",
        "atr_14",
    ]
    available_factor_columns = [column for column in factor_columns if column in factors_history.columns]
    factors_history = factors_history[available_factor_columns].sort_values(["snapshot_date", "symbol"]).reset_index(drop=True)

    scored_factors = _compute_sector_relative_scores(factors_history)
    selection_history = _build_selection_history(scored_factors)
    return scored_factors.reset_index(drop=True), selection_history
