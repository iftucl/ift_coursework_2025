"""Pipeline C — Value + Quality Composite Factor Computation.

Reads processed price and financial data from PostgreSQL, computes
sector-neutral composite factor scores (B/P, E/Y, CF/Y, DY, GPA, WCA,
LTDE, ROA) using Amundi Section 2.3 z-score methodology, and writes
results with quintile rankings back to systematic_equity.factor_values.

Run yearly after Pipeline B has populated price_history and financials.

Usage:
    poetry run python c_pipeline/main.py [--run-date YYYY-MM-DD]
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from modules.db_loader.data_loader import load_factor_inputs
from modules.db_writer.factor_writer import FactorWriter
from modules.factor.factor_model import run_factor_pipeline

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
    parser = argparse.ArgumentParser(description="Pipeline C: Value + Quality Factor Computation")
    parser.add_argument(
        "--run-date",
        default=datetime.today().strftime("%Y-%m-%d"),
        help="Quarter-end date YYYY-MM-DD (default: today)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()

    run_id = datetime.now(timezone.utc).strftime("pipeline_c_%Y%m%d_%H%M%S")
    logger.info(f"Computing composite factor for year ending {args.run_date} (run_id={run_id})")

    df = load_factor_inputs(cfg["postgres"], args.run_date)

    if df.empty:
        logger.warning(
            f"No data found for {args.run_date}. " "Ensure Pipeline A and B have run for this date."
        )
        return

    df = run_factor_pipeline(df)

    writer = FactorWriter(cfg["postgres"], args.run_date, run_id=run_id)
    writer.write(df)

    logger.info("Pipeline C complete.")


if __name__ == "__main__":
    main()
