#!/usr/bin/env python3
"""
Step 3: Generate trading execution signals

Orchestrates:
- Load selected stocks from Step 2
- For each stock: fetch price data
- Generate signals:
  * MACD crossover: True buy/sell crossover detection (not just trend sign)
  * ATR: Risk filtering on buy execution only (not directional)
  * Liquidity & Risk: Quick checks from Step 2 data
- Combine signals to final_trade_signal (1=BUY, 0=HOLD, -1=SELL)
- Output: analytics/signals/signals_*.csv

Key strategy:
- MACD crossover is the primary execution trigger
- ATR is a buy filter only (prevents buying in high volatility)
- ATR is NOT a sell signal
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from modules.extraction.price_extractor import PriceDataExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def load_selections():
    """Load selected stocks from Step 2 output and merge with portfolio data for supporting info."""
    selections_file = (
        Path(__file__).parent.parent
        / "analytics"
        / "selections"
        / "selections_latest.csv"
    )
    portfolio_file = (
        Path(__file__).parent.parent
        / "analytics"
        / "portfolio"
        / "portfolio_latest.csv"
    )

    if not selections_file.exists():
        logger.error(f"Selections file not found: {selections_file}")
        return None

    try:
        df_selections = pd.read_csv(selections_file)
        logger.info(f"✓ Loaded {len(df_selections)} selected stocks from Step 2")

        # Merge with portfolio data to get volume_60d_avg and var_95
        if portfolio_file.exists():
            try:
                df_portfolio = pd.read_csv(portfolio_file)
                # Merge on symbol to get supporting data
                df_selections = df_selections.merge(
                    df_portfolio[["symbol", "volume_60d_avg", "var_95"]],
                    on="symbol",
                    how="left",
                )
                logger.debug(
                    f"✓ Merged with portfolio data for {len(df_selections)} stocks"
                )
            except Exception as e:
                logger.warning(f"Could not merge portfolio data: {e}")
                # Continue without portfolio data - supporting checks will default to safe values
        else:
            logger.warning(
                "Portfolio file not found - supporting checks will use defaults"
            )

        return df_selections
    except Exception as e:
        logger.error(f"Failed to load selections: {e}")
        return None


def _normalize_ohlcv(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Normalize OHLCV columns to Open/High/Low/Close/Volume for downstream usage."""
    if df is None or df.empty:
        return None

    required = ["open", "high", "low", "close", "volume"]
    selected = {}

    for col in required:
        # Try exact match first, then case-insensitive
        if col in df.columns:
            selected[col] = df[col]
        else:
            col_lower = [c for c in df.columns if c.lower() == col]
            if col_lower:
                selected[col] = df[col_lower[0]]
            else:
                selected[col] = None

    if any(v is None for v in selected.values()):
        return None

    result = pd.DataFrame(selected)
    result.columns = ["Open", "High", "Low", "Close", "Volume"]
    return result


def _read_local_raw_cache(symbol: str, raw_cache_dir: Path) -> Optional[pd.DataFrame]:
    """Read cached price data from local CSV."""
    cache_file = raw_cache_dir / f"{symbol}.csv"
    if cache_file.exists():
        try:
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            logger.debug("Loaded %s from local cache", symbol)
            return df
        except Exception as e:
            logger.debug("Failed to read local cache for %s: %s", symbol, e)
            return None
    return None


def _write_local_raw_cache(symbol: str, df: pd.DataFrame, raw_cache_dir: Path) -> None:
    """Write price data to local CSV cache."""
    raw_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = raw_cache_dir / f"{symbol}.csv"
    try:
        df.to_csv(cache_file)
        logger.debug("Cached %s to local storage", symbol)
    except Exception as e:
        logger.debug("Failed to cache %s: %s", symbol, e)


