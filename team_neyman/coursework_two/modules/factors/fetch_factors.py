import sys
import time
from functools import reduce
from pathlib import Path

import pandas as pd
import yaml

from modules.db_loader import postgres

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"
sys.path.append(str(BASE_DIR))


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["portfolio"]


def wait_for_postgres():
    """
    Implements a retry loop to verify PostgreSQL availability during system startup.

    Attempts to establish a connection via the 'postgres' utility, pausing for 5 seconds between failures. This ensures downstream services don't execute before the database container is fully initialized.

    Returns:
        bool: True if connection is successful.

    Raises:
        ConnectionError: If the database remains unreachable after 5 attempts.
    """

    print("Checking database connection...")
    retries = 5
    while retries > 0:
        if postgres.check_connection():
            print("Database connected!")
            return True
        print(f"Waiting for database... ({retries} retries left)")
        time.sleep(5)
        retries -= 1
    raise ConnectionError("Could not connect to PostgreSQL container.")


def calculate_ntm_eps(data: pd.DataFrame):
    """
    Computes the Next Twelve Months (NTM) consensus EPS using a time-weighted interpolation.

    Calculates a forward-looking EPS by blending the current fiscal year (FY1) and next fiscal year (FY2) estimates. The weight assigned to each year is determined by the number of days remaining in the current fiscal period, providing a rolling 12-month estimate.

    Args:
        data (pd.DataFrame): Consensus data containing 'symbol', 'period', 'period_end_date', and 'consensus_eps'.

    Returns:
        pd.DataFrame: A DataFrame containing 'symbol' and the calculated 'ntm_eps'.
    """

    if data is not None and not data.empty:
        eps_pivot = data.pivot(
            index="symbol",
            columns="period",
            values=["period_end_date", "consensus_eps"],
        )

        eps_pivot.columns = [
            f"{col[1].lower().replace(' ', '_')}_{col[0]}" for col in eps_pivot.columns
        ]
        eps_pivot.reset_index(inplace=True)

        required_cols = [
            "current_year_period_end_date",
            "current_year_consensus_eps",
            "next_year_consensus_eps",
        ]
        for col in required_cols:
            if col not in eps_pivot.columns:
                eps_pivot[col] = pd.NA

        eps_pivot["current_year_period_end_date"] = pd.to_datetime(
            eps_pivot["current_year_period_end_date"]
        )
        today = pd.Timestamp.today().normalize()

        days_left_fy1 = (eps_pivot["current_year_period_end_date"] - today).dt.days
        days_left_fy1 = days_left_fy1.clip(lower=0, upper=365)

        weight_fy1 = days_left_fy1 / 365.0
        weight_fy2 = 1.0 - weight_fy1

        eps_pivot["current_year_consensus_eps"] = pd.to_numeric(
            eps_pivot["current_year_consensus_eps"], errors="coerce"
        )
        eps_pivot["next_year_consensus_eps"] = pd.to_numeric(
            eps_pivot["next_year_consensus_eps"], errors="coerce"
        )

        eps_pivot["ntm_eps"] = (
            (eps_pivot["current_year_consensus_eps"] * weight_fy1)
            + (eps_pivot["next_year_consensus_eps"] * weight_fy2)
        ).round(2)

        return eps_pivot[["symbol", "ntm_eps"]]
    else:
        return pd.DataFrame(columns=["symbol", "ntm_eps"])


def get_latest_indicators(symbols: list, as_of_date: str):
    """
    Aggregates multi-factor financial indicators and computes derived strategy signals for a symbol list.

    Fetches technical, risk, and fundamental data from PostgreSQL, merges them into a single feature set, and calculates key execution metrics like Forward Earning Yields and trend confirmation.

    Args:
        symbols (list): Tickers to analyze.
        as_of_date (str): The reference date for the data snapshot.

    Returns:
        pd.DataFrame: Unified indicator set or an empty DataFrame on failure.
    """

    latest_ohlcv = postgres.get_latest_data(
        "daily_ohlcv", columns=["close_price"], symbols=symbols, as_of_date=as_of_date
    )
    latest_liquidity = postgres.get_latest_data(
        "liquidity_factors",
        columns=["adv_20d", "addv_20d"],
        symbols=symbols,
        as_of_date=as_of_date,
    )
    latest_trend = postgres.get_latest_data(
        "trend_factors",
        columns=["ma200", "ma200_20d_roc"],
        symbols=symbols,
        as_of_date=as_of_date,
    )
    latest_momentum = postgres.get_latest_data(
        "momentum_factors",
        columns=["risk_adj_mom_12m", "positive_ret_pct_60d"],
        symbols=symbols,
        as_of_date=as_of_date,
    )
    latest_risk = postgres.get_latest_data(
        "risk_factors",
        columns=["vol_60d", "max_drawdown_1y", "historical_var_95_1m"],
        symbols=symbols,
        as_of_date=as_of_date,
    )

    latest_eps_estimate = postgres.get_latest_data(
        "eps_estimate",
        columns=["period", "period_end_date", "consensus_eps"],
        date_col="estimate_date",
        distinct_cols=["symbol", "period"],
        periods=["Current Year", "Next Year"],
        symbols=symbols,
        as_of_date=as_of_date,
    )
    latest_ntm_eps = calculate_ntm_eps(latest_eps_estimate)

    factor_dfs = [latest_liquidity, latest_trend, latest_momentum, latest_risk]

    for df in factor_dfs:
        if df is not None and not df.empty and "price_date" in df.columns:
            df.drop(columns=["price_date"], inplace=True)

    all_dfs = [latest_ohlcv] + factor_dfs + [latest_ntm_eps]

    valid_dfs = [df for df in all_dfs if df is not None and not df.empty]
    if not valid_dfs:
        print("Error: No data retrieved from any tables.")
        return pd.DataFrame()

    final_merged_df = reduce(
        lambda left, right: pd.merge(left, right, on="symbol", how="left"), valid_dfs
    )
    print(f"Successfully merged indicators for {len(final_merged_df)} symbols.")

    final_merged_df["price_above_ma200"] = (
        final_merged_df["close_price"] > final_merged_df["ma200"]
    )
    final_merged_df["forward_earning_yields"] = (
        final_merged_df["ntm_eps"] / final_merged_df["close_price"]
    )
    final_merged_df["var_pct"] = final_merged_df["historical_var_95_1m"] / 10000

    return final_merged_df


