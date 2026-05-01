"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Backtester — quarterly backtest loop with weight drift
Project : CW2 - Value-Sentiment Investment Strategy

Orchestrates the full backtest simulation:
  1. At each rebalance date, compute signals using point-in-time data
  2. Construct portfolio weights using configured scheme
  3. Simulate returns with intra-period weight drift
  4. Deduct transaction costs on rebalance dates
  5. Track portfolio value, weights, and turnover over time

Point-in-time discipline (Part A §A6):
  - report_date <= rebalance_date
  - 90-day lag buffer for financial data
  - T+1 close execution (trade next day after rebalance signal)

Survivorship bias: includes delisted tickers active at each
rebalance date.  Elton et al. (1996): 0.9–2.1% annual bias.

Ref: Part A §A6, Part D §D2
"""

import logging

import numpy as np
import pandas as pd

from modules.backtest.rebalance_schedule import get_rebalance_dates
from modules.backtest.transaction_costs import TransactionCostModel
from modules.data.universe import UniverseConstructor
from modules.portfolio.portfolio_constructor import PortfolioConstructor
from modules.signals.sentiment_signal import SentimentSignal
from modules.signals.signal_combiner import SignalCombiner
from modules.signals.value_signal import ValueSignal

logger = logging.getLogger(__name__)


class Backtester:
    """Orchestrate the quarterly backtest loop.

    :param data_loader: DataLoader instance for database access
    :type data_loader: modules.data.data_loader.DataLoader
    :param universe: UniverseConstructor instance
    :type universe: UniverseConstructor
    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, data_loader, universe, config: dict):
        self._loader = data_loader
        self._universe = universe
        self._config = config

        # Initialise components
        self._value_signal = ValueSignal(config)
        self._sentiment_signal = SentimentSignal(config)
        self._signal_combiner = SignalCombiner(config)
        self._port_constructor = PortfolioConstructor(config)
        self._cost_model = TransactionCostModel(config)
        self._execution_delay = config['backtest']['execution_delay']
        self._lag_days = config['backtest']['reporting_lag_days']

        # Momentum filter (Asness et al. 2013 — "Value and Momentum Everywhere")
        mom_cfg = config.get('scoring', {}).get('momentum_filter', {}) or {}
        self._momentum_enabled = bool(mom_cfg.get('enabled', False))
        self._momentum_lookback_days = int(mom_cfg.get('lookback_days', 126))
        self._momentum_min_return = float(mom_cfg.get('min_return', -0.05))

        # Market-regime overlay (Antonacci 2014 dual-momentum, Moskowitz-
        # Ooi-Pedersen 2012 time-series momentum). When the S&P 500 trades
        # below its own trailing moving average we scale the portfolio down
        # and park the remainder in cash. This is a SIGNAL, not leverage,
        # so it can break Sharpe's leverage-invariance ceiling.
        reg_cfg = config.get('backtest', {}).get('regime_filter', {}) or {}
        self._regime_enabled = bool(reg_cfg.get('enabled', False))
        self._regime_fast_ma = int(reg_cfg.get('fast_ma_days', 50))
        self._regime_slow_ma = int(reg_cfg.get('slow_ma_days', 200))
        self._regime_bull_weight = float(reg_cfg.get('bull_weight', 1.0))
        self._regime_bear_weight = float(reg_cfg.get('bear_weight', 0.0))
        self._regime_signal = None  # lazy-built from benchmark prices

    def run(
        self,
        prices: pd.DataFrame,
        scheme_override: str = None,
        portfolio_type: str = 'combined',
    ) -> dict:
        """Execute the full backtest simulation.

        :param prices: Pivoted price DataFrame (dates × tickers)
        :type prices: pd.DataFrame
        :param scheme_override: Override weighting scheme for variant testing
        :type scheme_override: str or None
        :param portfolio_type: 'combined', 'value_only', or 'sentiment_only'
        :type portfolio_type: str
        :returns: Dict with 'returns', 'weights_history', 'turnover',
                  'rebalance_info', 'costs'
        :rtype: dict
        """
        start = self._config['backtest']['start_date']
        end = self._config['backtest']['end_date']
        months = self._config['backtest']['rebalance_months']

        # Compute daily returns from prices
        daily_returns = prices.pct_change().dropna(how='all')

        # Generate rebalance dates
        rebalance_dates = get_rebalance_dates(
            start, end, months, price_dates=prices.index,
        )

        if not rebalance_dates:
            logger.error("No rebalance dates generated — aborting backtest")
            return self._empty_results()

        # --- Main backtest loop ---
        all_returns = []
        weights_history = {}
        turnover_history = {}
        cost_history = {}
        rebalance_info = []
        current_weights = pd.Series(dtype=float)

        for i, rebal_date in enumerate(rebalance_dates):
            logger.info(
                "=== Rebalance %d/%d: %s (portfolio=%s) ===",
                i + 1, len(rebalance_dates),
                rebal_date.strftime('%Y-%m-%d'),
                portfolio_type,
            )

            # --- Compute signals at this rebalance date ---
            new_weights = self._compute_portfolio_at_date(
                rebal_date, prices, current_weights,
                scheme_override, portfolio_type,
            )

            if len(new_weights) == 0:
                logger.warning("Empty portfolio at %s — holding cash", rebal_date)
                new_weights = pd.Series(dtype=float)

            # --- Calculate transaction cost ---
            tc = self._cost_model.calculate(current_weights, new_weights)
            turnover = self._calc_turnover(current_weights, new_weights)

            # --- Determine holding period ---
            # T+1 execution: start holding from next trading day
            exec_date = self._get_execution_date(rebal_date, daily_returns.index)
            next_rebal = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else pd.Timestamp(end)

            # --- Simulate returns with weight drift (vectorised) ---
            period_returns, drifted_weights = self._compute_period_returns(
                new_weights, daily_returns, exec_date, next_rebal,
            )

            # Deduct transaction cost from first day's return
            if len(period_returns) > 0:
                period_returns.iloc[0] -= tc

            all_returns.append(period_returns)

            # --- Record state ---
            weights_history[rebal_date] = new_weights.copy()
            turnover_history[rebal_date] = turnover
            cost_history[rebal_date] = tc
            rebalance_info.append({
                'date': rebal_date,
                'n_holdings': int((new_weights > 1e-8).sum()),
                'turnover': float(turnover),
                'cost': float(tc),
                'max_weight': float(new_weights.max()) if len(new_weights) > 0 else 0.0,
                'period_return': float((1 + period_returns).prod() - 1) if len(period_returns) > 0 else 0.0,
            })

            # Use exact end-of-period drifted weights for next rebalance —
            # ensures buffer rule and turnover at i+1 reflect organic drift.
            current_weights = drifted_weights if len(drifted_weights) > 0 else new_weights

        # Concatenate all period returns
        if all_returns:
            portfolio_returns = pd.concat(all_returns)
            portfolio_returns = portfolio_returns[~portfolio_returns.index.duplicated(keep='first')]
            portfolio_returns = portfolio_returns.sort_index()
        else:
            portfolio_returns = pd.Series(dtype=float)

        logger.info(
            "Backtest complete: %d trading days, %d rebalances, total return=%.2f%%",
            len(portfolio_returns),
            len(rebalance_dates),
            ((1 + portfolio_returns).prod() - 1) * 100 if len(portfolio_returns) > 0 else 0,
        )

        return {
            'returns': portfolio_returns,
            'weights_history': weights_history,
            'turnover': turnover_history,
            'costs': cost_history,
            'rebalance_info': pd.DataFrame(rebalance_info),
        }

    def _compute_portfolio_at_date(
        self,
        rebal_date: pd.Timestamp,
        prices: pd.DataFrame,
        current_weights: pd.Series,
        scheme_override: str,
        portfolio_type: str,
    ) -> pd.Series:
        """Compute signals and construct portfolio at a rebalance date.

        :param rebal_date: Current rebalance date
        :type rebal_date: pd.Timestamp
        :param prices: Full price matrix
        :type prices: pd.DataFrame
        :param current_weights: Current portfolio weights
        :type current_weights: pd.Series
        :param scheme_override: Weighting scheme override
        :type scheme_override: str or None
        :param portfolio_type: Portfolio variant type
        :type portfolio_type: str
        :returns: New portfolio weights
        :rtype: pd.Series
        """
        # Point-in-time data: apply reporting lag
        data_date = rebal_date - pd.Timedelta(days=self._lag_days)
        data_date_str = data_date.strftime('%Y-%m-%d')

        # Load point-in-time data
        value_df = self._loader.load_value_metrics(data_date_str)

        # Try article-level sentiment data from MongoDB first, fall back to aggregated
        # load_news_article_metadata attempts MongoDB → falls back to PostgreSQL
        sentiment_df = self._loader.load_news_article_metadata(data_date_str)

        # Get universe at rebalance date
        universe = self._universe.get_universe(rebal_date)
        if len(universe) == 0:
            return pd.Series(dtype=float)

        sector_map = self._universe.get_sector_map()
        active_tickers = set(universe['symbol'].tolist())

        # Sector attribution robustness test: drop a sector from the universe
        exclude_sector = self._config.get('_exclude_sector')
        if exclude_sector:
            active_tickers = {
                t for t in active_tickers if sector_map.get(t) != exclude_sector
            }

        # Momentum filter (Asness et al. 2013). Reject stocks whose
        # trailing 126-day return is below min_return at the rebalance
        # date. This is the classical remedy for the "value trap" where
        # cheap-today stocks are cheap *because* they have been
        # declining, so a pure value factor loads on past decliners.
        if self._momentum_enabled and len(prices) > 0:
            history = prices.loc[prices.index <= rebal_date]
            if len(history) > self._momentum_lookback_days:
                lookback = history.tail(self._momentum_lookback_days + 1)
                start_px = lookback.iloc[0]
                end_px = lookback.iloc[-1]
                trailing = (end_px / start_px) - 1.0
                passing = set(trailing[trailing >= self._momentum_min_return].index)
                before = len(active_tickers)
                active_tickers = active_tickers & passing
                logger.info(
                    "Momentum filter: %d → %d tickers (trailing %d-day return ≥ %.1f%%)",
                    before, len(active_tickers),
                    self._momentum_lookback_days,
                    self._momentum_min_return * 100,
                )

        # Filter data to active universe
        value_df = value_df[value_df['company_id'].isin(active_tickers)]
        sentiment_df = sentiment_df[sentiment_df['company_id'].isin(active_tickers)]

        if len(value_df) == 0:
            logger.warning("No value data at %s", rebal_date)
            return pd.Series(dtype=float)

        # Compute signals
        value_signals = self._value_signal.compute(value_df, sector_map)
        sentiment_signals = self._sentiment_signal.compute(sentiment_df, rebal_date)

        # Combine signals
        combined = self._signal_combiner.compute(value_signals, sentiment_signals, value_df)

        # Construct portfolio based on type. All variants receive the
        # price panel so they can use inverse-volatility weighting.
        if portfolio_type == 'value_only':
            return self._port_constructor.construct_value_only(combined, sector_map, prices)
        elif portfolio_type == 'sentiment_only':
            return self._port_constructor.construct_sentiment_only(combined, sector_map, prices)
        else:
            # Combined portfolio
            return self._port_constructor.construct(
                combined, sector_map, prices,
                current_weights, scheme_override,
            )

    def _compute_period_returns(
        self,
        weights: pd.Series,
        daily_returns: pd.DataFrame,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> tuple:
        """Simulate portfolio returns with intra-period weight drift.

        Vectorised implementation: builds the held-stocks' price relatives
        across the entire period, computes daily portfolio returns from the
        drifting weights closed-form, and returns both the return series
        and the final drifted weights so the next rebalance sees the true
        post-drift portfolio composition (a critical correctness fix that
        ensures turnover at rebalance ``i+1`` reflects organic price drift,
        not the pre-period target weights).

        Construction:
            1. Slice ``daily_returns`` to the holding window and the held
               tickers, filling missing days with 0.
            2. ``cum_growth_t = prod(1 + r_{1..t})`` per stock (cumulative
               growth factor since rebalance).
            3. ``portfolio_value_t = sum_i w0_i × cum_growth_{i,t}`` (no
               re-normalisation: this matches a buy-and-hold portfolio that
               drifts naturally).
            4. ``period_return_t = portfolio_value_t / portfolio_value_{t-1} - 1``.
            5. End-of-period drifted weights are
               ``w_T_i = w0_i × cum_growth_{i,T} / portfolio_value_T``.

        :param weights: Portfolio weights at start of period
        :type weights: pd.Series
        :param daily_returns: Full daily returns matrix
        :type daily_returns: pd.DataFrame
        :param start_date: First date of holding period
        :type start_date: pd.Timestamp
        :param end_date: Last date of holding period
        :type end_date: pd.Timestamp
        :returns: Tuple ``(period_returns, drifted_weights)``
        :rtype: (pd.Series, pd.Series)
        """
        period_slice = daily_returns.loc[start_date:end_date]
        if len(period_slice) == 0:
            return pd.Series(dtype=float, name='portfolio_return'), weights

        # Cash / empty portfolio — flat returns, no drift
        if len(weights) == 0 or weights.sum() <= 0:
            zero_rets = pd.Series(0.0, index=period_slice.index, name='portfolio_return')
            return zero_rets, pd.Series(dtype=float)

        held = weights.index.intersection(period_slice.columns)
        if len(held) == 0:
            zero_rets = pd.Series(0.0, index=period_slice.index, name='portfolio_return')
            return zero_rets, weights

        # Vectorised drift via cumulative growth factors per stock
        sub_returns = period_slice[held].fillna(0.0)
        growth_factors = (1.0 + sub_returns).cumprod(axis=0)

        w0 = weights.reindex(held).fillna(0.0).values  # initial weights vector
        # Each row of values = w0_i * cum_growth_{i,t} → portfolio value time series
        weighted_growth = growth_factors.values * w0  # (T × N)
        portfolio_value = weighted_growth.sum(axis=1)

        # Daily portfolio returns from the value path
        prev = np.concatenate(([1.0], portfolio_value[:-1]))
        period_rets = portfolio_value / prev - 1.0

        period_returns = pd.Series(
            period_rets,
            index=sub_returns.index,
            name='portfolio_return',
        )

        # Apply the market-regime overlay (cash sleeve during bearish
        # S&P regime). This scales each daily return by the regime
        # exposure and adds the cash-sleeve portion earning the risk-
        # free rate, breaking Sharpe's leverage invariance because the
        # regime signal is a timing alpha source.
        if self._regime_enabled:
            period_returns = self._apply_regime_overlay(period_returns)

        # End-of-period drifted weights
        final_value = portfolio_value[-1] if len(portfolio_value) > 0 else 1.0
        if final_value > 0:
            drifted = pd.Series(
                weighted_growth[-1] / final_value,
                index=held,
                name='weight',
            )
        else:
            drifted = pd.Series(dtype=float)

        return period_returns, drifted

    def _build_regime_signal(self) -> pd.Series:
        """Compute a daily bullish/bearish exposure signal for the S&P 500.

        Returns a Series indexed by trading dates with values in
        ``[bear_weight, bull_weight]``. The signal is ``bull_weight`` on
        days when the fast moving average is above the slow moving
        average (bullish trend) and ``bear_weight`` otherwise. The
        boolean cross is computed from the S&P 500 adjusted close fetched
        by :class:`modules.data.benchmark.BenchmarkLoader`.
        """
        try:
            from modules.data.benchmark import BenchmarkLoader
            bl = BenchmarkLoader(self._config)
            # Pull a year of extra history so the slow MA is defined at
            # the start of the backtest window.
            start = (
                pd.Timestamp(self._config['backtest']['start_date'])
                - pd.Timedelta(days=self._regime_slow_ma * 2)
            ).strftime('%Y-%m-%d')
            end = self._config['backtest']['end_date']
            prices = bl.load_primary(start, end)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning('Regime filter failed to load S&P 500: %s', exc)
            return pd.Series(dtype=float)

        if prices is None or len(prices) == 0:
            return pd.Series(dtype=float)

        fast = prices.rolling(self._regime_fast_ma, min_periods=self._regime_fast_ma).mean()
        slow = prices.rolling(self._regime_slow_ma, min_periods=self._regime_slow_ma).mean()
        bullish = fast > slow
        exposure = bullish.map(
            lambda b: self._regime_bull_weight if b else self._regime_bear_weight
        )
        # Lag by 1 day so we never trade on same-day close
        exposure = exposure.shift(1).fillna(self._regime_bull_weight)
        logger.info(
            'Regime filter: %d days bullish, %d days bearish (%.1f%% cash on avg)',
            int((exposure == self._regime_bull_weight).sum()),
            int((exposure == self._regime_bear_weight).sum()),
            (1 - exposure.mean()) * 100,
        )
        return exposure

    def _apply_regime_overlay(self, period_returns: pd.Series) -> pd.Series:
        """Blend daily portfolio returns with a risk-free cash sleeve.

        On each day ``r_final = exposure · r_portfolio + (1 − exposure) · r_f/252``.
        """
        if self._regime_signal is None:
            self._regime_signal = self._build_regime_signal()
        if len(self._regime_signal) == 0:
            return period_returns
        rf_daily = self._config.get('risk_free', {}).get('annual_rate', 0.04) / 252
        exposure = self._regime_signal.reindex(
            period_returns.index, method='ffill',
        ).fillna(self._regime_bull_weight)
        blended = (
            exposure.values * period_returns.values
            + (1.0 - exposure.values) * rf_daily
        )
        return pd.Series(
            blended, index=period_returns.index, name=period_returns.name,
        )

    def _drift_weights(self, weights: pd.Series, period_returns: pd.Series) -> pd.Series:
        """Identity passthrough retained for backwards compatibility.

        Drift is now computed exactly inside ``_compute_period_returns``
        and returned alongside the return series, so this helper is no
        longer the source of truth.

        :param weights: Weights at start of period (unused)
        :type weights: pd.Series
        :param period_returns: Period return series (unused)
        :type period_returns: pd.Series
        :returns: ``weights`` unchanged
        :rtype: pd.Series
        """
        return weights

    def _get_execution_date(
        self,
        rebal_date: pd.Timestamp,
        trading_dates: pd.DatetimeIndex,
    ) -> pd.Timestamp:
        """Get T+1 execution date from rebalance signal date.

        :param rebal_date: Rebalance signal date
        :type rebal_date: pd.Timestamp
        :param trading_dates: Available trading dates
        :type trading_dates: pd.DatetimeIndex
        :returns: First trading date after rebalance
        :rtype: pd.Timestamp
        """
        future = trading_dates[trading_dates > rebal_date]
        if len(future) >= self._execution_delay:
            return future[self._execution_delay - 1]
        elif len(future) > 0:
            return future[0]
        return rebal_date

    @staticmethod
    def _calc_turnover(old_weights: pd.Series, new_weights: pd.Series) -> float:
        """Calculate one-way portfolio turnover.

        Turnover = Sum(|w_new - w_old|) / 2

        :param old_weights: Pre-rebalance weights
        :type old_weights: pd.Series
        :param new_weights: Post-rebalance weights
        :type new_weights: pd.Series
        :returns: One-way turnover (0 to 1)
        :rtype: float
        """
        all_tickers = old_weights.index.union(new_weights.index)
        old_aligned = old_weights.reindex(all_tickers, fill_value=0.0)
        new_aligned = new_weights.reindex(all_tickers, fill_value=0.0)
        return (new_aligned - old_aligned).abs().sum() / 2.0

    @staticmethod
    def _empty_results() -> dict:
        """Return empty results dict."""
        return {
            'returns': pd.Series(dtype=float),
            'weights_history': {},
            'turnover': {},
            'costs': {},
            'rebalance_info': pd.DataFrame(),
        }
