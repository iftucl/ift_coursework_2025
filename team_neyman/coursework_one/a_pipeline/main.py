import time
from datetime import datetime, timedelta
from modules.db_loader import postgres
from modules.url_parser import yf_pipeline, dolthub_pipeline

if __name__ == '__main__':
    # Update latest data
    yf_pipeline.update_ohlcv_batch()
    postgres.add_new_column("ma200_20d_slope", "NUMERIC(10, 6)", "trend_factors")
    yf_pipeline.update_factors()
    dolthub_pipeline.setup_dolt_database()

    # Get the factors needed

    # Choose the companies