def get_target_factors(run_date: str):
    """
    Orchestrates the retrieval of strategy-ready factors for a sector-filtered universe.

    Filters companies by GICS sector, fetches their latest multi-factor indicators
    (liquidity, momentum, risk, and valuation), and merges them with sector
    metadata for a specific trading date.

    Args:
        run_date (str): The target date for indicator retrieval (YYYY-MM-DD).

    Returns:
        pd.DataFrame: A comprehensive dataset of company factors and sector classifications.
    """

    target_sectors = load_config()["sectors"]
    target_companies = postgres.get_companies_by_sector(target_sectors)
    latest_indicators = get_latest_indicators(
        list(target_companies["symbol"]), as_of_date=run_date
    )
    target_df = pd.merge(
        latest_indicators,
        target_companies[["symbol", "gics_sector"]],
        on="symbol",
        how="inner",
    )
    print(f"Total companies count: {len(target_df)}")
    return target_df


def apply_filter(df: pd.DataFrame):
    """
    Refines the investment universe by applying liquidity hurdles and trend-following filters.

    The function implements a two-stage elimination process: first, it removes the bottom 15% of stocks by both share and dollar volume to ensure tradability; second, it enforces a trend regime filter by retaining only stocks trading above their 200-day moving average.

    Args:
        df (pd.DataFrame): Input universe with 'adv_20d', 'addv_20d', 'close_price', and 'ma200'.

    Returns:
        pd.DataFrame: A filtered subset of the original data.
    """

    # 1. Liquidity Filter
    adv_cutoff = df["adv_20d"].quantile(0.15)
    addv_cutoff = df["addv_20d"].quantile(0.15)
    liquidity_mask = (df["adv_20d"] > adv_cutoff) & (df["addv_20d"] > addv_cutoff)
    df = df[liquidity_mask].copy()
    print(f"Liquidity mask count: {len(df)}")

    # 2. Trend Filter
    trend_mask = df["close_price"] > (df["ma200"] * 0.8)
    df = df[trend_mask].copy()
    print(f"Trend mask count: {len(df)}")

    return df


