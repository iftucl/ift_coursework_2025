"""Data fetcher module for retrieving financial data from external APIs.

Fetches price data, financial statements, and risk-free rates,
caching all data as Parquet files in MinIO with CTL control files.

CTL Pattern:
    Every data file (e.g. prices/AAPL.parquet) has a companion control
    file (prices/AAPL.ctl) that tracks when it was fetched, how many
    rows it contains, and whether it has been loaded into PostgreSQL.
    This makes the pipeline idempotent and resumable.
"""

import os
from threading import Lock

from dotenv import load_dotenv

from .cache import CacheMixin
from .constants import BUCKET, SimFinServerError
from .edgar import EdgarMixin
from .fundamentals import FundamentalsMixin
from .prices import PriceMixin
from .rates import RatesMixin
from .simfin import SimFinMixin
from .utils import UtilsMixin
from .yfinance_fundamentals import YFinanceMixin

load_dotenv()

__all__ = ["DataFetcher", "SimFinServerError"]


class DataFetcher(
    CacheMixin,
    UtilsMixin,
    PriceMixin,
    EdgarMixin,
    SimFinMixin,
    YFinanceMixin,
    FundamentalsMixin,
    RatesMixin,
):
    """Fetches financial data from external APIs with MinIO caching.

    Uses the parquet + CTL (control file) pattern:
    - Data is stored as .parquet files in MinIO
    - Each data file has a companion .ctl JSON file tracking metadata
    - Before fetching, checks if cached data exists via CTL files

    Args:
        minio_conn: MinioConnection instance for caching.
    """

    def __init__(self, minio_conn):
        self.minio = minio_conn
        self.bucket = BUCKET
        self.simfin_api_key = os.getenv("SIMFIN_API_KEY")
        self._simfin_min_interval_seconds = float(
            os.getenv("SIMFIN_MIN_INTERVAL_SECONDS", "0.55")
        )
        self._simfin_last_request_ts = 0.0
        self._simfin_rate_limit_lock = Lock()
        self.minio._ensure_bucket(self.bucket)
        # SEC EDGAR ticker -> CIK mapping (lazy-loaded on first use)
        self._ticker_to_cik = {}
        self._edgar_min_interval_seconds = float(
            os.getenv("EDGAR_MIN_INTERVAL_SECONDS", "0.5")
        )
        self._edgar_last_request_ts = 0.0
        self._edgar_rate_limit_lock = Lock()
        # Cache TTL (None = never expire)
        self.cache_ttl_days = None
        # Populated after each fetch -- keyed by 'delisted' and 'fetch_error'
        self.price_failures = {}
        self.fundamentals_failures = {}
