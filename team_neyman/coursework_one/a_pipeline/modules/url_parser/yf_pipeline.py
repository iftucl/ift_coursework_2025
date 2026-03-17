import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
import yfinance as yf

from a_pipeline.modules.db_loader import postgres
from a_pipeline.modules.factors import calculate_factors


BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    """Loads settings from the central YAML file."""
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


config = load_config().get("yf_pipeline", {})
BATCH_SIZE = config.get("batch_size", 50)


def fetch_ohlcv_data(ticker_list: list, start_date=None, end_date=None):
    """
    Downloads, cleans, and uploads OHLCV market data from Yahoo Finance in batches.

    Args:
        ticker_list (list): A list of stock ticker symbols to download.
        start_date (str, optional): Start date in 'YYYY-MM-DD' format. Defaults to 5 years ago.
        end_date (str, optional): End date in 'YYYY-MM-DD' format. Defaults to today.

    Returns:
        None: Processes data in batches of 50 and updates the 'daily_ohlcv' PostgreSQL table.

    Note:
        Implements data transformation by stacking MultiIndex columns from yfinance
        and performing numeric cleansing (rounding prices, filling null volumes).
        Includes a 2-second sleep between batches to respect rate limits.
    """
    # Fetch past 5 years data
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        five_years_ago = datetime.now() - timedelta(days=5 * 365)
        start_date = five_years_ago.strftime("%Y-%m-%d")
    print(f"Starting pipeline: Fetching from {start_date} to {end_date}")

    # Fetching data with batches
    batch_size = BATCH_SIZE

    for i in range(0, len(ticker_list), batch_size):
        batch = ticker_list[i : i + batch_size]

        try:
            raw_data = yf.download(
                batch, start=start_date, end=end_date, interval="1d", auto_adjust=True
            )
            if raw_data.empty:
                print(f"Batch {batch} returned no data at all.")
                continue

            clean_data = raw_data.dropna(axis=1, how="all")
            if clean_data.empty:
                continue

            df_stacked = clean_data.stack(level=1, future_stack=True).reset_index()
            # Rename to align with database
            df_stacked = df_stacked.rename(
                columns={
                    "Date": "price_date",
                    "Ticker": "symbol",
                    "Open": "open_price",
                    "High": "high_price",
                    "Low": "low_price",
                    "Close": "close_price",
                    "Volume": "volume",
                }
            )
            # Cleanse data
            df_stacked["symbol"] = df_stacked["symbol"].str.strip()
            df_stacked["price_date"] = pd.to_datetime(df_stacked["price_date"]).dt.date
            price_cols = ["open_price", "high_price", "low_price", "close_price"]
            for col in price_cols:
                df_stacked[col] = pd.to_numeric(df_stacked[col], errors="coerce").round(
                    4
                )
            df_stacked["volume"] = (
                df_stacked["volume"]
                .replace([np.inf, -np.inf], 0)
                .fillna(0)
                .astype("int64")
            )
            df_stacked = df_stacked.dropna(
                subset=["symbol", "price_date", "close_price"]
            )

            postgres.update_ohlcv_data(df_stacked)
            print(f"Batch {i//batch_size + 1} uploaded successfully.")
            del df_stacked

            time.sleep(2)

        except Exception as e:
            print(f"Error downloading batch starting with {batch[0]}: {e}")


def format_duration(seconds):
    """
    Converts a duration in seconds into a human-readable string format.

    Args:
        seconds (int or float): The total number of seconds to format.

    Returns:
        str: A formatted string representing minutes and seconds (e.g., '5m 30s' or '45s').
    """
    minutes, sec = divmod(int(seconds), 60)
    if minutes > 0:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def update_ohlcv_batch():
    """
    Coordinates the incremental update of the OHLCV database table.

    This function manages the full lifecycle of a market data update: it ensures the
    target table exists, retrieves the current universe of tickers, and calculates
    the optimal start date based on the most recent record to prevent data gaps.

    Args:
        None

    Returns:
        None: Orchestrates data fetching and prints execution metrics to the console.

    Note:
        Implements a 20-day look-back overlap when updating existing data to account
        for potential upstream data revisions or late reporting by the provider.
    """
    start_time = time.time()

    # Create OHLCV table if there's no one
    postgres.create_ohlcv_table()

    df_companies = postgres.get_table(name="company_static")
    ticker_list = [symbol.strip() for symbol in df_companies["symbol"].tolist()]

    # Fetch data from the latest data date minus 20 days
    last_update = postgres.get_latest_date(table_name="daily_ohlcv")

    if last_update:
        start = (last_update - timedelta(days=20)).strftime("%Y-%m-%d")
        fetch_ohlcv_data(ticker_list, start_date=start)
    else:
        fetch_ohlcv_data(ticker_list)

    end_time = time.time()
    duration = end_time - start_time
    print("-" * 30)
    print("Pipeline execution finished.")
    print(f"Total duration: {format_duration(duration)}")
    print("-" * 30)


