"""Data access layer for CW2.

Bridges CW1's persistence layer (PostgreSQL ``systematic_equity`` schema
and MongoDB ``raw_news_articles`` collection) into the CW2 backtester:

    * :mod:`modules.data.cw1_schema` — single source of truth for CW1's
      table names, column names, MongoDB collection names, MongoDB field
      names, and the identifier-safety helpers used by the loader.
    * :class:`modules.data.data_loader.DataLoader` — point-in-time SQL
      and Mongo readers with parameterised queries, env-var credential
      resolution, and a 90-day reporting lag enforced at query time.
    * :class:`modules.data.universe.UniverseConstructor` — survivorship-
      bias-aware investable universe at every rebalance date.
    * :class:`modules.data.benchmark.BenchmarkLoader` — Yahoo Finance
      benchmark series (S&P 500, MSCI World Value) plus an equal-weight
      universe benchmark for selection-skill isolation.
"""

from modules.data import cw1_schema
from modules.data.benchmark import BenchmarkLoader
from modules.data.data_loader import DataLoader
from modules.data.universe import UniverseConstructor

__all__ = ['DataLoader', 'UniverseConstructor', 'BenchmarkLoader', 'cw1_schema']