def apply_scoring(df: pd.DataFrame, omit_factor: str = None):
    """
    Computes a multi-factor composite score for a universe of stocks using percentile ranking.

    The function applies a weighted-average model across five core dimensions: Momentum,
    Valuation (FEY), Trend, Risk, and Liquidity. It features dynamic re-normalization
    logic to handle the omission of specific factors without breaking the weighting
    schema (sum w = 1.0).

    Args:
        df (pd.DataFrame): Indicator data containing technical and fundamental metrics.
        omit_factor (str, optional): A factor name to exclude from the total score.

    Returns:
        pd.DataFrame: The original DataFrame enriched with individual component ranks
                      and the final 'total_score'.
    """

    config = load_config()

    weights = {
        "momentum": config.get("momentum_weight"),
        "fey": config.get("fey_weight"),
        "trend": config.get("trend_weight"),
        "risk": config.get("risk_weight"),
        "liquidity": config.get("liquidity_weight"),
    }

    if omit_factor and omit_factor in weights:
        weights[omit_factor] = 0.0
        total_remaining = sum(weights.values())
        if total_remaining > 0:
            weights = {k: v / total_remaining for k, v in weights.items()}

    # Momentum score
    df["rar_rank"] = df["risk_adj_mom_12m"].rank(
        ascending=True, pct=True, na_option="keep"
    )
    df["stability_rank"] = df["positive_ret_pct_60d"].rank(
        ascending=True, pct=True, na_option="keep"
    )
    df["momentum_score"] = 0.7 * df["rar_rank"] + 0.3 * df["stability_rank"]

    # Forward earnings yield score
    df["fey_score"] = df["forward_earning_yields"].rank(
        ascending=True, pct=True, na_option="top"
    )

    # Trend score
    df["trend_score"] = df["ma200_20d_roc"].rank(
        ascending=True, pct=True, na_option="keep"
    )

    # Risk score
    df["vol_rank"] = df["vol_60d"].rank(ascending=False, pct=True, na_option="keep")
    df["mdd_rank"] = df["max_drawdown_1y"].rank(
        ascending=False, pct=True, na_option="keep"
    )
    df["var_rank"] = df["var_pct"].rank(ascending=False, pct=True, na_option="keep")
    df["risk_score"] = (df["vol_rank"] + df["mdd_rank"] + df["var_rank"]) / 3

    # Liquidity score
    df["adv_rank"] = df["adv_20d"].rank(ascending=True, pct=True, na_option="keep")
    df["addv_rank"] = df["addv_20d"].rank(ascending=True, pct=True, na_option="keep")
    df["liquidity_score"] = (df["adv_rank"] + df["addv_rank"]) / 2

    # Total score
    df["total_score"] = (
        weights["momentum"] * df["momentum_score"]
        + weights["fey"] * df["fey_score"]
        + weights["trend"] * df["trend_score"]
        + weights["risk"] * df["risk_score"]
        + weights["liquidity"] * df["liquidity_score"]
    )

    """
    Z-score example
    df["rar_zscore"] = (df["risk_adj_mom_12m"] - df["risk_adj_mom_12m"].mean()) / df["risk_adj_mom_12m"].std()

    Handle outlier
    df["z_score_capped"] = df["z_score"].clip(-3, 3)

    Combine Z-scores
    df["composite_z"] = df["z_mom"] + df["z_value"]

    Map back to 0-1 scale using the normal distribution curve
    from scipy.stats import norm
    df["final_score_0_1"] = norm.cdf(df["composite_z"])
    """

    return df


def apply_weight(df: pd.DataFrame):
    """
    Determines final portfolio weightings by applying sector-specific and individual stock caps.

    Initializes weights based on 'total_score' and enters an iterative optimization loop
    to enforce risk constraints. If the 'Health Care' sector or any single security exceeds
    predefined limits, the excess weight is redistributed proportionally across the
    remaining universe until convergence.

    Args:
        df (pd.DataFrame): Data containing 'total_score' and 'gics_sector'.

    Returns:
        pd.DataFrame: The input DataFrame enriched with a normalized 'weight' column
                      that satisfies all risk mandates.
    """

    config = load_config()

    # Top score selection
    df["rank"] = df["total_score"].rank(ascending=False, method="first")
    cutoff_rank = max(30, len(df) * 0.5)
    df = df[df["rank"] <= cutoff_rank].copy()

    # Apply weights
    total_score_sum = df["total_score"].sum()
    if total_score_sum != 0:
        df["weight"] = df["total_score"] / total_score_sum
    else:
        print("No scoring data.")
        return

    # Cap constraints
    max_iterations = 100
    tolerance = 1e-10

    for i in range(max_iterations):

        hc_mask = df["gics_sector"] == "Health Care"
        non_hc_mask = ~hc_mask
        hc_total_weight = df.loc[hc_mask, "weight"].sum()

        if hc_total_weight > config["health_sector_cap"] + tolerance:
            hc_scale_factor = config["health_sector_cap"] / hc_total_weight
            df.loc[hc_mask, "weight"] *= hc_scale_factor

            released_weight = hc_total_weight - config["health_sector_cap"]
            non_hc_weight_sum = df.loc[non_hc_mask, "weight"].sum()

            if non_hc_weight_sum > 0:
                df.loc[non_hc_mask, "weight"] += (
                    df.loc[non_hc_mask, "weight"] / non_hc_weight_sum
                ) * released_weight

        if len(df) < 11:
            print(
                f"Warning: Only {len(df)} stocks selected. 10% cap might be impossible or cause high concentration."
            )
            break

        over_mask = df["weight"] > config["stock_cap"] + tolerance
        if over_mask.any():
            under_mask = df["weight"] < config["stock_cap"]

            excess_weight = df.loc[over_mask, "weight"].sum() - (
                over_mask.sum() * config["stock_cap"]
            )

            df.loc[over_mask, "weight"] = config["stock_cap"]

            under_weight_sum = df.loc[under_mask, "weight"].sum()
            if under_weight_sum > 0:
                df.loc[under_mask, "weight"] += (
                    df.loc[under_mask, "weight"] / under_weight_sum
                ) * excess_weight

        current_hc_weight = df[df["gics_sector"] == "Health Care"]["weight"].sum()
        current_max_stock = df["weight"].max()

        if (
            current_hc_weight <= config["health_sector_cap"] + tolerance
            and current_max_stock <= config["stock_cap"] + tolerance
        ):
            print(f"Constraints converged after {i+1} iterations.")
            break
    else:
        print("Warning: Weight constraints failed to converge within 100 iterations.")

    df["weight"] = df["weight"] / df["weight"].sum()

    return df