def calculate_liquidity_data(ticker_list: list, start_date=None):
    """
    Computes multi-horizon liquidity indicators and synchronizes them with PostgreSQL.

    This function calculates various volume and dollar-volume metrics (average, median,
    and Amihud illiquidity) across 20-day and 60-day windows to capture both short
    and medium-term trading dynamics.

    Args:
        ticker_list (list): A list of stock ticker symbols to process.
        start_date (datetime, optional): The target start date for the update.
            If provided, the function fetches 100 extra days of history to
            accommodate rolling window calculations.

    Returns:
        None: Filters results to the requested timeframe and updates the
            'liquidity_factors' database table.

    Note:
        Implements a 'warm-up' period by fetching data 100 days prior to
        start_date, ensuring that rolling averages (like 60-day ADV) are
        fully populated on the first day of the target period.
    """
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=100)).strftime("%Y-%m-%d")
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)

    data["return"] = calculate_factors.calculate_return(data)
    data["dollar_volume"] = calculate_factors.calculate_dollar_volume(data)
    data["adv_20d"] = calculate_factors.calculate_avg_volume(data, days=20)
    data["adv_60d"] = calculate_factors.calculate_avg_volume(data, days=60)
    data["mdv_20d"] = calculate_factors.calculate_median_volume(data, days=20)
    data["mdv_60d"] = calculate_factors.calculate_median_volume(data, days=60)
    data["addv_20d"] = calculate_factors.calculate_avg_dollar_volume(data, days=20)
    data["addv_60d"] = calculate_factors.calculate_avg_dollar_volume(data, days=60)
    data["mddv_20d"] = calculate_factors.calculate_median_dollar_volume(data, days=20)
    data["mddv_60d"] = calculate_factors.calculate_median_dollar_volume(data, days=60)
    data["amihud_illiquidity_20d"] = calculate_factors.calculate_amihud(data, days=20)
    data["amihud_illiquidity_60d"] = calculate_factors.calculate_amihud(data, days=60)

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data["price_date"] >= start_date]

    postgres.update_liquidity_data(data)


def calculate_trend_data(ticker_list: list, start_date=None):
    """
    Computes technical trend indicators and synchronizes them with PostgreSQL.

    This function calculates multiple Exponential Moving Averages (EMA), the Average
    Directional Index (ADX), Donchian Channels, and Rate of Change (ROC) metrics
    to determine the strength and direction of asset price trends.

    Args:
        ticker_list (list): A list of stock ticker symbols to process.
        start_date (datetime, optional): The target start date for the update.
            If provided, fetches 500 days of prior history to handle 200-day
            EMA and 52-week (252-day) high calculations.

    Returns:
        None: Updates the 'trend_factors' database table after filtering
            results to the target period.

    Note:
        Uses a 300-day 'warm-up' period to ensure the 200-day EMA and 52-week
        high metrics are fully stabilized before the target start_date.
    """
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=500)).strftime("%Y-%m-%d")
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)

    data["ma200"] = calculate_factors.calculate_ema(data, days=200)
    data["ma150"] = calculate_factors.calculate_ema(data, days=150)
    data["ma100"] = calculate_factors.calculate_ema(data, days=100)
    adx_series = calculate_factors.calculate_adx(data, days=14)
    if not adx_series.dropna().empty:
        data["adx14"] = adx_series.to_numpy().flatten()
    else:
        print("Warning: ADX calculation returned all Nulls. Skipping column update.")
    data["donchian_high_55"] = calculate_factors.calculate_donchian_high(data, days=55)
    data["donchian_high_120"] = calculate_factors.calculate_donchian_high(
        data, days=120
    )
    data["price_to_52w_high"] = calculate_factors.calculate_price_to_weeks_high(
        data, days=252
    )
    data["ma200_20d_roc"] = calculate_factors.calculate_ma_roc(
        data, ma_days=200, window_days=20
    )

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data["price_date"] >= start_date]

    postgres.update_trend_data(data)


