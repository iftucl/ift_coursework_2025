"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Portfolio construction — screen, weight, constrain
Project : CW2 - Value-Sentiment Investment Strategy

Orchestrates the full portfolio construction pipeline:
  1. Screen: select stocks flagged invest_decision = True
  2. Weight: apply chosen weighting scheme (EW, score, inv-vol)
  3. Constrain: enforce position and sector limits
  4. Buffer: apply buy/sell buffer to reduce turnover

Implements 4 portfolio variants as required by the task:
  A: Value-Only (top 20% sector-rel value, D/E < 2)
  B: Sentiment-Only (top 20% quality-weighted sentiment)
  C: Combined (invest_decision = True from composite)
  D: Benchmark (S&P 500 / MSCI World)

Ref: Part A §A5
"""

import logging

import numpy as np
import pandas as pd

from modules.portfolio.constraints import apply_constraints
from modules.portfolio.weighting import (
    compute_equal_weight,
    compute_inverse_volatility_weight,
    compute_score_weight,
)

logger = logging.getLogger(__name__)


class PortfolioConstructor:
    """Screen, weight, and apply constraints to build portfolio.

    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, config: dict):
        self._scheme = config['portfolio']['weighting_scheme']
        self._max_position = config['portfolio']['max_position_weight']
        self._max_sector = config['portfolio']['max_sector_weight']
        self._min_holdings = config['portfolio']['min_holdings']
        self._target_holdings = config['portfolio']['target_holdings']
        self._buffer_buy = config['portfolio']['buffer_buy_pctl']
        self._buffer_sell = config['portfolio']['buffer_sell_pctl']
        self._selection_pctl = config['scoring']['selection_percentile']
        self._max_de = config['scoring']['max_debt_equity']
        self._min_confidence = config['scoring']['min_sentiment_confidence']

        # Long-short extension: when enabled, the portfolio shorts the
        # bottom quintile of the eligible universe to capture the spread
        # between winners and losers. The short sleeve is sized as a
        # fraction of the long sleeve.
        ls_cfg = config.get('portfolio', {}).get('long_short', {}) or {}
        self._long_short = bool(ls_cfg.get('enabled', False))
        self._short_pctl = float(ls_cfg.get('short_percentile', 0.20))
        self._short_ratio = float(ls_cfg.get('short_ratio', 0.5))

    def construct(
        self,
        signals: pd.DataFrame,
        sector_map: dict,
        prices: pd.DataFrame = None,
        current_weights: pd.Series = None,
        scheme_override: str = None,
    ) -> pd.Series:
        """Build constrained portfolio weights from scored signals.

        :param signals: DataFrame with company_id, composite_score,
                        invest_decision, value_score, etc.
        :type signals: pd.DataFrame
        :param sector_map: Dict mapping ticker → GICS sector
        :type sector_map: dict
        :param prices: Price DataFrame (needed for inverse-vol)
        :type prices: pd.DataFrame or None
        :param current_weights: Current portfolio weights (for buffer rule)
        :type current_weights: pd.Series or None
        :param scheme_override: Override weighting scheme for variant testing
        :type scheme_override: str or None
        :returns: Portfolio weights indexed by ticker, summing to 1.0
        :rtype: pd.Series
        """
        scheme = scheme_override or self._scheme

        # --- Step 1: Screen ---
        selected = self._screen(signals, current_weights)

        if len(selected) == 0:
            logger.warning("No stocks selected — returning empty portfolio")
            return pd.Series(dtype=float)

        tickers = selected['company_id'].tolist()

        # --- Step 2: Weight ---
        weights = self._weight(tickers, selected, scheme, prices)

        # --- Step 3: Constrain ---
        weights = apply_constraints(
            weights,
            sector_map,
            max_position=self._max_position,
            max_sector=self._max_sector,
            min_holdings=self._min_holdings,
        )

        # --- Step 4 (optional): Long-short extension ---
        if self._long_short:
            weights = self._add_short_sleeve(
                signals, weights, sector_map, scheme, prices,
            )

        logger.info(
            "Portfolio constructed: %d holdings, scheme=%s, sum=%.6f",
            (weights > 1e-8).sum() + (weights < -1e-8).sum(), scheme, weights.sum(),
        )
        return weights

    def _add_short_sleeve(
        self,
        signals: pd.DataFrame,
        long_weights: pd.Series,
        sector_map: dict,
        scheme: str,
        prices: pd.DataFrame = None,
    ) -> pd.Series:
        """Short the most overvalued stocks to capture the long-short spread.

        Selects from the FULL scored universe (including ineligible
        stocks), picking the lowest-value_score names — these are stocks
        the sector-relative z-score flags as genuinely expensive within
        their sector. This is the classic HML short leg: long cheap
        stocks, short expensive ones.
        """
        full = signals[signals['value_score'].notna()].copy()
        if len(full) == 0:
            return long_weights

        long_set = set(long_weights[long_weights > 1e-8].index)

        # Candidates for shorting: bottom quintile by VALUE score
        # (not composite — we want the truly overvalued, not just
        # those with low sentiment). Exclude anything we're long.
        candidates = full[~full['company_id'].isin(long_set)]
        if len(candidates) == 0:
            return long_weights

        n_short = max(5, int(len(candidates) * self._short_pctl))
        bottom = candidates.nsmallest(n_short, 'value_score')
        short_tickers = bottom['company_id'].tolist()

        if not short_tickers:
            return long_weights

        # Equal-weight the short side for simplicity (inv-vol on shorts
        # can perversely overweight the most volatile names)
        from modules.portfolio.weighting import compute_equal_weight
        short_raw = compute_equal_weight(short_tickers)

        long_notional = long_weights[long_weights > 0].sum()
        target_short_notional = long_notional * self._short_ratio
        short_scaled = short_raw / short_raw.sum() * target_short_notional

        combined = long_weights.copy()
        for ticker, w in short_scaled.items():
            combined[ticker] = combined.get(ticker, 0) - w

        logger.info(
            "Long-short: %d long (%.0f%%), %d short (%.0f%%), net = %.1f%%",
            (combined > 1e-8).sum(), long_notional * 100,
            (combined < -1e-8).sum(), target_short_notional * 100,
            combined.sum() * 100,
        )
        return combined

    def construct_value_only(
        self,
        signals: pd.DataFrame,
        sector_map: dict,
        prices: pd.DataFrame = None,
    ) -> pd.Series:
        """Build value-only portfolio (Portfolio A).

        Selects top ``selection_percentile`` by ``value_score`` with
        ``debt_equity <= max_debt_equity``. Weights by the configured
        scheme (``equal_weight`` | ``score_weight`` | ``inverse_volatility``)
        so that the variant benefits from the same risk-parity choice
        as the combined portfolio.

        :param signals: Scored signals DataFrame
        :type signals: pd.DataFrame
        :param sector_map: Sector mapping
        :type sector_map: dict
        :param prices: Price panel (required for inverse-volatility weights)
        :type prices: pd.DataFrame or None
        :returns: Constrained weights of value-selected stocks
        :rtype: pd.Series
        """
        eligible = signals[
            (signals['value_score'] > 0) &
            ((signals['debt_equity'].isna()) | (signals['debt_equity'] <= self._max_de))
        ].copy()

        if len(eligible) == 0:
            return pd.Series(dtype=float)

        n_select = max(self._min_holdings, int(len(eligible) * self._selection_pctl))
        top = eligible.nlargest(n_select, 'value_score')
        tickers = top['company_id'].tolist()
        # Use the configured weighting scheme (value_score is the ranking
        # column so we pass it as the "composite" for score-weighting).
        scored = top.rename(columns={'value_score': 'composite_score'})
        weights = self._weight(tickers, scored, self._scheme, prices)
        return apply_constraints(weights, sector_map, self._max_position, self._max_sector)

    def construct_sentiment_only(
        self,
        signals: pd.DataFrame,
        sector_map: dict,
        prices: pd.DataFrame = None,
    ) -> pd.Series:
        """Build sentiment-only portfolio (Portfolio B).

        Selects top ``selection_percentile`` by sentiment_score with
        confidence > ``min_sentiment_confidence``, weighted by the
        configured scheme (equal / score / inv-vol) so sentiment-only
        can leverage the same risk-parity optimisation as combined.

        :param signals: Scored signals DataFrame
        :type signals: pd.DataFrame
        :param sector_map: Sector mapping
        :type sector_map: dict
        :param prices: Price panel (required for inverse-volatility weights)
        :type prices: pd.DataFrame or None
        :returns: Constrained weights of sentiment-selected stocks
        :rtype: pd.Series
        """
        eligible = signals[
            signals['confidence'].fillna(0) > self._min_confidence
        ].copy()

        if len(eligible) == 0:
            return pd.Series(dtype=float)

        n_select = max(self._min_holdings, int(len(eligible) * self._selection_pctl))
        top = eligible.nlargest(n_select, 'sentiment_score')
        tickers = top['company_id'].tolist()
        # Use the configured weighting scheme (sentiment_score is the ranking
        # column so we pass it as the "composite" for score-weighting).
        scored = top.rename(columns={'sentiment_score': 'composite_score'})
        weights = self._weight(tickers, scored, self._scheme, prices)
        return apply_constraints(weights, sector_map, self._max_position, self._max_sector)

    def _screen(
        self,
        signals: pd.DataFrame,
        current_weights: pd.Series = None,
    ) -> pd.DataFrame:
        """Screen stocks for portfolio inclusion using a buffer rule.

        Implements the PDF A5 buffer specification literally:
            * New buys are admitted only if their composite-score percentile
              rank exceeds ``buffer_buy_pctl`` (default 0.60), i.e. they are
              among the top 40% of eligible names.
            * Existing holdings are retained if their composite-score
              percentile rank is at least ``buffer_sell_pctl`` (default 0.40),
              i.e. they are still in the top 60%.

        This double-threshold "no-trade band" reduces turnover from
        marginal ranking changes around the cutoff while still respecting
        the underlying invest-decision flag (top 20% by composite score).

        :param signals: Scored signals with composite_score, invest_decision, is_eligible
        :type signals: pd.DataFrame
        :param current_weights: Current holdings (for buffer leniency)
        :type current_weights: pd.Series or None
        :returns: Filtered DataFrame of selected stocks
        :rtype: pd.DataFrame
        """
        eligible = signals[signals['is_eligible'] & signals['composite_score'].notna()].copy()
        if len(eligible) == 0:
            logger.info("Screening: no eligible stocks")
            return eligible

        # Composite-score percentile rank within the eligible universe.
        # rank 0 → worst, 1 → best. Percentile rank > buy threshold means
        # the stock is in the top (1 - buy_pctl) fraction.
        eligible['composite_pctl'] = eligible['composite_score'].rank(pct=True, method='average')

        if current_weights is not None and len(current_weights) > 0:
            current_tickers = set(current_weights[current_weights > 1e-8].index)
            is_current = eligible['company_id'].isin(current_tickers)

            new_buy_mask = (~is_current) & (eligible['composite_pctl'] >= self._buffer_buy)
            hold_mask = is_current & (eligible['composite_pctl'] >= self._buffer_sell)
            invest_mask = eligible['invest_decision']  # always eligible from top quintile

            selected = eligible[invest_mask | new_buy_mask | hold_mask]
        else:
            # Cold start: just take the invest_decision quintile
            selected = eligible[eligible['invest_decision']]

        # Floor: ensure at least min_holdings names so we never end up tiny
        if len(selected) < self._min_holdings:
            top_up = eligible.nlargest(self._min_holdings, 'composite_score')
            selected = pd.concat([selected, top_up]).drop_duplicates(subset=['company_id'])

        logger.info(
            "Screening: %d stocks selected (buffer: buy>=%.2f pctl, sell>=%.2f pctl)",
            len(selected), self._buffer_buy, self._buffer_sell,
        )
        return selected

    def _weight(
        self,
        tickers: list,
        selected: pd.DataFrame,
        scheme: str,
        prices: pd.DataFrame = None,
    ) -> pd.Series:
        """Apply chosen weighting scheme to selected stocks.

        :param tickers: List of selected ticker symbols
        :type tickers: list
        :param selected: DataFrame with composite scores for score-weighting
        :type selected: pd.DataFrame
        :param scheme: Weighting scheme name
        :type scheme: str
        :param prices: Price data (needed for inverse-volatility)
        :type prices: pd.DataFrame or None
        :returns: Raw (unconstrained) weights
        :rtype: pd.Series
        """
        if scheme == 'equal_weight':
            return compute_equal_weight(tickers)

        elif scheme == 'score_weight':
            scores = selected.set_index('company_id')['composite_score']
            return compute_score_weight(tickers, scores)

        elif scheme == 'inverse_volatility':
            if prices is None:
                logger.warning("No price data for inv-vol — falling back to equal-weight")
                return compute_equal_weight(tickers)
            return compute_inverse_volatility_weight(tickers, prices)

        else:
            logger.warning("Unknown weighting scheme '%s' — using equal-weight", scheme)
            return compute_equal_weight(tickers)
