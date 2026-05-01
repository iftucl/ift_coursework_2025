"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Risk analysis — VaR, CVaR, Fama-French regression
Project : CW2 - Value-Sentiment Investment Strategy

Computes risk metrics:
  - Value at Risk (VaR) — historical 95% and 99%
  - Conditional VaR (CVaR / Expected Shortfall) — coherent risk measure
  - Fama-French 5-factor regression with Newey-West standard errors

Ref: Part A §A7.1, §A7.2
Academic: Newey & West (1987), Fama & French (2015)
"""

import logging
import os
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Compute historical Value at Risk.

    :param returns: Daily return series
    :type returns: pd.Series
    :param confidence: Confidence level (e.g. 0.95)
    :type confidence: float
    :returns: VaR (negative number representing loss threshold)
    :rtype: float
    """
    if len(returns) == 0:
        return 0.0
    alpha = 1 - confidence
    var = np.percentile(returns.dropna(), alpha * 100)
    return var


def compute_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Compute Conditional Value at Risk (Expected Shortfall).

    CVaR is the mean of returns below the VaR threshold.
    It is a coherent risk measure, unlike VaR.

    :param returns: Daily return series
    :type returns: pd.Series
    :param confidence: Confidence level (e.g. 0.95)
    :type confidence: float
    :returns: CVaR (negative number)
    :rtype: float
    """
    if len(returns) == 0:
        return 0.0
    var = compute_var(returns, confidence)
    tail = returns[returns <= var]
    return tail.mean() if len(tail) > 0 else var


def compute_fama_french_regression(
    portfolio_returns: pd.Series,
    ff_factors: pd.DataFrame = None,
    n_lags: int = 6,
) -> dict:
    """Run Fama-French 5-factor regression with Newey-West standard errors.

    Rp - Rf = alpha + b_MKT(Rm-Rf) + b_SMB(SMB) + b_HML(HML)
            + b_RMW(RMW) + b_CMA(CMA) + epsilon

    Uses statsmodels OLS with Newey-West HAC covariance estimation
    (6 lags per Newey & West 1987).

    :param portfolio_returns: Daily portfolio excess returns
    :type portfolio_returns: pd.Series
    :param ff_factors: Fama-French factor data with columns
                       [Mkt-RF, SMB, HML, RMW, CMA, RF]
    :type ff_factors: pd.DataFrame or None
    :param n_lags: Number of Newey-West lags
    :type n_lags: int
    :returns: Dict with alpha, betas, t-stats, R-squared
    :rtype: dict
    """
    try:
        import statsmodels.api as sm
    except ImportError:
        logger.warning("statsmodels not available — skipping FF regression")
        return _empty_ff_result()

    if ff_factors is None:
        logger.info("No Fama-French factor data provided — attempting download")
        ff_factors = _download_ff_factors(portfolio_returns.index)

    if ff_factors is None or len(ff_factors) == 0:
        logger.warning("Cannot load FF factors — returning empty regression")
        return _empty_ff_result()

    # Align dates
    common_dates = portfolio_returns.index.intersection(ff_factors.index)
    if len(common_dates) < 30:
        logger.warning("Too few common dates (%d) for FF regression", len(common_dates))
        return _empty_ff_result()

    y = portfolio_returns.loc[common_dates]

    # Subtract risk-free rate if present
    if 'RF' in ff_factors.columns:
        rf = ff_factors.loc[common_dates, 'RF']
        y = y - rf

    # Factor columns
    factor_cols = ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA']
    available_factors = [c for c in factor_cols if c in ff_factors.columns]
    X = ff_factors.loc[common_dates, available_factors]
    X = sm.add_constant(X)

    # Drop any NaN rows
    valid = y.notna() & X.notna().all(axis=1)
    y = y[valid]
    X = X[valid]

    if len(y) < 30:
        return _empty_ff_result()

    # OLS with Newey-West HAC standard errors
    model = sm.OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': n_lags})

    result = {
        'alpha': model.params.get('const', 0),
        'alpha_tstat': model.tvalues.get('const', 0),
        'alpha_pvalue': model.pvalues.get('const', 0),
        'r_squared': model.rsquared,
        'adj_r_squared': model.rsquared_adj,
        'n_observations': int(model.nobs),
        'betas': {},
        'tstats': {},
        'pvalues': {},
    }

    for factor in available_factors:
        result['betas'][factor] = model.params.get(factor, 0)
        result['tstats'][factor] = model.tvalues.get(factor, 0)
        result['pvalues'][factor] = model.pvalues.get(factor, 0)

    # Annualise alpha (daily to annual)
    result['alpha_annualised'] = result['alpha'] * 252

    logger.info(
        "FF regression: alpha=%.4f (t=%.2f), R²=%.3f, n=%d",
        result['alpha_annualised'], result['alpha_tstat'],
        result['r_squared'], result['n_observations'],
    )
    return result


_FF_URL = (
    'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/'
    'F-F_Research_Data_5_Factors_2x3_daily_CSV.zip'
)
_FF_CACHE = os.path.join('.cache', 'ff_factors', 'ff5_daily.csv')


def _download_ff_factors(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Download Fama-French 5-factor daily data from Ken French's library.

    Uses a direct HTTPS download via ``requests`` (pandas_datareader is
    broken on Python 3.12 because it imports the deleted ``distutils``
    module). The ZIP is cached on disk so repeated runs are instant.

    :param dates: Date range for factor data
    :type dates: pd.DatetimeIndex
    :returns: DataFrame with daily factor returns or None
    :rtype: pd.DataFrame or None
    """
    df = _load_ff_from_cache()
    if df is not None:
        return _slice_ff(df, dates)

    df = _fetch_ff_from_web()
    if df is not None:
        _save_ff_to_cache(df)
        return _slice_ff(df, dates)

    # Last resort — synthetic market factor from S&P 500 benchmark cache
    return _synthetic_ff_factor(dates)