def calculate_momentum_data(ticker_list: list, start_date=None):
    """
    Computes absolute and risk-adjusted momentum indicators for PostgreSQL synchronization.

    This function calculates returns and price momentum across various time horizons
    (1, 3, 6, and 12 months). It specifically implements lagged momentum (to account
    for short-term reversal) and risk-adjusted metrics to evaluate the quality
    of price trends.

    Args:
        ticker_list (list): A list of stock ticker symbols to process.
        start_date (datetime, optional): The target start date for the update.
            Fetches 500 days of history to accommodate 12-month lagged momentum
            and volatility scaling.

    Returns:
        None: Updates the 'momentum_factors' database table after filtering.

    Note:
        Calculates 'lagged' momentum (e.g., 12-month minus 1-month) to exclude
        the most recent month's performance, a common practice to avoid
        short-term mean reversion noise in trend signals.
    """
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=500)).strftime("%Y-%m-%d")
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)

    data["mom_12m"] = calculate_factors.calculate_lagged_momentum(data, total_months=12)
    data["mom_6m"] = calculate_factors.calculate_lagged_momentum(data, total_months=6)
    data["mom_3m"] = calculate_factors.calculate_lagged_momentum(data, total_months=3)
    data["ret_1m"] = calculate_factors.calculate_return(data, days=20)
    data["ret_3m"] = calculate_factors.calculate_return(data, days=60)
    data["ret_6m"] = calculate_factors.calculate_return(data, days=126)
    data["ret_12m"] = calculate_factors.calculate_return(data, days=252)
    data["risk_adj_mom_12m"] = calculate_factors.calculate_risk_adj_momentum(
        data, momentum_months=12, vol_days=60
    )
    data["risk_adj_ret_6m"] = calculate_factors.calculate_risk_adj_return(
        data, return_months=6, vol_days=60
    )
    data["positive_ret_pct_60d"] = calculate_factors.calculate_positive_return_percent(
        data, days=60
    )
    data["positive_ret_prc_120d"] = calculate_factors.calculate_positive_return_percent(
        data, days=120
    )

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data["price_date"] >= start_date]

    postgres.update_momentum_data(data)


def calculate_risk_data(ticker_list: list, start_date=None):
    """
    Computes multi-dimensional risk metrics and synchronizes them with PostgreSQL.

    This function calculates a comprehensive suite of risk indicators, including
    annualized volatility, downside deviation, maximum drawdown, and tail-risk
    measures like Value at Risk (VaR) and Conditional Value at Risk (CVaR).

    Args:
        ticker_list (list): A list of stock ticker symbols to process.
        start_date (datetime, optional): The target start date for the update.
            Fetches 300 days of prior history to accommodate 1-year (252-day)
            drawdown and volatility calculations.

    Returns:
        None: Updates the 'risk_factors' database table after filtering
            results to the target period.

    Note:
        Implements a 500-day 'warm-up' period to ensure that long-horizon metrics
        such as 1-year max drawdown and worst-case returns are fully populated
        and accurate from the requested start_date.
    """
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=500)).strftime("%Y-%m-%d")
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)

    data["vol_20d"] = calculate_factors.calculate_annualized_volatility(data, days=20)
    data["vol_60d"] = calculate_factors.calculate_annualized_volatility(data, days=60)
    data["vol_120d"] = calculate_factors.calculate_annualized_volatility(data, days=120)
    data["downside_vol_60d"] = calculate_factors.calculate_downside_volitility(
        data, days=60
    )
    data["max_drawdown_6m"] = calculate_factors.calculate_maximum_drawdown(
        data, days=126
    )
    data["max_drawdown_1y"] = calculate_factors.calculate_maximum_drawdown(
        data, days=252
    )
    data["historical_var_95_1m"] = calculate_factors.calculate_historical_var(
        data, days=20
    )
    data["historical_cvar_95_1m"] = calculate_factors.calculate_historical_cvar(
        data, days=20
    )
    data["worst_day_ret_1y"] = calculate_factors.calculate_worst_day_return(data)
    data["worst_week_ret_1y"] = calculate_factors.calculate_worst_week_return(data)

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data["price_date"] >= start_date]

    postgres.update_risk_data(data)


