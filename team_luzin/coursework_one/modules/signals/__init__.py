"""
Signals module for trading execution signals.

This module handles:
- MACD trend signal generation
- ATR risk signal calculation
- Liquidity signal filtering
- Final execution signal generation (BUY/SELL/HOLD)
"""

from .execution_signals import ExecutionSignals

__all__ = ["ExecutionSignals"]
