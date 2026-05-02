from a_pipeline.modules.db_loader import postgres
from a_pipeline.modules.url_parser import dolthub_pipeline, yf_pipeline

# Rebuild the database
if __name__ == "__main__":
    """
    postgres.del_table("liquidity_factors")
    postgres.del_table("trend_factors")
    postgres.del_table("momentum_factors")
    postgres.del_table("risk_factors")
    postgres.del_table("mean_reversion_factors")
    postgres.del_table("daily_ohlcv")
    postgres.del_table("daily_fx")

    print("Initializing Database...")
    postgres.create_ohlcv_table()
    postgres.create_fx_table()
    postgres.create_liquidity_table()
    postgres.create_trend_table()
    postgres.create_momentum_table()
    postgres.create_risk_table()
    postgres.create_mean_reversion_table()

    print("Fetching Ticker Currencies...")
    postgres.del_column("currency", "company_static")
    yf_pipeline.get_ticker_currencies()

    print("Initialization Complete.")


    yf_pipeline.update_ohlcv_batch()
    yf_pipeline.update_factors()
    dolthub_pipeline.rebuild_dolt_database()

    postgres.del_table("daily_fx")
    postgres.create_fx_table()
    yf_pipeline.fetch_fx_data()
    """
    postgres.create_company_currency()
    yf_pipeline.get_ticker_currencies()
