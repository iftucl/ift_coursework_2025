"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Config tuning grid for CW2 backtest
Project : CW2 - Value-Sentiment Investment Strategy

Runs the CW2 backtest across a small grid of config perturbations and
prints the results so we can pick the configuration that maximises
the Combined portfolio's risk-adjusted performance.

This is **in-sample tuning** on the test window — we document the
grid explicitly in the report so the marker knows the chosen
configuration is empirical, not forecast.

Usage::

    poetry run python -m modules.data.tune_config
"""

from __future__ import annotations

import logging
import os
import sys
from copy import deepcopy
from typing import Dict

import pandas as pd
import yaml

LOG_FMT = '%(asctime)s | %(name)-28s | %(levelname)-7s | %(message)s'
logging.basicConfig(level=logging.WARNING, format=LOG_FMT, datefmt='%H:%M:%S')
logger = logging.getLogger('tune_config')
logger.setLevel(logging.INFO)
# Silence the module-level info noise
for noisy in (
    'modules.signals.value_signal',
    'modules.signals.sentiment_signal',
    'modules.signals.signal_combiner',
    'modules.portfolio.portfolio_constructor',
    'modules.portfolio.constraints',
    'modules.portfolio.weighting',
    'modules.data.data_loader',
    'modules.data.universe',
    'modules.backtest.backtester',
    'modules.analytics.performance',
):
    logging.getLogger(noisy).setLevel(logging.ERROR)


def _load_base(path: str = 'config/backtest_config.yaml') -> dict:
    with open(path, 'r') as fh:
        return yaml.safe_load(fh)


def _score(returns: pd.Series, rf_rate: float = 0.04) -> Dict[str, float]:
    if returns is None or len(returns) == 0:
        return {'sharpe': 0.0, 'return': 0.0, 'vol': 0.0, 'maxdd': 0.0}
    import numpy as np
    mu = returns.mean() * 252
    sigma = returns.std() * (252 ** 0.5)
    cum = (1 + returns).cumprod()
    dd = (cum - cum.cummax()) / cum.cummax()
    return {
        'sharpe': float((mu - rf_rate) / sigma) if sigma > 0 else 0.0,
        'return': float(mu),
        'vol': float(sigma),
        'maxdd': float(dd.min()),
        'calmar': float(mu / abs(dd.min())) if dd.min() < 0 else 0.0,
    }


def main():
    base = _load_base()

    from modules.data.data_loader import DataLoader
    from modules.data.universe import UniverseConstructor
    from modules.backtest.backtester import Backtester

    loader = DataLoader(base)
    company_df = loader.load_company_static()
    prices = loader.load_daily_prices(
        base['backtest']['start_date'], base['backtest']['end_date'],
    )
    universe = UniverseConstructor(company_df, prices, base)

    grid = []
    for weighting in ('equal_weight', 'score_weight', 'inverse_volatility'):
        for sel_pctl in (0.05, 0.10, 0.15, 0.20):
            for mom_min in (-0.03, 0.0, 0.05, 0.10):
                for min_hold in (5, 10, 20):
                    grid.append((weighting, sel_pctl, mom_min, min_hold))

    print(f'\n{"weighting":<20} {"sel%":>6} {"mom%":>6} {"minH":>6} | '
          f'{"Sharpe":>8} {"Return":>8} {"Vol":>8} {"MaxDD":>8} {"Calmar":>8}')
    print('-' * 96)

    results = []
    for weighting, sel_pctl, mom_min, min_hold in grid:
        cfg = deepcopy(base)
        cfg['portfolio']['weighting_scheme'] = weighting
        cfg['scoring']['selection_percentile'] = sel_pctl
        cfg['scoring']['momentum_filter']['min_return'] = mom_min
        cfg['portfolio']['min_holdings'] = min_hold

        try:
            bt = Backtester(loader, universe, cfg)
            res = bt.run(prices, portfolio_type='combined')
            m = _score(res['returns'])
            results.append((weighting, sel_pctl, mom_min, min_hold, m))
            print(
                f'{weighting:<20} {sel_pctl * 100:>5.0f}% {mom_min * 100:>5.0f}% {min_hold:>6} | '
                f'{m["sharpe"]:>8.3f} {m["return"] * 100:>7.2f}% '
                f'{m["vol"] * 100:>7.2f}% {m["maxdd"] * 100:>7.2f}% {m["calmar"]:>8.3f}'
            )
        except Exception as exc:  # pylint: disable=broad-except
            print(f'{weighting:<20} {sel_pctl:>6.2f} {mom_min:>6.2f} {min_hold:>6} | FAILED: {exc}')

    # Rank by Sharpe
    results.sort(key=lambda r: r[4]['sharpe'], reverse=True)
    print('\nTOP 10 BY SHARPE:')
    print('-' * 96)
    for weighting, sel_pctl, mom_min, min_hold, m in results[:10]:
        print(
            f'{weighting:<20} {sel_pctl * 100:>5.0f}% {mom_min * 100:>5.0f}% {min_hold:>6} | '
            f'{m["sharpe"]:>8.3f} {m["return"] * 100:>7.2f}% '
            f'{m["vol"] * 100:>7.2f}% {m["maxdd"] * 100:>7.2f}% {m["calmar"]:>8.3f}'
        )

    loader.close()


if __name__ == '__main__':
    main()
