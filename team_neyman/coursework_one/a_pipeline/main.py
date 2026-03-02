import time
from datetime import datetime, timedelta
from modules.db_loader import postgres
from modules.url_parser import yf_pipeline, dolthub_pipeline

if __name__ == '__main__':
    #yf_pipeline.update_ohlcv_batch()
    #yf_pipeline.update_factors()
    dolthub_pipeline.setup_dolt_database()
