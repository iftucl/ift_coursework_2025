"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Structured logging via ift_global
Project : CW1 - Value + News Sentiment Strategy

Provides a singleton logger instance and run ID generation for
pipeline traceability across all modules.

The IFTLoggerAdapter wraps IFTLogger to support standard Python
printf-style formatting (e.g. logger.info("count: %d", 5)) which
IFTLogger does not natively support.
"""

import logging
import uuid


class IFTLoggerAdapter:
    """Adapter that adds printf-style formatting support to IFTLogger.

    :param ift_logger: Underlying IFTLogger instance
    :type ift_logger: IFTLogger
    """

    def __init__(self, ift_logger):
        self._logger = ift_logger

    def _format(self, msg, args):
        if args:
            return msg % args
        return msg

    def info(self, msg, *args, **kwargs):
        """Log an info-level message with optional printf-style args."""
        self._logger.info(self._format(msg, args))

    def warning(self, msg, *args, **kwargs):
        """Log a warning-level message with optional printf-style args."""
        self._logger.warning(self._format(msg, args))

    def error(self, msg, *args, **kwargs):
        """Log an error-level message with optional printf-style args."""
        self._logger.error(self._format(msg, args))

    def debug(self, msg, *args, **kwargs):
        """Log a debug-level message with optional printf-style args."""
        self._logger.debug(self._format(msg, args))


try:
    from ift_global.utils.logger import IFTLogger

    _raw_logger = IFTLogger(
        app_name="big_data",
        service_name="value_sentiment",
        log_level="info",
    )
    pipeline_logger = IFTLoggerAdapter(_raw_logger)
except ImportError:
    pipeline_logger = logging.getLogger("value_sentiment")
    if not pipeline_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        pipeline_logger.addHandler(handler)
        pipeline_logger.setLevel(logging.INFO)


def generate_run_id() -> str:
    """Generate a unique run identifier for audit trail linkage.

    :return: UUID-4 string
    :rtype: str
    """
    return str(uuid.uuid4())
