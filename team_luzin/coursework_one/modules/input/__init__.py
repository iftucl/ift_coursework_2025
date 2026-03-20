"""
Input module for market data loading and ingestion.

This module handles:
- Market data downloading (price, volume, volatility)
- Data validation and cleaning
- Sector filtering and universe preparation
"""

from .market_data_loader import MarketDataLoader

__all__ = ["MarketDataLoader"]
