"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : QuantStats tearsheet integration
Project : CW2 - Value-Sentiment Investment Strategy

Generates comprehensive HTML tearsheet using the QuantStats library.
Output is saved as HTML and optionally converted to PDF for appendix.

Ref: Part C §C3 — Appendix D
"""

import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)


def generate_tearsheet(
    returns: pd.Series,
    benchmark_returns: pd.Series = None,
    title: str = 'Value-Sentiment Strategy',
    output_path: str = 'charts/tearsheet.html',
):
    """Generate a QuantStats HTML tearsheet.

    :param returns: Daily portfolio return series
    :type returns: pd.Series
    :param benchmark_returns: Benchmark returns for comparison
    :type benchmark_returns: pd.Series or None
    :param title: Report title
    :type title: str
    :param output_path: HTML output file path
    :type output_path: str
    """
    try:
        import quantstats as qs
    except ImportError:
        logger.warning("quantstats not installed — skipping tearsheet")
        return

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

    # QuantStats expects Series with datetime index
    returns = returns.copy()
    returns.index = pd.to_datetime(returns.index)

    if benchmark_returns is not None:
        benchmark_returns = benchmark_returns.copy()
        benchmark_returns.index = pd.to_datetime(benchmark_returns.index)

    try:
        qs.reports.html(
            returns,
            benchmark=benchmark_returns,
            title=title,
            output=output_path,
        )
        logger.info("Tearsheet generated: %s", output_path)
    except Exception as e:
        logger.error("Tearsheet generation failed: %s", e)
