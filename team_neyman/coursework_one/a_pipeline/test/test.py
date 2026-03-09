import sys
from pathlib import Path

root_path = Path(__file__).resolve().parent.parent
sys.path.append(str(root_path))

from modules.url_parser import dolthub_pipeline, yf_pipeline
from modules.db_loader import postgres
from modules.factors import calculate_factors

if __name__ == '__main__':
    #dolthub_pipeline.update_earnings_data(r"C:/Ryan/UCL BDF/Big Data in Quantitative Finance/ift_coursework_2025")
    postgres.del_table("liquidity_factors")
    postgres.del_table("trend_factors")
    postgres.del_table("momentum_factors")
    postgres.del_table("risk_factors")
    postgres.del_table("mean_reversion_factors")
    yf_pipeline.update_ohlcv_batch()
    yf_pipeline.update_factors()
    dolthub_pipeline.setup_dolt_database()