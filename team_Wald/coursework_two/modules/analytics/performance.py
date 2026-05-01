"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Performance evaluation metrics
Project : CW2 - Value-Sentiment Investment Strategy

Computes absolute and relative performance metrics:
  - Annualised return and volatility
  - Sharpe ratio (Lo, 2002)
  - Sortino ratio (downside-only risk)
  - Calmar ratio (return / max drawdown)
  - Information ratio (active return / tracking error)
  - Maximum drawdown and drawdown series

Ref: Part A §A7.1
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


def compute_performance_summary(
    returns: pd.Series,
    benchmark_returns: pd.Series = None,
    risk_free_rate: float = 0.04,
    portfolio_name: str = 'Portfolio',
) -> dict:
    """Compute comprehensive performance metrics for a return series.

    :param returns: Daily portfolio return series
    :type returns: pd.Series
    :param benchmark_returns: Daily benchmark return series (optional)
    :type benchmark_returns: pd.Series or None
    :param risk_free_rate: Annual risk-free rate for Sharpe calculation
    :type risk_free_rate: float
    :param portfolio_name: Name label for the portfolio
    :type portfolio_name: str
    :returns: Dict of performance metrics
    :rtype: dict
    """
    if len(returns) == 0:
        return _empty_metrics(portfolio_name)

    # Daily risk-free rate
    rf_daily = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1

    # Annualised return
    total_return = (1 + returns).prod() - 1
    n_days = len(returns)
    ann_return = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / n_days) - 1

    # Annualised volatility
    ann_vol = returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Sharpe ratio
    excess_returns = returns - rf_daily
    sharpe = (excess_returns.mean() / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
              if returns.std() > 0 else 0.0)

    # Sortino ratio (downside deviation only)
    downside_returns = excess_returns[excess_returns < 0]
    downside_std = downside_returns.std() if len(downside_returns) > 0 else 0
    sortino = (excess_returns.mean() / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR)
               if downside_std > 0 else 0.0)

    # Maximum drawdown
    cum_returns = (1 + returns).cumprod()
    running_max = cum_returns.cummax()
    drawdown = (cum_returns - running_max) / running_max
    max_dd = drawdown.min()

    # Calmar ratio
    calmar = ann_return / abs(max_dd) if max_dd != 0 else 0.0

    # Skewness and kurtosis
    skewness = returns.skew()
    kurtosis = returns.kurtosis()

    metrics = {
        'portfolio': portfolio_name,
        'total_return': total_return,
        'annualised_return': ann_return,
        'annualised_volatility': ann_vol,
        'sharpe_ratio': sharpe,
        'sortino_ratio': sortino,
        'max_drawdown': max_dd,
        'calmar_ratio': calmar,
        'skewness': skewness,
        'kurtosis': kurtosis,
        'trading_days': n_days,
    }

    # Relative metrics vs benchmark
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        aligned = _align_series(returns, benchmark_returns)
        if len(aligned) > 0:
            active_returns = aligned['portfolio'] - aligned['benchmark']
            tracking_error = active_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
            info_ratio = (active_returns.mean() * TRADING_DAYS_PER_YEAR / tracking_error
                          if tracking_error > 0 else 0.0)

            # Benchmark metrics — guard against empty alignment
            bm_total = (1 + aligned['benchmark']).prod() - 1
            bm_ann = (1 + bm_total) ** (TRADING_DAYS_PER_YEAR / len(aligned)) - 1

            metrics.update({
                'benchmark_return': bm_ann,
                'active_return': ann_return - bm_ann,
                'tracking_error': tracking_error,
                'information_ratio': info_ratio,
            })
        else:
            metrics.update({
                'benchmark_return': 0.0,
                'active_return': 0.0,
                'tracking_error': 0.0,
                'information_ratio': 0.0,
            })

    return metrics


def compute_drawdown_series(returns: pd.Series) -> pd.Series:
    """Compute the drawdown time series (underwater chart).

    :param returns: Daily return series
    :type returns: pd.Series
    :returns: Drawdown series (negative values indicate drawdown depth)
    :rtype: pd.Series
    """
    cum_returns = (1 + returns).cumprod()
    running_max = cum_returns.cummax()
    drawdown = (cum_returns - running_max) / running_max
    return drawdown


