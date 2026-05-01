"""Constants and configuration for data fetching modules."""

# MinIO cache bucket
BUCKET = "wittgenstein-cache"

# SimFin API endpoints
SIMFIN_STATEMENTS_URL = "https://backend.simfin.com/api/v3/companies/statements/compact"
SIMFIN_WEIGHTED_SHARES_URL = (
    "https://backend.simfin.com/api/v3/companies/weighted-shares-outstanding"
)

# SEC EDGAR (free, no API key, US-listed companies only)
SEC_EDGAR_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_EDGAR_USER_AGENT = "TeamWittgenstein/1.0 (bigdata-coursework@university.ac.uk)"

# Map 2-letter country codes to full country names for DB storage
COUNTRY_CODE_TO_NAME = {
    "US": "United States",
    "GB": "United Kingdom",
    "CA": "Canada",
    "FR": "France",
    "DE": "Germany",
    "CH": "Switzerland",
    "IT": "Italy",
    "SP": "Spain",
}

# Map country codes (from company_static) to OECD 3-letter codes
COUNTRY_TO_OECD = {
    "US": "USA",
    "GB": "GBR",
    "CA": "CAN",
    "FR": "FRA",
    "DE": "DEU",
    "CH": "CHE",
    "IT": "ITA",
    "SP": "ESP",
}

# Map country codes to yfinance Treasury/bond yield tickers (fallback)
COUNTRY_TO_YIELD_TICKER = {
    "US": "^IRX",  # 13-Week US Treasury Bill
    "GB": "^IRX",  # Use US T-bill as proxy
    "CA": "^IRX",  # Use US T-bill as proxy
    "FR": "^IRX",  # Use US T-bill as proxy
    "DE": "^IRX",  # Use US T-bill as proxy
    "CH": "^IRX",  # Use US T-bill as proxy
    "IT": "^IRX",  # Use US T-bill as proxy
    "SP": "^IRX",  # Use US T-bill as proxy
}


class SimFinServerError(Exception):
    """Raised when SimFin returns HTTP 500 so caller can trigger fallback."""
