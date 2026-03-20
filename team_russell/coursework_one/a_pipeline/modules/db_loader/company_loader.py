"""Load the investable universe from PostgreSQL systematic_equity.company_static."""

from dataclasses import dataclass
from typing import List

from sqlalchemy import create_engine, text


@dataclass
class Company:
    """Represents a single row from company_static."""

    symbol: str
    security: str
    gics_sector: str
    gics_industry: str
    country: str
    region: str


def load_companies(pg_config: dict) -> List[Company]:
    """Read all companies from systematic_equity.company_static.

    Args:
        pg_config: dict with keys host, port, user, password, database.

    Returns:
        List of Company dataclass instances.
    """
    url = (
        f"postgresql+psycopg2://{pg_config['user']}:{pg_config['password']}"
        f"@{pg_config['host']}:{pg_config['port']}/{pg_config['database']}"
    )
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT symbol, security, gics_sector, gics_industry, country, region "
                "FROM systematic_equity.company_static"
            )
        )
        return [Company(*row) for row in rows]
