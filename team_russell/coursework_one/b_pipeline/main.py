"""Pipeline B — Processing Consumer.

Consumes raw price and financial data from Kafka, stores raw documents in
MongoDB, computes derived fields, and writes processed records to PostgreSQL.

Runs as a long-lived service. Stop with Ctrl+C or SIGTERM.

Usage:
    poetry run python b_pipeline/main.py [--poll-timeout SECONDS]
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml
from modules.db_writer.mongo_writer import MongoRawWriter
from modules.db_writer.postgres_writer import PostgresWriter
from modules.kafka_consumer.consumer import RawDataConsumer
from modules.transformer.transformer import transform_financials, transform_prices

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
    parser = argparse.ArgumentParser(description="Pipeline B: Processing Consumer")
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=1.0,
        help="Kafka poll timeout in seconds (default: 1.0)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()

    kafka_cfg = cfg["kafka"]
    topics = list(kafka_cfg["topics"].values())

    consumer = RawDataConsumer(kafka_cfg["bootstrap_servers"], kafka_cfg["group_id"])
    mongo = MongoRawWriter(
        cfg["mongodb"]["host"], cfg["mongodb"]["port"], cfg["mongodb"]["database"]
    )
    pg = PostgresWriter(
        cfg["postgres"]["host"],
        cfg["postgres"]["port"],
        cfg["postgres"]["user"],
        cfg["postgres"]["password"],
        cfg["postgres"]["database"],
    )

    # Buffer to hold half-pairs until both balance_sheet and income_statement arrive
    pending_financials: dict = {}

    logger.info("Pipeline B started — waiting for messages.")

    for msg in consumer.consume(topics, poll_timeout=args.poll_timeout):
        msg_type = msg.get("type")
        symbol = msg.get("symbol", "").strip()

        if not symbol:
            logger.warning("Received message with no symbol — skipping.")
            continue

        # --- Price message ---
        if msg_type is None and "prices" in msg:
            mongo.upsert_prices(symbol, msg)
            records = transform_prices(msg)
            pg.upsert_prices(records)

        # --- Financial message (balance sheet or income statement) ---
        elif msg_type in ("balance_sheet", "income_statement"):
            if msg_type == "balance_sheet":
                mongo.upsert_balance_sheet(symbol, msg)
            else:
                mongo.upsert_income_statement(symbol, msg)

            pending_financials.setdefault(symbol, {})[msg_type] = msg

            # Process when both halves of the pair are available
            pair = pending_financials[symbol]
            if "balance_sheet" in pair and "income_statement" in pair:
                records = transform_financials(pair["balance_sheet"], pair["income_statement"])
                pg.upsert_financials(symbol, records)
                del pending_financials[symbol]

        else:
            logger.warning(f"Unknown message type '{msg_type}' for {symbol} — skipping.")

    logger.info("Pipeline B stopped.")


if __name__ == "__main__":
    main()
