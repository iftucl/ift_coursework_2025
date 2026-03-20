"""Pipeline A — Data Ingestion.

Reads the investable universe from PostgreSQL, fetches daily prices from
Yahoo Finance and quarterly financials from Yahoo Finance (default) or
Alpha Vantage (--financial-source alphavantage), then publishes raw data
to Kafka topics and backs it up to MinIO.

Usage:
    python a_pipeline/main.py [--mode prices|financials|all]
                               [--run-date YYYY-MM-DD]
                               [--lookback-years N]
                               [--financial-source yfinance|alphavantage]
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from modules.db_loader.company_loader import load_companies
from modules.fetcher.alpha_vantage_fetcher import fetch_balance_sheet, fetch_income_statement
from modules.fetcher.yfinance_fetcher import fetch_prices
from modules.fetcher.yfinance_financial_fetcher import fetch_financials_yfinance
from modules.kafka_producer.producer import RawDataProducer
from modules.minio_writer.minio_writer import MinioRawWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "conf.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as fh:
        return yaml.safe_load(fh)["dev"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline A: Data Ingestion")
    parser.add_argument(
        "--run-date",
        default=datetime.today().strftime("%Y-%m-%d"),
        help="Run date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--lookback-years",
        type=int,
        default=5,
        help="Years of historical price data to fetch (default: 5)",
    )
    parser.add_argument(
        "--mode",
        choices=["prices", "financials", "all"],
        default="all",
        help="Which data to fetch (default: all)",
    )
    parser.add_argument(
        "--financial-source",
        choices=["yfinance", "alphavantage"],
        default="yfinance",
        help="Source for financial statement data (default: yfinance)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()

    run_date = datetime.strptime(args.run_date, "%Y-%m-%d")
    start_date = (run_date - timedelta(days=365 * args.lookback_years)).strftime("%Y-%m-%d")
    end_date = args.run_date

    logger.info(
        f"Run date: {args.run_date} | Mode: {args.mode} | "
        f"Lookback: {args.lookback_years}y | Financial source: {args.financial_source}"
    )

    companies = load_companies(cfg["postgres"])
    logger.info(f"Loaded {len(companies)} companies from company_static")

    producer = RawDataProducer(cfg["kafka"]["bootstrap_servers"])
    minio = MinioRawWriter(
        cfg["minio"]["endpoint"],
        cfg["minio"]["access_key"],
        cfg["minio"]["secret_key"],
        cfg["minio"]["bucket"],
        secure=cfg["minio"].get("secure", False),
    )

    price_topic = cfg["kafka"]["topics"]["prices"]
    fin_topic = cfg["kafka"]["topics"]["financials"]
    av_key = cfg["alpha_vantage"]["api_key"]

    for i, company in enumerate(companies, start=1):
        symbol = company.symbol.strip()
        logger.info(f"[{i}/{len(companies)}] Processing {symbol}")

        if args.mode in ("prices", "all"):
            price_data = fetch_prices(symbol, start_date, end_date)
            if price_data:
                producer.publish(price_topic, symbol, price_data)
                minio.write(symbol, "prices", price_data)

        if args.mode in ("financials", "all"):
            if args.financial_source == "yfinance":
                fin_data = fetch_financials_yfinance(symbol)
                if fin_data:
                    producer.publish(fin_topic, symbol, fin_data["balance_sheet"])
                    producer.publish(fin_topic, symbol, fin_data["income_statement"])
                    minio.write(symbol, "balance_sheet", fin_data["balance_sheet"])
                    minio.write(symbol, "income_statement", fin_data["income_statement"])
            else:
                bs_data = fetch_balance_sheet(symbol, av_key)
                if bs_data:
                    producer.publish(fin_topic, symbol, bs_data)
                    minio.write(symbol, "balance_sheet", bs_data)

                inc_data = fetch_income_statement(symbol, av_key)
                if inc_data:
                    producer.publish(fin_topic, symbol, inc_data)
                    minio.write(symbol, "income_statement", inc_data)

    producer.flush()
    logger.info("Pipeline A complete.")


if __name__ == "__main__":
    main()
