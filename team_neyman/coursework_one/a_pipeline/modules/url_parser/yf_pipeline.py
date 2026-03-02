import numpy as np
import pandas as pd
import yfinance as yf
import time
from datetime import datetime, timedelta
from modules.db_loader import postgres
from modules.factors import calculate_factors

def fetch_ohlcv_data(ticker_list: list, start_date=None, end_date=None):
    # Fetch past 5 years data
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    if start_date is None:
        five_years_ago = datetime.now() - timedelta(days=5*365)
        start_date = five_years_ago.strftime('%Y-%m-%d')
    print(f"Starting pipeline: Fetching from {start_date} to {end_date}")

    # Fetching data with batches
    batch_size = 50 

    for i in range(0, len(ticker_list), batch_size):
        batch = ticker_list[i : i + batch_size]
        
        try:
            raw_data = yf.download(batch, start=start_date, end=end_date, interval="1d", auto_adjust=True)
            if raw_data.empty:
                print(f"Batch {batch} returned no data at all.")
                continue

            clean_data = raw_data.dropna(axis=1, how='all')
            if clean_data.empty:
                continue

            df_stacked = clean_data.stack(level=1, future_stack=True).reset_index()
            # Rename to align with database
            df_stacked = df_stacked.rename(columns={
                'Date': 'price_date',
                'Ticker': 'symbol',
                'Open': 'open_price',
                'High': 'high_price',
                'Low': 'low_price',
                'Close': 'close_price',
                'Volume': 'volume'
            })
            # Cleanse data
            df_stacked['symbol'] = df_stacked['symbol'].str.strip()
            df_stacked['price_date'] = pd.to_datetime(df_stacked['price_date']).dt.date
            price_cols = ['open_price', 'high_price', 'low_price', 'close_price']
            for col in price_cols:
                df_stacked[col] = pd.to_numeric(df_stacked[col], errors='coerce').round(4)
            df_stacked['volume'] = df_stacked['volume'].replace([np.inf, -np.inf], 0).fillna(0).astype('int64')
            df_stacked = df_stacked.dropna(subset=['symbol', 'price_date', 'close_price'])

            postgres.update_ohlcv_data(df_stacked)
            print(f"Batch {i//batch_size + 1} uploaded successfully.")
            del df_stacked
            
            time.sleep(2) 
            
        except Exception as e:
            print(f"Error downloading batch starting with {batch[0]}: {e}")

# Converts total seconds into a readable string (e.g., 5m 30s).
def format_duration(seconds):
    minutes, sec = divmod(int(seconds), 60)
    if minutes > 0:
        return f"{minutes}m {sec}s"
    return f"{sec}s"

def update_ohlcv_batch():
    start_time = time.time()

    # Create OHLCV table if there's no one
    postgres.create_ohlcv_table()

    df_companies = postgres.get_company_static()
    ticker_list = [symbol.strip() for symbol in df_companies['symbol'].tolist()]
    
    # Fetch data from the latest data date minus 20 days to update missing or changing value
    last_update = postgres.get_latest_date(table_name='daily_ohlcv')

    if last_update:
        start = (last_update - timedelta(days=20)).strftime('%Y-%m-%d')
        fetch_ohlcv_data(ticker_list, start_date=start)
    else:
        fetch_ohlcv_data(ticker_list)

    end_time = time.time()
    duration = end_time - start_time
    print("-" * 30)
    print(f"Pipeline execution finished.")
    print(f"Total duration: {format_duration(duration)}")
    print("-" * 30)

def calculate_liquidity_data(ticker_list: list, start_date=None):
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=100)).strftime('%Y-%m-%d')
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)
    
    data['return'] = calculate_factors.calculate_return(data)
    data['dollar_volume'] = calculate_factors.calculate_dollar_volume(data)
    data['adv_20d'] = calculate_factors.calculate_avg_volume(data, days=20)
    data['adv_60d'] = calculate_factors.calculate_avg_volume(data, days=60)
    data['mdv_20d'] = calculate_factors.calculate_median_volume(data, days=20)
    data['mdv_60d'] = calculate_factors.calculate_median_volume(data, days=60)
    data['addv_20d'] = calculate_factors.calculate_avg_dollar_volume(data, days=20)
    data['addv_60d'] = calculate_factors.calculate_avg_dollar_volume(data, days=60)
    data['mddv_20d'] = calculate_factors.calculate_median_dollar_volume(data, days=20)
    data['mddv_60d'] = calculate_factors.calculate_median_dollar_volume(data, days=60)
    data['amihud_illiquidity_20d'] = calculate_factors.calculate_amihud(data, days=20)
    data['amihud_illiquidity_60d'] = calculate_factors.calculate_amihud(data, days=60)

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data['price_date'] >= start_date]

    postgres.update_liquidity_data(data)

