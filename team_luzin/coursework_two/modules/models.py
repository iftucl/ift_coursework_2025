from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CW1Inputs:
    universe_snapshot: pd.DataFrame
    factors: pd.DataFrame
    selections: pd.DataFrame
    signals: pd.DataFrame
    price_history: pd.DataFrame
    historical_factors: pd.DataFrame = field(default_factory=pd.DataFrame)
    historical_selections: pd.DataFrame = field(default_factory=pd.DataFrame)
    historical_signals: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass
class BacktestResults:
    holdings: pd.DataFrame
    returns: pd.DataFrame
    equity_curve: pd.DataFrame
    holdings_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    backtest_mode: str = "fixed_latest"
