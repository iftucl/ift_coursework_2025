import sys
from pathlib import Path
import pandas as pd
from modules.db_loader import postgres
from modules.factors import calculate_factors

root_path = Path(__file__).resolve().parent.parent
sys.path.append(str(root_path))

if __name__ == "__main__":
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
    print(f"Companies count: {len(target_df)}")

    adv_cutoff = target_df["adv_20d"].quantile(0.15)
    addv_cutoff = target_df["addv_20d"].quantile(0.15)
    liquidity_mask = (target_df["adv_20d"] > adv_cutoff) & (
        target_df["addv_20d"] > addv_cutoff
    )
    liquidity_df = target_df[liquidity_mask]
    print(f"Liquidity mask count: {len(liquidity_df)}")

    trend_mask = (target_df["close_price"] > target_df["ma200"]) & (
        target_df["ma200_20d_roc"] > 0
    )
    trend_df = target_df[trend_mask]
    print(f"Trend mask count: {len(trend_df)}")

    earnings_mask = target_df["forward_earning_yields"] > 0
    earnings_df = target_df[earnings_mask]
    print(f"Earnings mask count: {len(earnings_df)}")
    print(target_df["forward_earning_yields"].describe())

    momentum_mask = target_df["momentum_score"] >= 0.4
    momentum_df = target_df[momentum_mask]
    print(f"Momentum mask count: {len(momentum_df)}")
    print(target_df["momentum_score"].describe())

    risk_mask = (
        (target_df["vol_60d"] < 0.3)
        & (target_df["max_drawdown_1y"] > -0.50)
        & (target_df["var_pct"] < 0.15)
    )
    risk_df = target_df[risk_mask]
    print(f"Risk mask count: {len(risk_df)}")
    print(target_df["vol_60d"].describe())
    print(target_df["max_drawdown_1y"].describe())
    print(target_df["var_pct"].describe())
