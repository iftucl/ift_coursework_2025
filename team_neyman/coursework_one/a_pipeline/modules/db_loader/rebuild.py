from a_pipeline.modules.db_loader import postgres
from a_pipeline.modules.url_parser import dolthub_pipeline, yf_pipeline

# Rebuild the database
if __name__ == "__main__":
    postgres.del_table("liquidity_factors")
    postgres.del_table("trend_factors")
    postgres.del_table("momentum_factors")
    postgres.del_table("risk_factors")
    postgres.del_table("mean_reversion_factors")
    postgres.del_table("daily_ohlcv")
    yf_pipeline.update_ohlcv_batch()
    yf_pipeline.update_factors()
    dolthub_pipeline.setup_dolt_database()
