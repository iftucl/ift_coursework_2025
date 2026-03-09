import numpy as np
import pandas as pd
from functools import reduce
from modules.db_loader import postgres

def calculate_return(data: pd.DataFrame, days: int=1):
    return data.groupby('symbol')['close_price'].transform(lambda x: np.log(x / x.shift(days))).round(6)

def calculate_annualized_return(data: pd.DataFrame, days: int=1):
    return ((1 + calculate_return(data, days))**(252/days)-1).round(6)

def calculate_volatility(data: pd.DataFrame, days: int):
    if 'return' not in data.columns:
        data['return'] = calculate_return(data)
    return data.groupby('symbol')['return'].transform(lambda x: x.rolling(window=days, min_periods=int(days*0.8)).std()).round(6)

def calculate_annualized_volatility(data: pd.DataFrame, days: int):
    return (calculate_volatility(data, days)*np.sqrt(252)).round(6)

def calculate_downside_volitility(data: pd.DataFrame, days: int):
    if 'return' not in data.columns:
        data['return'] = calculate_return(data)
    data['negative_return'] = data['return'].clip(upper=0)
    return (data.groupby('symbol')['negative_return'].transform(lambda x: x.rolling(window=days, min_periods=int(days*0.8)).std())*np.sqrt(252)).round(6)

def calculate_avg_volume(data: pd.DataFrame, days: int):
    return data.groupby('symbol')['volume'].transform(lambda x: x.rolling(window=days).mean()).round(0)

def calculate_median_volume(data: pd.DataFrame, days: int):
    return data.groupby('symbol')['volume'].transform(lambda x: x.rolling(window=days).median()).round(0)

def calculate_dollar_volume(data: pd.DataFrame):
    dollar_vol = data['close_price'] * data['volume']
    dollar_vol = dollar_vol.replace([float('inf'), float('-inf')], 0).fillna(0)
    return dollar_vol.round(2)

def calculate_avg_dollar_volume(data: pd.DataFrame, days: int):
    if 'dollar_volume' not in data.columns:
        data['dollar_volume'] = calculate_dollar_volume(data)
    return data.groupby('symbol')['dollar_volume'].transform(lambda x: x.rolling(window=days).mean()).round(2)

def calculate_median_dollar_volume(data: pd.DataFrame, days: int):
    if 'dollar_volume' not in data.columns:
        data['dollar_volume'] = calculate_dollar_volume(data)
    return data.groupby('symbol')['dollar_volume'].transform(lambda x: x.rolling(window=days).median()).round(2)

def calculate_amihud(data: pd.DataFrame, days: int):
    if 'return' not in data.columns:
        data['return'] = calculate_return(data)
    if 'dollar_volume' not in data.columns:
        data['dollar_volume'] = calculate_dollar_volume(data)
    temp_dollar_vol = data['dollar_volume'].replace(0, np.nan)
    data['amihud_daily'] = (data['return'].abs() / temp_dollar_vol) * (10**6)
    return data.groupby('symbol')['amihud_daily'].transform(lambda x: x.rolling(window=days, min_periods=int(days*0.8)).mean()).round(10)

def calculate_sma(data: pd.DataFrame, days: int):
    return data.groupby('symbol')['close_price'].transform(lambda x: x.rolling(window=days).mean()).round(4)

def calculate_ema(data: pd.DataFrame, days: int):
    return data.groupby('symbol')['close_price'].transform(lambda x: x.ewm(span=days).mean()).round(4)

def calculate_adx(data: pd.DataFrame, days: int=14):
    def _compute_adx_per_symbol(group):
        high = group['high_price']
        low = group['low_price']
        prev_close = group['close_price'].shift(1)
        
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        atr = tr.ewm(alpha=1/days, adjust=False).mean()
        plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/days, adjust=False).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/days, adjust=False).mean() / atr

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.ewm(alpha=1/days, adjust=False).mean()
        
        return pd.Series(adx, index=group.index)

    return data.groupby('symbol', group_keys=False).apply(_compute_adx_per_symbol, include_groups=False).round(2)

def calculate_donchian_high(data: pd.DataFrame, days: int):
    return data.groupby('symbol')['high_price'].transform(lambda x: x.rolling(window=days).max()).round(4)

def calculate_donchian_low(data: pd.DataFrame, days: int):
    return data.groupby('symbol')['low_price'].transform(lambda x: x.rolling(window=days).min()).round(4)

def calculate_donchian_median(data: pd.DataFrame, days: int):
    donchian_high = calculate_donchian_high(data, days)
    donchian_low = calculate_donchian_low(data, days)
    return ((donchian_high + donchian_low) / 2).round(4)

def calculate_price_to_weeks_high(data: pd.DataFrame, days: int=252):
    rolling_52w_high = data.groupby('symbol')['high_price'].transform(lambda x: x.rolling(window=days).max())
    return (data['close_price'] / rolling_52w_high).round(4)

