import pandas as pd
from modules.db_loader import postgres
from modules.factors import calculate_factors
from modules.url_parser import dolthub_pipeline, yf_pipeline

if __name__ == "__main__":
    # Update latest data
    yf_pipeline.update_ohlcv_batch()
    yf_pipeline.update_factors()
    dolthub_pipeline.setup_dolt_database()
    # Get the factors needed
    target_sectors = ["Consumer Staples", "Utilities", "Health Care"]
    target_companies = postgres.get_companies_by_sector(target_sectors)
    latest_indicators = calculate_factors.get_latest_indicators(
        list(target_companies["symbol"])
    )
    target_df = pd.merge(
        latest_indicators,
        target_companies[["symbol", "gics_sector"]],
        on="symbol",
        how="inner",
    )
    print(f"Total companies count: {len(target_df)}")

    # Choose the companies
    # 1. Liquidity Filter
    adv_cutoff = target_df["adv_20d"].quantile(0.15)
    addv_cutoff = target_df["addv_20d"].quantile(0.15)
    liquidity_mask = (target_df["adv_20d"] > adv_cutoff) & (
        target_df["addv_20d"] > addv_cutoff
    )
    target_df = target_df[liquidity_mask]
    print(f"Liquidity mask count: {len(target_df)}")
    # 2. (Option A) Sequential Filter
    trend_mask = (target_df["close_price"] > target_df["ma200"]) & (
        target_df["ma200_20d_roc"] > 0
    )
    target_df = target_df[trend_mask]
    print(f"Trend mask count: {len(target_df)}")
    earnings_mask = target_df["forward_earning_yields"] > 0
    target_df = target_df[earnings_mask]
    print(f"Earnings mask count: {len(target_df)}")
    momentum_mask = target_df["momentum_score"] >= 0.4
    target_df = target_df[momentum_mask]
    print(f"Momentum mask count: {len(target_df)}")
    # 3. Risk Filter
    risk_mask = (
        (target_df["vol_60d"] < 0.3)
        & (target_df["max_drawdown_1y"] > -0.5)
        & (target_df["var_pct"] < 0.15)
    )
    target_df = target_df[risk_mask]
    print(f"Risk mask count: {len(target_df)}")