def compute_cumulative_returns(returns: pd.Series) -> pd.Series:
    """Compute cumulative return series (growth of $1).

    :param returns: Daily return series
    :type returns: pd.Series
    :returns: Cumulative return series
    :rtype: pd.Series
    """
    return (1 + returns).cumprod()


def compute_rolling_sharpe(
    returns: pd.Series,
    window: int = 252,
    risk_free_rate: float = 0.04,
) -> pd.Series:
    """Compute rolling Sharpe ratio over a trailing window.

    :param returns: Daily return series
    :type returns: pd.Series
    :param window: Rolling window in trading days
    :type window: int
    :param risk_free_rate: Annual risk-free rate
    :type risk_free_rate: float
    :returns: Rolling Sharpe ratio series
    :rtype: pd.Series
    """
    rf_daily = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = returns - rf_daily
    rolling_mean = excess.rolling(window).mean()
    rolling_std = returns.rolling(window).std()
    rolling_sharpe = rolling_mean / rolling_std * np.sqrt(TRADING_DAYS_PER_YEAR)
    return rolling_sharpe


def compute_monthly_returns(returns: pd.Series) -> pd.DataFrame:
    """Compute monthly return heatmap data.

    :param returns: Daily return series
    :type returns: pd.Series
    :returns: DataFrame with years as rows, months as columns
    :rtype: pd.DataFrame
    """
    monthly = returns.resample('ME').apply(lambda x: (1 + x).prod() - 1)
    monthly_df = pd.DataFrame({
        'year': monthly.index.year,
        'month': monthly.index.month,
        'return': monthly.values,
    })
    pivot = monthly_df.pivot(index='year', columns='month', values='return')
    pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][:len(pivot.columns)]
    return pivot


def compute_top_drawdowns(returns: pd.Series, n: int = 3) -> pd.DataFrame:
    """Identify the top N worst drawdown events.

    :param returns: Daily return series
    :type returns: pd.Series
    :param n: Number of worst drawdowns to return
    :type n: int
    :returns: DataFrame with start, end, depth, recovery date
    :rtype: pd.DataFrame
    """
    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max

    events = []
    in_drawdown = False
    start = None

    for date, val in dd.items():
        if val < 0 and not in_drawdown:
            in_drawdown = True
            start = date
        elif val >= 0 and in_drawdown:
            in_drawdown = False
            depth = dd.loc[start:date].min()
            trough_date = dd.loc[start:date].idxmin()
            events.append({
                'start': start,
                'trough': trough_date,
                'recovery': date,
                'depth': depth,
                'duration_days': (date - start).days,
            })

    # Handle ongoing drawdown at end
    if in_drawdown:
        depth = dd.loc[start:].min()
        trough_date = dd.loc[start:].idxmin()
        events.append({
            'start': start,
            'trough': trough_date,
            'recovery': None,
            'depth': depth,
            'duration_days': (dd.index[-1] - start).days,
        })

    events_df = pd.DataFrame(events)
    if len(events_df) > 0:
        events_df = events_df.nsmallest(n, 'depth')
    return events_df


def _align_series(port: pd.Series, bench: pd.Series) -> pd.DataFrame:
    """Align portfolio and benchmark return series on common dates.

    :param port: Portfolio returns
    :type port: pd.Series
    :param bench: Benchmark returns
    :type bench: pd.Series
    :returns: DataFrame with 'portfolio' and 'benchmark' columns
    :rtype: pd.DataFrame
    """
    combined = pd.DataFrame({
        'portfolio': port,
        'benchmark': bench,
    }).dropna()
    return combined


def _empty_metrics(name: str) -> dict:
    """Return empty performance metrics dict."""
    return {
        'portfolio': name,
        'total_return': 0.0,
        'annualised_return': 0.0,
        'annualised_volatility': 0.0,
        'sharpe_ratio': 0.0,
        'sortino_ratio': 0.0,
        'max_drawdown': 0.0,
        'calmar_ratio': 0.0,
        'skewness': 0.0,
        'kurtosis': 0.0,
        'trading_days': 0,
    }
