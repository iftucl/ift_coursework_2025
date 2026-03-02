import numpy as np
import pandas as pd

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

def calculate_lagged_momentum(data: pd.DataFrame, total_months: int, lag_months: int=1):
    price_start = data.groupby('symbol')['close_price'].shift(total_months*21)
    price_end = data.groupby('symbol')['close_price'].shift(lag_months*21)
    return ((price_end / price_start) - 1).round(6)

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