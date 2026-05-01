"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Explicit no-lookahead tests
Project : CW2 - Value-Sentiment Investment Strategy

Implements the canonical no-lookahead test pattern from Part D §D8 of
the master guide.  These tests verify, at multiple levels of the stack,
that signals computed at a rebalance date never use data published
after the 90-day reporting lag cutoff:

    1. **SQL-string contract** — every PostgreSQL read query that takes
       an ``as_of_date`` parameter contains the literal substring
       ``date <= :as_of`` (or equivalent), so the WHERE clause cannot
       silently regress to an unfiltered scan.
    2. **MongoDB query contract** — the article-level loader's filter
       includes a server-side ``$lte`` on ``published_at``.
    3. **Backtester data-date contract** — the backtester always
       subtracts the 90-day reporting lag from each rebalance date
       before calling :meth:`DataLoader.load_value_metrics`.

These tests exercise contracts at the *string* and *attribute* level,
so they don't need a live database to run.
"""

import inspect
import re

import pandas as pd
import pytest

from modules.backtest.backtester import Backtester
from modules.data import data_loader as dl_module
from modules.data.data_loader import DataLoader


# ----------------------------------------------------------------------
# 1. SQL contract — every reader uses parameterised <= :as_of
# ----------------------------------------------------------------------

class TestSqlNoLookaheadContract:
    """The point-in-time clause must be present in every SQL reader."""

    def _source_of(self, method_name: str) -> str:
        return inspect.getsource(getattr(DataLoader, method_name))

    @pytest.mark.parametrize('method', [
        'load_value_metrics',
        'load_sentiment_scores',
        'load_composite_rankings',
    ])
    def test_method_uses_as_of_bind_param(self, method):
        src = self._source_of(method)
        assert 'date <= :as_of' in src, (
            f"{method} must filter rows by `date <= :as_of` (parameter "
            f"binding) — the no-lookahead clause is the load-bearing "
            f"defence against future-data leak."
        )

    def test_no_string_interpolation_of_as_of(self):
        """Catch regressions: f-string interpolation of as_of is forbidden."""
        for method in ('load_value_metrics', 'load_sentiment_scores',
                       'load_composite_rankings'):
            src = self._source_of(method)
            # Reject any pattern like {as_of} or {as_of_date} inside f-strings
            assert "{as_of" not in src, (
                f"{method} contains an f-string interpolation of as_of — "
                f"this is a SQL injection risk and a regression of the "
                f"v2.2 security pass."
            )

    def test_load_daily_prices_uses_bind_params(self):
        src = inspect.getsource(DataLoader.load_daily_prices)
        assert ':start' in src and ':end' in src, (
            "load_daily_prices must bind start/end as parameters."
        )


# ----------------------------------------------------------------------
# 2. MongoDB contract — the news loader filters server-side
# ----------------------------------------------------------------------

class TestMongoNoLookaheadContract:
    """The article reader must apply a server-side $lte filter."""

    def test_load_articles_filters_published_at(self):
        src = inspect.getsource(DataLoader._load_articles_from_mongo)
        # The query may reference published_at via the symbolic constant
        # MONGO_FIELD_PUBLISHED_AT (preferred) or as a literal string;
        # accept either since both are point-in-time correct.
        assert 'MONGO_FIELD_PUBLISHED_AT' in src or 'published_at' in src
        assert '$lte' in src
        assert 'point_in_time_query' in src or '$or' in src

    def test_published_at_constant_resolves_correctly(self):
        """The constant must resolve to the literal CW1 field name."""
        from modules.data.cw1_schema import MONGO_FIELD_PUBLISHED_AT
        assert MONGO_FIELD_PUBLISHED_AT == 'published_at'

    def test_no_unconditional_find(self):
        """Catch regressions: a bare collection.find({}) is forbidden."""
        src = inspect.getsource(DataLoader._load_articles_from_mongo)
        assert 'collection.find({})' not in src, (
            "Unconditional collection.find({}) was the v2.1 lookahead "
            "leak — this regression must not be reintroduced."
        )


# ----------------------------------------------------------------------
# 3. Backtester contract — reporting-lag offset is applied per rebalance
# ----------------------------------------------------------------------

class TestBacktesterReportingLag:

    def test_backtester_uses_lag_days(self):
        src = inspect.getsource(Backtester._compute_portfolio_at_date)
        # The data_date must be derived by subtracting the lag from the rebal_date
        assert 'self._lag_days' in src
        assert 'rebal_date - pd.Timedelta(days=self._lag_days)' in src

    def test_reporting_lag_default_is_90_days(self):
        # The PDF specifies a 90-day reporting lag in §A6.
        # We verify that the config-default is 90.
        from pathlib import Path
        import yaml
        config_path = Path(__file__).resolve().parents[1] / 'config' / 'backtest_config.yaml'
        if not config_path.exists():
            pytest.skip(f"config not found at {config_path}")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg['backtest']['reporting_lag_days'] == 90

    def test_execution_delay_is_t_plus_one(self):
        from pathlib import Path
        import yaml
        config_path = Path(__file__).resolve().parents[1] / 'config' / 'backtest_config.yaml'
        if not config_path.exists():
            pytest.skip(f"config not found at {config_path}")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        # T+1 close execution per §A6
        assert cfg['backtest']['execution_delay'] == 1


# ----------------------------------------------------------------------
# 4. End-to-end semantic test — synthetic value frame + manual filter
# ----------------------------------------------------------------------

class TestPointInTimeSemantics:
    """Verify the contract using synthetic data via DataFrame filtering.

    We can't hit a real Postgres in CI, but we can replicate the
    point-in-time semantics on a synthetic frame and assert the
    invariant CW2 relies on: the most recent record per company_id
    whose ``date <= as_of`` is the one returned.
    """

    def test_synthetic_filtering_invariant(self):
        # Build a frame with three companies × four dates each.
        rows = []
        for cid in ['AAPL', 'MSFT', 'GOOGL']:
            for d in ['2023-01-31', '2023-04-30', '2023-07-31', '2023-10-31']:
                rows.append({'company_id': cid, 'date': pd.Timestamp(d), 'value_score': float(d[:4])})
        df = pd.DataFrame(rows)

        as_of = '2023-06-30'
        filtered = (
            df[df['date'] <= pd.Timestamp(as_of)]
            .sort_values(['company_id', 'date'], ascending=[True, False])
            .drop_duplicates('company_id', keep='first')
        )
        # Every row in the filtered set must have date <= as_of
        assert (filtered['date'] <= pd.Timestamp(as_of)).all()
        # Each company gets exactly one row
        assert len(filtered) == 3
        # The most recent date per company is 2023-04-30 (the latest date <= 2023-06-30)
        assert (filtered['date'] == pd.Timestamp('2023-04-30')).all()