def _load_ff_from_cache() -> Optional[pd.DataFrame]:
    if not os.path.exists(_FF_CACHE):
        return None
    try:
        df = pd.read_csv(_FF_CACHE, parse_dates=['date'], index_col='date')
        logger.info("Loaded Fama-French factors from cache: %d rows", len(df))
        return df
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("FF cache read failed: %s", exc)
        return None


def _save_ff_to_cache(df: pd.DataFrame):
    try:
        os.makedirs(os.path.dirname(_FF_CACHE), exist_ok=True)
        df.to_csv(_FF_CACHE)
        logger.info("FF factors cached to %s", _FF_CACHE)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("FF cache write failed: %s", exc)


def _fetch_ff_from_web() -> Optional[pd.DataFrame]:
    try:
        import io
        import zipfile
        import requests

        resp = requests.get(
            _FF_URL,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
            timeout=30,
        )
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            inner_name = zf.namelist()[0]
            with zf.open(inner_name) as f:
                raw = f.read().decode('utf-8', errors='replace')
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Could not download FF factors from %s: %s", _FF_URL, exc)
        return None

    # Parse the CSV: skip the header preamble, look for the first line
    # that starts with a YYYYMMDD date.
    lines = raw.splitlines()
    data_start = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped and stripped[0:8].isdigit() and len(stripped.split(',')) >= 6:
            data_start = idx
            break
    if data_start is None:
        logger.warning("FF CSV had no recognisable data rows")
        return None

    rows = []
    for line in lines[data_start:]:
        parts = [p.strip() for p in line.split(',')]
        if not parts or not parts[0] or not parts[0][0:8].isdigit():
            break
        try:
            date = pd.Timestamp(parts[0])
            mkt_rf, smb, hml, rmw, cma, rf = (float(p) for p in parts[1:7])
        except (ValueError, IndexError):
            continue
        rows.append({
            'date': date,
            'Mkt-RF': mkt_rf / 100.0,
            'SMB': smb / 100.0,
            'HML': hml / 100.0,
            'RMW': rmw / 100.0,
            'CMA': cma / 100.0,
            'RF': rf / 100.0,
        })

    if not rows:
        logger.warning("FF CSV parsed but produced no rows")
        return None

    df = pd.DataFrame(rows).set_index('date').sort_index()
    logger.info("Downloaded Fama-French 5-factor daily: %d rows", len(df))
    return df


def _slice_ff(df: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    if len(dates) == 0:
        return df
    return df.loc[(df.index >= dates.min()) & (df.index <= dates.max())]


def _synthetic_ff_factor(dates: pd.DatetimeIndex) -> Optional[pd.DataFrame]:
    """Last-resort market factor built from cached S&P 500 prices."""
    cache_files = []
    cache_dir = os.path.join('.cache', 'benchmarks')
    if os.path.isdir(cache_dir):
        for fname in os.listdir(cache_dir):
            if fname.startswith('GSPC_'):
                cache_files.append(os.path.join(cache_dir, fname))
    if not cache_files:
        logger.warning("No cached S&P 500 benchmark for synthetic FF factor")
        return None
    try:
        prices = pd.read_csv(cache_files[0], parse_dates=['date'], index_col='date').iloc[:, 0]
        mkt = prices.pct_change().dropna()
        df = pd.DataFrame({'Mkt-RF': mkt, 'RF': 0.0001}, index=mkt.index)
        logger.info("Using synthetic market factor from S&P 500 cache (%d rows)", len(df))
        return df
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Synthetic factor build failed: %s", exc)
        return None


def _empty_ff_result() -> dict:
    """Return empty Fama-French regression result."""
    return {
        'alpha': 0.0,
        'alpha_tstat': 0.0,
        'alpha_pvalue': 1.0,
        'alpha_annualised': 0.0,
        'r_squared': 0.0,
        'adj_r_squared': 0.0,
        'n_observations': 0,
        'betas': {},
        'tstats': {},
        'pvalues': {},
    }
