"""Write computed composite factor scores to PostgreSQL systematic_equity.factor_values."""

import logging
import math

import pandas as pd
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

_UPSERT_SQL = text(
    """
    INSERT INTO systematic_equity.factor_values
        (symbol, period_date, run_id, market_cap, book_value,
         bp, ey, cfy, dy, gpa, wca, ltde, roa,
         z_bp, z_ey, z_cfy, z_dy, z_gpa, z_wca, z_ltde, z_roa,
         value_score, quality_score, composite_score,
         composite_percentile, quintile)
    VALUES
        (:symbol, :period_date, :run_id, :market_cap, :book_value,
         :bp, :ey, :cfy, :dy, :gpa, :wca, :ltde, :roa,
         :z_bp, :z_ey, :z_cfy, :z_dy, :z_gpa, :z_wca, :z_ltde, :z_roa,
         :value_score, :quality_score, :composite_score,
         :composite_percentile, :quintile)
    ON CONFLICT (symbol, period_date) DO UPDATE SET
        run_id               = EXCLUDED.run_id,
        market_cap           = EXCLUDED.market_cap,
        book_value           = EXCLUDED.book_value,
        bp                   = EXCLUDED.bp,
        ey                   = EXCLUDED.ey,
        cfy                  = EXCLUDED.cfy,
        dy                   = EXCLUDED.dy,
        gpa                  = EXCLUDED.gpa,
        wca                  = EXCLUDED.wca,
        ltde                 = EXCLUDED.ltde,
        roa                  = EXCLUDED.roa,
        z_bp                 = EXCLUDED.z_bp,
        z_ey                 = EXCLUDED.z_ey,
        z_cfy                = EXCLUDED.z_cfy,
        z_dy                 = EXCLUDED.z_dy,
        z_gpa                = EXCLUDED.z_gpa,
        z_wca                = EXCLUDED.z_wca,
        z_ltde               = EXCLUDED.z_ltde,
        z_roa                = EXCLUDED.z_roa,
        value_score          = EXCLUDED.value_score,
        quality_score        = EXCLUDED.quality_score,
        composite_score      = EXCLUDED.composite_score,
        composite_percentile = EXCLUDED.composite_percentile,
        quintile             = EXCLUDED.quintile
"""
)

_OUTPUT_COLS = [
    "symbol",
    "period_date",
    "run_id",
    "market_cap",
    "book_value",
    "bp",
    "ey",
    "cfy",
    "dy",
    "gpa",
    "wca",
    "ltde",
    "roa",
    "z_bp",
    "z_ey",
    "z_cfy",
    "z_dy",
    "z_gpa",
    "z_wca",
    "z_ltde",
    "z_roa",
    "value_score",
    "quality_score",
    "composite_score",
    "composite_percentile",
    "quintile",
]


class FactorWriter:
    """Upserts composite factor scores into systematic_equity.factor_values.

    Args:
        pg_config: PostgreSQL connection config dict.
        quarter_end_date: The year-end date string used as period_date.
        run_id: Pipeline run identifier (e.g. a timestamp string).
    """

    def __init__(self, pg_config: dict, quarter_end_date: str, run_id: str = "") -> None:
        url = (
            f"postgresql+psycopg2://{pg_config['user']}:{pg_config['password']}"
            f"@{pg_config['host']}:{pg_config['port']}/{pg_config['database']}"
        )
        self._engine = create_engine(url)
        self._quarter_end_date = quarter_end_date
        self._run_id = run_id

    def write(self, df: pd.DataFrame) -> None:
        """Upsert all rows from df into factor_values.

        Args:
            df: Output DataFrame from value_factor.run_factor_pipeline().
        """
        df = df.copy()
        df["period_date"] = self._quarter_end_date
        df["run_id"] = self._run_id

        def _clean(val):
            if val is None:
                return None
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                return None
            return val

        records = [
            {k: _clean(v) for k, v in row.items()} for row in df[_OUTPUT_COLS].to_dict("records")
        ]

        with self._engine.begin() as conn:
            conn.execute(_UPSERT_SQL, records)

        logger.info(
            f"Upserted {len(records)} factor records for period {self._quarter_end_date} "
            f"(run_id={self._run_id})"
        )