def calculate_ma_roc(data: pd.DataFrame, ma_days: int, window_days: int):
    if f'ma{ma_days}' not in data.columns:
        data[f'ma{ma_days}'] = calculate_sma(data, days=ma_days)
    lookback_ma = data.groupby('symbol')[f'ma{ma_days}'].shift(window_days)
    ma_roc = (data[f'ma{ma_days}'] / lookback_ma) - 1
    return ma_roc.round(6)

def calculate_lagged_momentum(data: pd.DataFrame, total_months: int, lag_months: int=1):
    price_start = data.groupby('symbol')['close_price'].shift(total_months*21)
    price_end = data.groupby('symbol')['close_price'].shift(lag_months*21)
    return np.log(price_end / price_start).round(6)

def calculate_risk_adj_momentum(data: pd.DataFrame, momentum_months: int, vol_days: int):
    if 'momentum' not in data.columns:
        data['momentum'] = calculate_lagged_momentum(data, momentum_months+1)
    if 'volatility' not in data.columns:
        data['volatility'] = calculate_annualized_volatility(data, vol_days)
    return (data['momentum']/data['volatility']).replace(0, np.nan).round(6)

def calculate_risk_adj_return(data: pd.DataFrame, return_months: int, vol_days: int):
    if 'annualized_return' not in data.columns:
        data['annualized_return'] = calculate_annualized_return(data, return_months*21)
    if 'volatility' not in data.columns:
        data['volatility'] = calculate_annualized_volatility(data, vol_days)
    return (data['return']/data['volatility']).replace(0, np.nan).round(6)

def calculate_positive_return_percent(data: pd.DataFrame, days: int):
    data['is_positive'] = (calculate_return(data) > 0).astype(int)
    return data.groupby('symbol')['is_positive'].transform(lambda x: x.rolling(window=days, min_periods=int(days*0.8)).mean()).round(6)

def calculate_maximum_drawdown(data: pd.DataFrame, days: int):
    rolling_peak = data.groupby('symbol')['close_price'].transform(lambda x: x.rolling(window=days, min_periods=1).max())
    data['raw_drawdown'] = (data['close_price'] - rolling_peak) / rolling_peak
    return data.groupby('symbol')['raw_drawdown'].transform(lambda x: x.rolling(window=days, min_periods=1).min()).round(6)

def calculate_historical_var(data: pd.DataFrame, capital: int=10000, confidence_level: float=0.95, days: int=1, rolling_window: int=252):
    data[f'return_{days}d'] = calculate_return(data, days)
    alpha = 1 - confidence_level
    rolling_var_pct = data.groupby('symbol')[f'return_{days}d'].transform(lambda x: x.rolling(window=rolling_window, min_periods=int(rolling_window*0.8)).quantile(alpha))
    var_dollar = (rolling_var_pct * capital).abs()
    return var_dollar.round(4)

def calculate_historical_cvar(data: pd.DataFrame, capital: int=10000, confidence_level: float=0.95, days: int=1, rolling_window: int=252):
    data[f'return_{days}d'] = calculate_return(data, days)
    alpha = 1 - confidence_level
    def _get_cvar(window_series):
        window_series = window_series.dropna()
        if window_series.empty:
            return np.nan
        var_threshold = window_series.quantile(alpha)
        tail_losses = window_series[window_series <= var_threshold]
        return tail_losses.mean()

    rolling_cvar_pct = data.groupby('symbol')[f'return_{days}d'].transform(lambda x: x.rolling(window=rolling_window, min_periods=int(rolling_window*0.8)).apply(_get_cvar))
    cvar_dollar = (rolling_cvar_pct * capital).abs()
    
    return cvar_dollar.round(4)

def calculate_worst_day_return(data: pd.DataFrame, days: int=252):
    if 'return' not in data.columns:
        data['return'] = calculate_return(data)
    return data.groupby('symbol')['return'].transform(lambda x: x.rolling(window=days, min_periods=int(days*0.8)).min()).round(6)

def calculate_worst_week_return(data: pd.DataFrame, days: int=252):
    data['weekly_return'] = calculate_return(data, 5)
    return data.groupby('symbol')['weekly_return'].transform(lambda x: x.rolling(window=days, min_periods=int(days*0.8)).min()).round(6)

def calculate_rsi(data: pd.DataFrame, days: int):
    delta = data.groupby('symbol')['close_price'].diff()

    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)

    avg_gain = gain.groupby(data['symbol']).transform(lambda x: x.ewm(alpha=1/days, adjust=False).mean())
    avg_loss = loss.groupby(data['symbol']).transform(lambda x: x.ewm(alpha=1/days, adjust=False).mean())

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))
    
    return rsi.fillna(100).round(2)

def calculate_bollingner(data: pd.DataFrame, days: int = 20, num_std: int = 2):
    mid_band = data.groupby('symbol')['close_price'].transform(lambda x: x.rolling(window=days).mean())
    
    std_dev = data.groupby('symbol')['close_price'].transform(lambda x: x.rolling(window=days).std())
    
    upper_band = mid_band + (std_dev * num_std)
    lower_band = mid_band - (std_dev * num_std)
    
    percent_b = (data['close_price'] - lower_band) / (upper_band - lower_band)
    
    return percent_b.round(6)

