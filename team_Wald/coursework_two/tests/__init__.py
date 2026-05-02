"""CW2 unit + integration test package.

Test types follow Part D §D8:

    * Known-answer  — manual calculation verified against expected value
    * Invariants    — weights sum to 1, drawdown ≤ 0, scores in [-3, 3]
    * No-lookahead  — signals only use ``date <= rebalance_date`` data
    * Edge cases    — empty universe, single stock, all NaN, zero variance
    * Regression    — saved reference output unchanged after refactor
    * Integration   — full pipeline mini-backtest

Coverage target: ≥85% across all CW2 modules. Run with::

    poetry run pytest tests/ -v --cov=modules --cov-report=term-missing
"""