def calculate_trend_data(ticker_list: list, start_date=None):
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=300)).strftime('%Y-%m-%d')
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)

    data['ma200'] = calculate_factors.calculate_ema(data, days=200)
    data['ma150'] = calculate_factors.calculate_ema(data, days=150)
    data['ma100'] = calculate_factors.calculate_ema(data, days=100)
    data['adx14'] = calculate_factors.calculate_adx(data, days=14)
    data['donchian_high_55'] = calculate_factors.calculate_donchian_high(data, days=55)
    data['donchian_high_120'] = calculate_factors.calculate_donchian_high(data, days=120)
    data['price_to_52w_high'] = calculate_factors.calculate_price_to_weeks_high(data, days=252)
    data['ma200_20d_slope'] = calculate_factors.calculate_ma_slope(data, ma_days=200, window_days=20)

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data['price_date'] >= start_date]

    postgres.update_trend_data(data)

def calculate_momentum_data(ticker_list: list, start_date=None):
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=300)).strftime('%Y-%m-%d')
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)
    
    data['mom_12m'] = calculate_factors.calculate_lagged_momentum(data, total_months=12)
    data['mom_6m'] = calculate_factors.calculate_lagged_momentum(data, total_months=6)
    data['mom_3m'] = calculate_factors.calculate_lagged_momentum(data, total_months=3)
    data['ret_1m'] = calculate_factors.calculate_return(data, days=20)
    data['ret_3m'] = calculate_factors.calculate_return(data, days=60)
    data['ret_6m'] = calculate_factors.calculate_return(data, days=126)
    data['ret_12m'] = calculate_factors.calculate_return(data, days=252)
    data['risk_adj_mom_12m'] = calculate_factors.calculate_risk_adj_momentum(data, momentum_months=12, vol_days=60)
    data['risk_adj_ret_6m'] = calculate_factors.calculate_risk_adj_return(data, return_months=6, vol_days=60)
    data['positive_ret_pct_60d'] = calculate_factors.calculate_positive_return_percent(data, days=60)
    data['positive_ret_prc_120d'] = calculate_factors.calculate_positive_return_percent(data, days=120)

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data['price_date'] >= start_date]

    postgres.update_momentum_data(data)

def calculate_risk_data(ticker_list: list, start_date=None):
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=300)).strftime('%Y-%m-%d')
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)

    data['vol_20d'] = calculate_factors.calculate_volatility(data, days=20)
    data['vol_60d'] = calculate_factors.calculate_volatility(data, days=60)
    data['vol_120d'] = calculate_factors.calculate_volatility(data, days=120)
    data['downside_vol_60d'] = calculate_factors.calculate_downside_volitility(data, days=60)
    data['max_drawdown_6m'] = calculate_factors.calculate_maximum_drawdown(data, days=126)
    data['max_drawdown_1y'] = calculate_factors.calculate_maximum_drawdown(data, days=252)
    data['historical_var_95_1d'] = calculate_factors.calculate_historical_var(data)
    data['historical_cvar_95_1d'] = calculate_factors.calculate_historical_cvar(data)
    data['worst_day_ret_1y'] = calculate_factors.calculate_worst_day_return(data)
    data['worst_week_ret_1y'] = calculate_factors.calculate_worst_week_return(data)

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data['price_date'] >= start_date]

    postgres.update_risk_data(data)

def calculate_mean_reversion_data(ticker_list: list, start_date=None):
    if start_date is not None:
        data_start_date = (start_date - timedelta(days=300)).strftime('%Y-%m-%d')
        data = postgres.get_ohlcv_data(ticker_list, data_start_date)
    else:
        data = postgres.get_ohlcv_data(ticker_list)

    data['rsi_2d'] = calculate_factors.calculate_rsi(data, days=2)
    data['rsi_5d'] = calculate_factors.calculate_rsi(data, days=5)
    data['rsi_14d'] = calculate_factors.calculate_rsi(data, days=14)
    data['bollinger_pct_20d'] = calculate_factors.calculate_bollingner(data)
    data['ret_5d'] = calculate_factors.calculate_return(data, days=5)
    data['ret_10d'] = calculate_factors.calculate_return(data, days=10)

    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        data = data[data['price_date'] >= start_date]

    postgres.update_mean_reversion_data(data)

def update_factors():
    # Creates tables if the tables don't exist 
    postgres.create_liquidity_table()
    postgres.create_trend_table()
    postgres.create_momentum_table()
    postgres.create_risk_table()
    postgres.create_mean_reversion_table()

    df_companies = postgres.get_company_static()
    if df_companies is None or df_companies.empty:
        print("Error: Could not retrieve company list.")
        return
    
    ticker_list = [symbol.strip() for symbol in df_companies['symbol'].tolist()]
    # Calculate each factors for companies in batches
    batch_size = 50 

    # Get the latest data date for each table
    date_liquidity = postgres.get_latest_date(table_name='liquidity_factors')
    date_trend = postgres.get_latest_date(table_name='trend_factors')
    date_momentum = postgres.get_latest_date(table_name='momentum_factors')
    date_risk = postgres.get_latest_date(table_name='risk_factors')
    date_mean_rev = postgres.get_latest_date(table_name='mean_reversion_factors')

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