def calculate_ntm_eps(data: pd.DataFrame):
    if data is not None and not data.empty:
        eps_pivot = data.pivot(
            index='symbol',
            columns='period',
            values=['period_end_date', 'consensus_eps']
        )
        
        eps_pivot.columns = [f"{col[1].lower().replace(' ', '_')}_{col[0]}" for col in eps_pivot.columns]
        eps_pivot.reset_index(inplace=True)

        required_cols = ['current_year_period_end_date', 'current_year_consensus_eps', 'next_year_consensus_eps']
        for col in required_cols:
            if col not in eps_pivot.columns:
                eps_pivot[col] = pd.NA

        eps_pivot['current_year_period_end_date'] = pd.to_datetime(eps_pivot['current_year_period_end_date'])
        today = pd.Timestamp.today().normalize()
        
        days_left_fy1 = (eps_pivot['current_year_period_end_date'] - today).dt.days
        days_left_fy1 = days_left_fy1.clip(lower=0, upper=365) 

        weight_fy1 = days_left_fy1 / 365.0
        weight_fy2 = 1.0 - weight_fy1
        
        eps_pivot['current_year_consensus_eps'] = pd.to_numeric(eps_pivot['current_year_consensus_eps'], errors='coerce')
        eps_pivot['next_year_consensus_eps'] = pd.to_numeric(eps_pivot['next_year_consensus_eps'], errors='coerce')
        
        eps_pivot['ntm_eps'] = (
            (eps_pivot['current_year_consensus_eps'] * weight_fy1) + 
            (eps_pivot['next_year_consensus_eps'] * weight_fy2)
        ).round(2)

        return eps_pivot[['symbol', 'ntm_eps']]
    else:
        return pd.DataFrame(columns=['symbol', 'ntm_eps'])

def get_latest_indicators(symbols: list):
    latest_ohlcv = postgres.get_latest_data("daily_ohlcv", columns=["close_price"], symbols=symbols)
    latest_liquidity = postgres.get_latest_data("liquidity_factors", columns=["adv_20d", "addv_20d"], symbols=symbols)
    latest_trend = postgres.get_latest_data("trend_factors", columns=["ma200", "ma200_20d_roc"], symbols=symbols)
    latest_momentum = postgres.get_latest_data("momentum_factors", columns=["risk_adj_mom_12m", "positive_ret_pct_60d"], symbols=symbols)
    latest_risk = postgres.get_latest_data("risk_factors", columns=["vol_60d", "max_drawdown_1y", "historical_var_95_1m"], symbols=symbols)
    
    latest_eps_estimate = postgres.get_latest_data("eps_estimate", columns=["period", "period_end_date", "consensus_eps"], 
                                                   date_col="estimate_date", distinct_cols=["symbol", "period"], 
                                                   periods = ["Current Year", "Next Year"], symbols=symbols)
    latest_ntm_eps = calculate_ntm_eps(latest_eps_estimate)

    # Put the factor tables in a list so we can loop through them
    factor_dfs = [latest_liquidity, latest_trend, latest_momentum, latest_risk]
    
    # Drop the redundant 'price_date' columns from the factor tables
    for df in factor_dfs:
        if df is not None and not df.empty and 'price_date' in df.columns:
            df.drop(columns=['price_date'], inplace=True)

    # Compile the final list of DataFrames to merge
    all_dfs = [latest_ohlcv] + factor_dfs + [latest_ntm_eps]
    
    # Filter out any None or empty DataFrames just in case a database table is completely empty
    valid_dfs = [df for df in all_dfs if df is not None and not df.empty]
    if not valid_dfs:
        print("Error: No data retrieved from any tables.")
        return pd.DataFrame()

    # Merge everything on 'symbol' using a LEFT JOIN
    # This keeps every symbol in OHLCV, and attaches factors if they exist.
    final_merged_df = reduce(
        lambda left, right: pd.merge(left, right, on='symbol', how='left'), 
        valid_dfs
    )
    print(f"Successfully merged indicators for {len(final_merged_df)} symbols.")

    final_merged_df['price_above_ma200'] = final_merged_df['close_price'] > final_merged_df['ma200']
    final_merged_df['forward_earning_yields'] = final_merged_df['ntm_eps'] / final_merged_df['close_price']
    final_merged_df['rar_rank'] = final_merged_df['risk_adj_mom_12m'].rank(ascending=True, pct=True, na_option='keep')
    final_merged_df['stability_rank'] = final_merged_df['positive_ret_pct_60d'].rank(ascending=True, pct=True, na_option='keep')
    final_merged_df['momentum_score'] = 0.7 * final_merged_df['rar_rank'] + 0.3 * final_merged_df['stability_rank']
    final_merged_df['var_pct'] = final_merged_df['historical_var_95_1m'] / 10000

    return final_merged_df