def _get_prices_with_fallback(
    symbol: str,
    extractor: PriceDataExtractor,
    raw_cache_dir: Path,
    years: int,
) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Get price data with fallback strategy:
    1. Try local cache
    2. Fetch from external source (Yahoo Finance)

    Returns:
        Tuple of (price_data, source) where source is 'local_cache' or 'external_fetch'
    """
    local_df = _read_local_raw_cache(symbol, raw_cache_dir)
    if local_df is not None:
        return local_df, "local_cache"

    fetched = extractor.fetch_price_data(symbol)
    normalized = _normalize_ohlcv(fetched) if fetched is not None else None
    if normalized is None or normalized.empty:
        return None, "external_fetch"

    _write_local_raw_cache(symbol, normalized, raw_cache_dir)
    return normalized, "external_fetch"


def _calculate_macd_values(close_series: pd.Series) -> Tuple[float, float, float]:
    """
    Calculate MACD line, signal line, and histogram (latest values).

    Args:
        close_series: Series of close prices

    Returns:
        Tuple of (macd_value, signal_value, histogram_value)
    """
    try:
        ema12 = close_series.ewm(span=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        return (
            float(macd_line.iloc[-1]),
            float(signal_line.iloc[-1]),
            float(histogram.iloc[-1]),
        )
    except Exception as e:
        logger.debug(f"Failed to calculate MACD values: {e}")
        return None, None, None


def _calculate_atr_values(df_prices: pd.DataFrame) -> Tuple[float, float, float]:
    """
    Calculate ATR_14, ATR_pct, and ATR_pct moving average (20-day).

    Args:
        df_prices: DataFrame with Open, High, Low, Close, Volume

    Returns:
        Tuple of (atr_14, atr_pct, atr_pct_ma_20)
    """
    try:
        if len(df_prices) < 14:
            return None, None, None

        high = df_prices["High"]
        low = df_prices["Low"]
        close = df_prices["Close"]

        # Calculate True Range
        tr = np.maximum(
            high - low,
            np.maximum(np.abs(high - close.shift()), np.abs(low - close.shift())),
        )

        # Calculate ATR_14
        atr_14 = tr.rolling(window=14).mean().iloc[-1]
        if pd.isna(atr_14):
            return None, None, None

        # Calculate ATR%
        current_close = close.iloc[-1]
        if current_close <= 0:
            atr_pct = None
        else:
            atr_pct = (atr_14 / current_close) * 100

        # Calculate 20-period rolling mean of ATR%
        atr_pct_series = (tr.rolling(window=14).mean() / close) * 100
        atr_pct_ma_20 = atr_pct_series.rolling(window=20).mean().iloc[-1]
        if pd.isna(atr_pct_ma_20):
            return float(atr_14) if atr_14 is not None else None, atr_pct, None

        return (
            float(atr_14) if atr_14 is not None else None,
            float(atr_pct) if atr_pct is not None else None,
            float(atr_pct_ma_20) if atr_pct_ma_20 is not None else None,
        )

    except Exception as e:
        logger.debug(f"Failed to calculate ATR values: {e}")
        return None, None, None


def _calculate_atr_risk_signal(atr_pct: float, atr_pct_ma_20: float) -> int:
    """
    Calculate ATR risk signal.

    Returns:
        1 if current atr_pct <= 1.5 * atr_pct_ma_20 (acceptable risk)
        -1 if current atr_pct > 1.5 * atr_pct_ma_20 (excessive volatility)
    """
    try:
        if atr_pct is None or atr_pct_ma_20 is None or atr_pct_ma_20 <= 0:
            return -1  # Conservative: fail closed on insufficient data

        threshold = 1.5 * atr_pct_ma_20
        if atr_pct <= threshold:
            return 1  # Low risk
        else:
            return -1  # High risk
    except Exception:
        return -1


def _detect_recent_bullish_crossover(close_series: pd.Series, window: int = 5) -> bool:
    """
    [DEPRECATED: Use _calculate_macd_execution_signal instead]
    Detect if a bullish MACD crossover occurred in the last N trading days.
    """
    pass


def _detect_recent_bearish_crossover(close_series: pd.Series, window: int = 5) -> bool:
    """
    [DEPRECATED: Use _calculate_macd_execution_signal instead]
    Detect if a bearish MACD crossover occurred in the last N trading days.
    """
    pass


def _get_macd_regime(close_series: pd.Series) -> int:
    """
    Get current MACD regime (bullish, bearish, or neutral).

    Returns:
        1 if MACD > signal (bullish regime)
        -1 if MACD < signal (bearish regime)
        0 if MACD == signal (neutral)
    """
    try:
        if len(close_series) < 27:
            return 0

        ema12 = close_series.ewm(span=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()

        macd_today = macd_line.iloc[-1]
        signal_today = signal_line.iloc[-1]

        if macd_today > signal_today:
            return 1
        elif macd_today < signal_today:
            return -1
        else:
            return 0
    except Exception:
        return 0


def _calculate_macd_execution_signal(
    close_series: pd.Series, recent_window: int = 5
) -> int:
    """
    Calculate valid MACD execution signal using recent crossover + regime logic.

    This is the daily execution trigger: does not require same-day crossover.
    Instead, checks if a bullish/bearish crossover happened in the last N days
    AND current MACD is still above/below signal (regime confirmation).

    Args:
        close_series: Series of close prices
        recent_window: Number of recent bars to check for crossover (default 5)

    Returns:
        1 if valid recent bullish crossover within window AND still bullish regime
        -1 if valid recent bearish crossover within window AND still bearish regime
        0 otherwise (no valid execution signal)
    """
    try:
        if len(close_series) < 27:
            return 0

        ema12 = close_series.ewm(span=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()

        macd_today = macd_line.iloc[-1]
        signal_today = signal_line.iloc[-1]

        # Current MACD regime
        if macd_today > signal_today:
            current_regime = 1
        elif macd_today < signal_today:
            current_regime = -1
        else:
            return 0

        # Check for recent bullish crossover (within last N bars, excluding today)
        lookback = min(recent_window, len(macd_line) - 1)
        for i in range(-lookback, 0):
            if i == -1:
                continue  # Skip today
            prev_i = i - 1
            # Bullish crossover: MACD crosses above signal
            if (
                macd_line.iloc[prev_i] <= signal_line.iloc[prev_i]
                and macd_line.iloc[i] > signal_line.iloc[i]
            ):
                # Valid if still in bullish regime
                if current_regime == 1:
                    return 1

        # Check for recent bearish crossover (within last N bars, excluding today)
        for i in range(-lookback, 0):
            if i == -1:
                continue  # Skip today
            prev_i = i - 1
            # Bearish crossover: MACD crosses below signal
            if (
                macd_line.iloc[prev_i] >= signal_line.iloc[prev_i]
                and macd_line.iloc[i] < signal_line.iloc[i]
            ):
                # Valid if still in bearish regime
                if current_regime == -1:
                    return -1

        return 0
    except Exception as e:
        logger.debug(f"Error calculating MACD execution signal: {e}")
        return 0


def trading_execution():
    """
    Step 3: Daily Execution Layer (uses Step 2 monthly portfolio).

    Frequency model:
    - Step 2 (monthly): Portfolio formation - defines allowed universe and stocks
    - Step 3 (daily): Execution layer - decides BUY/SELL/HOLD within Step 2 universe

    Execution logic:
    - Reads monthly portfolio from Step 2
    - For each selected stock: computes daily MACD execution signals
    - MACD uses recent crossover window (5 days) + ATR risk filtering (BUY-only)
    - Outputs daily execution signals: BUY (1), SELL (-1), HOLD (0)

    Indicator stack:
    - MACD 12/26/9: Primary execution trigger via recent crossover detection
    - ATR 14-day: Risk gate for BUY execution only (does NOT block SELL)
    - Liquidity + Risk gates: Supporting execution sanity checks from Step 2

    NOTE: Does NOT depend on MinIO. Storage is handled in Step 4.
    """
    logger.info("Step 3/4: Daily Execution Signals (Step 2 Monthly Portfolio)")
    logger.info("=" * 70)

    try:
        # Load selections from Step 2
        df_selections = load_selections()
        if df_selections is None or df_selections.empty:
            logger.error("No selections from Step 2")
            return False

        # Initialize price extractor
        extractor = PriceDataExtractor(years=5)
        logger.info("✓ Price extractor initialized")
        raw_cache_dir = Path(__file__).parent.parent / "analytics" / "raw" / "prices"

        # Generate signals for selected stocks
        results = []
        failed = []
        source_stats = {"local_cache": 0, "external_fetch": 0}

        for idx, row in df_selections.iterrows():
            symbol = row.get("symbol")
            if not symbol:
                continue

            # Clean symbol: strip whitespace, remove leading "$"
            symbol = str(symbol).strip().lstrip("$").upper()

            try:
                # Fetch price data using local-first policy
                df_prices, source = _get_prices_with_fallback(
                    symbol=symbol,
                    extractor=extractor,
                    raw_cache_dir=raw_cache_dir,
                    years=extractor.years,
                )
                source_stats[source] = source_stats.get(source, 0) + 1

                if df_prices is None or df_prices.empty:
                    logger.debug(f"No price data for {symbol}")
                    failed.append(symbol)
                    continue

                # Extract close prices
                close_series = df_prices["Close"]
                if close_series is None or close_series.isna().all():
                    logger.debug("Close price series empty for %s", symbol)
                    failed.append(symbol)
                    continue

                # Calculate MACD values (for diagnostic output)
                macd, macd_signal, macd_histogram = _calculate_macd_values(close_series)

                # Calculate ATR values and risk signal
                atr_14, atr_pct, atr_pct_ma = _calculate_atr_values(df_prices)
                atr_risk_signal = _calculate_atr_risk_signal(atr_pct, atr_pct_ma)

                # Supporting checks from Step 2 data
                # Liquidity signal: 1 if volume_60d_avg exists and > 0, else -1
                volume_60d_avg = row.get("volume_60d_avg")
                liquidity_signal = (
                    1 if pd.notna(volume_60d_avg) and volume_60d_avg > 0 else -1
                )

                # Risk signal: 1 if var_95 exists, else -1
                var_95 = row.get("var_95")
                risk_signal = 1 if pd.notna(var_95) else -1

                # Calculate MACD execution signal (valid recent crossover + regime confirmation)
                # Returns:
                # 1 = valid recent bullish crossover AND still bullish regime (within 5-day window)
                # -1 = valid recent bearish crossover AND still bearish regime (within 5-day window)
                # 0 = no valid execution signal
                macd_cross_signal = _calculate_macd_execution_signal(
                    close_series, recent_window=5
                )

                # Final trade signal logic
                # BUY: valid bullish MACD signal + ATR risk gate passes + liquidity + risk gates pass
                # SELL: valid bearish MACD signal (ATR does NOT block sell)
                # HOLD: otherwise
                final_trade_signal = 0  # Default HOLD

                if macd_cross_signal == 1:
                    # BUY: bullish execution signal + all filters pass
                    if (
                        atr_risk_signal == 1
                        and liquidity_signal == 1
                        and risk_signal == 1
                    ):
                        final_trade_signal = 1
                    # Otherwise HOLD while waiting for ATR to normalize

                elif macd_cross_signal == -1:
                    # SELL: bearish execution signal (independent of ATR)
                    final_trade_signal = -1

                # Otherwise HOLD (0)

                results.append(
                    {
                        "symbol": symbol,
                        "price_source": source,
                        "macd": macd,
                        "macd_signal": macd_signal,
                        "macd_histogram": macd_histogram,
                        "macd_cross_signal": macd_cross_signal,
                        "atr_14": atr_14,
                        "atr_pct": atr_pct,
                        "atr_pct_ma": atr_pct_ma,
                        "atr_risk_signal": atr_risk_signal,
                        "liquidity_signal": liquidity_signal,
                        "risk_signal": risk_signal,
                        "final_trade_signal": final_trade_signal,
                    }
                )

                if (idx + 1) % 50 == 0:
                    logger.info(f"  Processed {idx + 1}/{len(df_selections)} stocks")

            except Exception as e:
                logger.debug(f"Error processing {symbol}: {e}")
                failed.append(symbol)

        logger.info(
            f"✓ Generated signals for {len(results)} stocks ({len(failed)} failed)"
        )
        logger.info(
            "✓ Price data sources used: local=%s, external=%s",
            source_stats.get("local_cache", 0),
            source_stats.get("external_fetch", 0),
        )

        if not results:
            logger.error("No signals generated")
            return False

        # Convert to DataFrame
        df_signals = pd.DataFrame(results)

        # Count signals
        buy_count = len(df_signals[df_signals["final_trade_signal"] == 1])
        sell_count = len(df_signals[df_signals["final_trade_signal"] == -1])
        hold_count = len(df_signals[df_signals["final_trade_signal"] == 0])

        logger.info("✓ Signal distribution:")
        logger.info(f"  BUY:  {buy_count} ({100*buy_count/len(df_signals):.1f}%)")
        logger.info(f"  SELL: {sell_count} ({100*sell_count/len(df_signals):.1f}%)")
        logger.info(f"  HOLD: {hold_count} ({100*hold_count/len(df_signals):.1f}%)")

        # Save signals locally with versioning
        run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_base = Path(__file__).parent.parent / "analytics" / "signals"
        output_dir = output_base / run_timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save timestamped files
        signals_csv = output_dir / f"signals_{run_timestamp}.csv"
        signals_parquet = output_dir / f"signals_{run_timestamp}.parquet"
        df_signals.to_csv(signals_csv, index=False)
        df_signals.to_parquet(signals_parquet, index=False)
        logger.info(f"✓ Saved signals to {signals_csv}")
        logger.info(f"✓ Saved signals to {signals_parquet}")

        # Save latest files
        latest_csv = output_base / "signals_latest.csv"
        latest_parquet = output_base / "signals_latest.parquet"
        df_signals.to_csv(latest_csv, index=False)
        df_signals.to_parquet(latest_parquet, index=False)
        logger.info(f"✓ Updated latest signals file: {latest_csv}")

        logger.info("✓ Step 3 complete: Local signal files ready for Step 4 export")

        return True

    except Exception as e:
        logger.error(f"Step 3 failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = trading_execution()
    sys.exit(0 if success else 1)