def calculate_mean_reversion_data(ticker_list: list, start_date=None):
    """
    Computes short-term mean reversion indicators and synchronizes them with PostgreSQL.

    This function focuses on identifying overbought or oversold conditions using
    Relative Strength Index (RSI) across multiple horizons, Bollinger Band
    positioning, and short-term price reversals.

    Args:
        ticker_list (list): A list of stock ticker symbols to process.
        start_date (datetime, optional): The target start date for the update.
            Fetches 300 days of history to ensure RSI and Bollinger Band
            calculations are fully stabilized.

    Returns:
        None: Updates the 'mean_reversion_factors' database table after filtering
            results to the target period.

    Note:
        Features the 'RSI-2' indicator, a common quantitative measure for
        extremely short-term mean reversion, along with Bollinger Band
        percentage to track price relative to volatility envelopes.
    """
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=300)).strftime("%Y-%m-%d")
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)

    data["rsi_2d"] = calculate_factors.calculate_rsi(data, days=2)
    data["rsi_5d"] = calculate_factors.calculate_rsi(data, days=5)
    data["rsi_14d"] = calculate_factors.calculate_rsi(data, days=14)
    data["bollinger_pct_20d"] = calculate_factors.calculate_bollingner(data)
    data["ret_5d"] = calculate_factors.calculate_return(data, days=5)
    data["ret_10d"] = calculate_factors.calculate_return(data, days=10)

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data["price_date"] >= start_date]

    postgres.update_mean_reversion_data(data)


def update_factors():
    """
    Orchestrates the end-to-end factor calculation and database synchronization pipeline.

    This function serves as the central control point for technical and fundamental
    factor updates. It ensures all target database tables are initialized, manages
    ticker batching to optimize memory usage, and retrieves the most recent
    timestamps for each factor category to enable efficient incremental updates.

    Args:
        None

    Returns:
        None: Coordinates five sub-pipelines (Liquidity, Trend, Momentum, Risk,
            and Mean Reversion) and provides console progress feedback.

    Note:
        Implements a batching strategy (50 tickers per batch) to prevent system
        memory exhaustion when processing large-scale OHLCV datasets and complex
        rolling window calculations.
    """
    # Creates tables if the tables don't exist
    postgres.create_liquidity_table()
    postgres.create_trend_table()
    postgres.create_momentum_table()
    postgres.create_risk_table()
    postgres.create_mean_reversion_table()

    df_companies = postgres.get_table(name="company_static")
    if df_companies is None or df_companies.empty:
        print("Error: Could not retrieve company list.")
        return

    ticker_list = [symbol.strip() for symbol in df_companies["symbol"].tolist()]
    # Calculate each factors for companies in batches
    batch_size = BATCH_SIZE

    # Get the latest data date for each table
    date_liquidity = postgres.get_latest_date(table_name="liquidity_factors")
    date_trend = postgres.get_latest_date(table_name="trend_factors")
    date_momentum = postgres.get_latest_date(table_name="momentum_factors")
    date_risk = postgres.get_latest_date(table_name="risk_factors")
    date_mean_rev = postgres.get_latest_date(table_name="mean_reversion_factors")

    total_batches = (len(ticker_list) // batch_size) + 1

    for i in range(0, len(ticker_list), batch_size):
        batch = ticker_list[i : i + batch_size]
        current_batch_num = (i // batch_size) + 1
        print(f"--- Processing Batch {current_batch_num} of {total_batches} ---")

        calculate_liquidity_data(batch, date_liquidity)
        calculate_trend_data(batch, date_trend)
        calculate_momentum_data(batch, date_momentum)
        calculate_risk_data(batch, date_risk)
        calculate_mean_reversion_data(batch, date_mean_rev)

    print("All factor updates completed successfully!")
