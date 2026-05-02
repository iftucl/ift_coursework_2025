"""Step 14 — Extend backtest to 2015 using WRDS fundamental data.

Background
----------
Step 13 backfilled value + quality scores for Dec 31, 2015–2024 via WRDS/Compustat.
This step uses those scores to extend the backtest back to 2015:

  Phase 1 — Score Dec 31 dates (2015–2020)
    Value + quality already in DB.  Download yfinance prices to add:
      - Low volatility  (252-day trailing annualised vol, inverted; stored but not in composite)
      - Momentum        (12-1 month return)
    Then recompute the 3-factor composite (Value+Quality+Momentum) and assign quintiles.

  Phase 2 — Insert quarterly rebalance dates (Mar/Jun/Sep 2016–2021)
    Copy the prior Dec 31 value/quality scores to each quarterly date,
    then download fresh prices to compute low vol + momentum for that date.

  Phase 3 — Compute holding-period returns (24 new quarters)
    Download entry/exit prices for each quarterly period and compute
    equal-weighted gross and net-of-cost returns by quintile.

  Phase 4 — Combine with existing 16 quarters (step 11 output) and
    regenerate performance summary + charts (10-year backtest).

New periods added:
  2015-12-31 → 2016-03-31  …  2021-09-30 → 2021-12-31  (24 quarters)

Combined with step 11's 16 quarters (2022–2025) → 40 quarters total.

Usage
-----
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step14_extend_to_2015.py
"""

import math
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
import yfinance as yf
from scipy.stats import norm, spearmanr
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")
sns.set_theme(style="whitegrid", palette="muted", font_scale=1.05)

# ── Config ────────────────────────────────────────────────────────────────────
PG = dict(host="localhost", port=5439, user="postgres", password="postgres", database="fift")

BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
CHARTS = RESULTS / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

# Final 3-factor composite weights: Value + Quality + Momentum
# Low Volatility is computed and stored in DB but excluded from composite.
W_VALUE = 0.35
W_QUALITY = 0.35
W_MOMENTUM = 0.30

BATCH_SIZE = 50
BATCH_SLEEP = 2
TC_RT = 0.004  # 0.4% round-trip transaction cost
from _rf_rates import rf_quarterly_series  # noqa: E402

WINSOR_LO = 0.05
WINSOR_HI = 0.95
SMALL_SECTOR_MIN = 5
MIN_DAYS = 20  # minimum trading days for price series

# Dec 31 dates with WRDS fundamentals (already in DB from step04)
DEC_DATES = [
    "2015-12-31",
    "2016-12-31",
    "2017-12-31",
    "2018-12-31",
    "2019-12-31",
    "2020-12-31",
    "2021-12-31",
    "2022-12-31",
    "2023-12-31",
    "2024-12-31",
]

# Quarterly rebalance dates to CREATE (copy Dec fundamentals + fresh vol/mom)
# Key: which Dec date supplies the value/quality scores (EU stocks only;
# US stocks already have quarterly fundamentals from step04)
QUARTERLY_MAP = {
    "2015-12-31": ["2016-03-31", "2016-06-30", "2016-09-30"],
    "2016-12-31": ["2017-03-31", "2017-06-30", "2017-09-30"],
    "2017-12-31": ["2018-03-31", "2018-06-30", "2018-09-30"],
    "2018-12-31": ["2019-03-31", "2019-06-30", "2019-09-30"],
    "2019-12-31": ["2020-03-31", "2020-06-30", "2020-09-30"],
    "2020-12-31": ["2021-03-31", "2021-06-30", "2021-09-30"],
    "2021-12-31": ["2022-03-31", "2022-06-30", "2022-09-30"],
    "2022-12-31": ["2023-03-31", "2023-06-30", "2023-09-30"],
    "2023-12-31": ["2024-03-31", "2024-06-30", "2024-09-30"],
    "2024-12-31": ["2025-03-31", "2025-06-30", "2025-09-30"],
}

# All holding periods (40 quarters: Dec 2015 → Sep 2025)
NEW_PERIODS = [
    ("2015-12-31", "2016-03-31"),
    ("2016-03-31", "2016-06-30"),
    ("2016-06-30", "2016-09-30"),
    ("2016-09-30", "2016-12-31"),
    ("2016-12-31", "2017-03-31"),
    ("2017-03-31", "2017-06-30"),
    ("2017-06-30", "2017-09-30"),
    ("2017-09-30", "2017-12-31"),
    ("2017-12-31", "2018-03-31"),
    ("2018-03-31", "2018-06-30"),
    ("2018-06-30", "2018-09-30"),
    ("2018-09-30", "2018-12-31"),
    ("2018-12-31", "2019-03-31"),
    ("2019-03-31", "2019-06-30"),
    ("2019-06-30", "2019-09-30"),
    ("2019-09-30", "2019-12-31"),
    ("2019-12-31", "2020-03-31"),
    ("2020-03-31", "2020-06-30"),
    ("2020-06-30", "2020-09-30"),
    ("2020-09-30", "2020-12-31"),
    ("2020-12-31", "2021-03-31"),
    ("2021-03-31", "2021-06-30"),
    ("2021-06-30", "2021-09-30"),
    ("2021-09-30", "2021-12-31"),
    ("2021-12-31", "2022-03-31"),
    ("2022-03-31", "2022-06-30"),
    ("2022-06-30", "2022-09-30"),
    ("2022-09-30", "2022-12-31"),
    ("2022-12-31", "2023-03-31"),
    ("2023-03-31", "2023-06-30"),
    ("2023-06-30", "2023-09-30"),
    ("2023-09-30", "2023-12-31"),
    ("2023-12-31", "2024-03-31"),
    ("2024-03-31", "2024-06-30"),
    ("2024-06-30", "2024-09-30"),
    ("2024-09-30", "2024-12-31"),
    ("2024-12-31", "2025-03-31"),
    ("2025-03-31", "2025-06-30"),
    ("2025-06-30", "2025-09-30"),
    ("2025-09-30", "2025-12-31"),
]


# ── DB helpers ────────────────────────────────────────────────────────────────
def _engine():  # pragma: no cover
    url = (
        f"postgresql+psycopg2://{PG['user']}:{PG['password']}"
        f"@{PG['host']}:{PG['port']}/{PG['database']}"
    )
    return create_engine(url)


def _clean(val):
    if val is None or val is pd.NA:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


# ── Scoring helpers ───────────────────────────────────────────────────────────
def _assign_groups(sectors):
    counts = sectors.value_counts()
    small = counts[counts < SMALL_SECTOR_MIN].index
    groups = sectors.copy()
    groups[groups.isin(small)] = "__pooled__"
    return groups


def _winsorise(s):
    valid = s.dropna()
    if len(valid) < 2:
        return s
    lo, hi = valid.quantile([WINSOR_LO, WINSOR_HI])
    return s.clip(lower=lo, upper=hi)


def _to_zscore(s):
    valid_mask = s.notna()
    n = valid_mask.sum()
    if n < 2:
        return pd.Series(np.nan, index=s.index)
    result = pd.Series(np.nan, index=s.index, dtype=float)
    ranks = s[valid_mask].rank(method="average")
    p = ranks / (n + 1)
    result[valid_mask] = p.apply(norm.ppf)
    return result


def sector_neutral_zscore(values, sectors):
    groups = _assign_groups(sectors)
    result = pd.Series(np.nan, index=values.index, dtype=float)
    for group, idx in groups.groupby(groups).groups.items():
        s = _winsorise(values.loc[idx].copy())
        result.loc[idx] = _to_zscore(s).values
    return result


# ── Price cache ───────────────────────────────────────────────────────────────
# All prices are downloaded ONCE for the full 2014–2026 range and cached to
# disk as a Parquet file. Subsequent runs load from cache instantly, avoiding
# Yahoo Finance rate limits entirely.

CACHE_PATH = BASE / "results" / "_price_cache.parquet"
PRICE_CACHE: pd.DataFrame | None = None  # in-memory after first load


def _download_batch(
    symbols: list, start: str, end: str, retries: int = 3  # pragma: no cover
) -> pd.DataFrame:
    """Download one batch with exponential backoff retry."""
    for attempt in range(retries):
        try:
            raw = yf.download(
                symbols, start=start, end=end, auto_adjust=True, progress=False, threads=True
            )
            if raw.empty:
                return pd.DataFrame()
            close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
            if not isinstance(raw.columns, pd.MultiIndex):
                close.columns = symbols
            if hasattr(close.index, "tz") and close.index.tz is not None:
                close.index = close.index.tz_localize(None)
            return close
        except Exception as e:
            wait = 2**attempt * 5  # 5s, 10s, 20s
            print(f"    Batch attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)
    print(f"    Batch failed after {retries} attempts — skipping.")
    return pd.DataFrame()


def build_price_cache(symbols: list):  # pragma: no cover
    """Download all prices for all symbols once and save to disk."""
    global PRICE_CACHE
    # Full window: 13 months before earliest date through end of 2026
    start = "2014-10-01"
    end = "2026-01-15"

    print(f"\n  Building price cache: {len(symbols)} symbols, {start} → {end}")
    print(f"  Cache will be saved to: {CACHE_PATH.name}")
    print("  (This runs once — subsequent runs load from cache instantly)\n")

    frames = []
    n_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"    Batch {batch_num}/{n_batches} ({len(batch)} symbols)...", end=" ")
        df = _download_batch(batch, start, end)
        if not df.empty:
            frames.append(df)
            print(f"OK ({len(df)} rows)")
        else:
            print("empty")
        if i + BATCH_SIZE < len(symbols):
            time.sleep(BATCH_SLEEP)

    if not frames:
        raise RuntimeError("Price cache build failed — no data downloaded.")

    cache = pd.concat(frames, axis=1)
    cache = cache.loc[:, ~cache.columns.duplicated()]
    cache.index = pd.to_datetime(cache.index)
    cache.to_parquet(CACHE_PATH)
    PRICE_CACHE = cache
    print(f"\n  Cache saved: {len(cache.columns)} symbols × {len(cache)} days")
    return cache


def load_price_cache() -> pd.DataFrame:  # pragma: no cover
    """Load cache from disk if available, otherwise return None."""
    global PRICE_CACHE
    if PRICE_CACHE is not None:
        return PRICE_CACHE
    if CACHE_PATH.exists():
        print(f"  Loading price cache from disk ({CACHE_PATH.name})...")
        PRICE_CACHE = pd.read_parquet(CACHE_PATH)
        print(f"  Cache loaded: {len(PRICE_CACHE.columns)} symbols × {len(PRICE_CACHE)} days")
        return PRICE_CACHE
    return None


def get_prices_for_symbol(symbol: str) -> pd.Series | None:  # pragma: no cover
    """Slice a single symbol's price series from the in-memory cache."""
    cache = PRICE_CACHE
    if cache is None or symbol not in cache.columns:
        return None
    s = cache[symbol].dropna()
    return s if len(s) >= MIN_DAYS else None


# ── Price helpers ─────────────────────────────────────────────────────────────
def price_on_or_before(series, target):
    t = pd.Timestamp(target)
    before = series[series.index <= t]
    return float(before.iloc[-1]) if not before.empty else None


def price_on_or_after(series, target):
    t = pd.Timestamp(target)
    after = series[series.index >= t]
    return float(after.iloc[0]) if not after.empty else None


def fetch_prices_for_date(symbols, rebalance_date):  # pragma: no cover
    """Return price dict sliced from in-memory cache (no API call)."""
    r_dt = date.fromisoformat(rebalance_date)
    all_prices = {}
    for sym in symbols:
        s = get_prices_for_symbol(sym.strip())
        if s is not None:
            all_prices[sym.strip()] = s
    return all_prices, r_dt


def compute_low_vol(all_prices, symbols, r_dt):
    """252-day trailing annualised volatility (inverted so low vol = high score)."""
    lv_map = {}
    start_252 = r_dt - timedelta(days=380)
    for sym in symbols:
        series = all_prices.get(sym)
        if series is None:
            lv_map[sym] = np.nan
            continue
        window = series[series.index >= pd.Timestamp(start_252)]
        if len(window) < MIN_DAYS:
            lv_map[sym] = np.nan
            continue
        px = window / 100.0 if sym.endswith(".L") else window
        log_rets = np.log(px / px.shift(1)).dropna()
        lv_map[sym] = float(log_rets.std() * np.sqrt(252))
    return lv_map


def compute_momentum(all_prices, symbols, r_dt):
    """12-1 month momentum (skip last month to avoid reversal)."""
    skip_dt = r_dt - timedelta(days=30)
    start_dt = r_dt - timedelta(days=395)
    mom_map = {}
    for sym in symbols:
        series = all_prices.get(sym)
        if series is None:
            mom_map[sym] = np.nan
            continue
        px = series / 100.0 if sym.endswith(".L") else series
        p_num = price_on_or_before(px, skip_dt.isoformat())
        p_den = price_on_or_before(px, start_dt.isoformat())
        if p_num is None or p_den is None or p_den <= 0:
            mom_map[sym] = np.nan
        else:
            mom_map[sym] = (p_num / p_den) - 1.0
    return mom_map


def _normalise_01(s: pd.Series) -> pd.Series:
    """Min-max normalise a series to [0, 1], ignoring NaN."""
    mn, mx = s.min(), s.max()
    if mx > mn:
        return (s - mn) / (mx - mn)
    return pd.Series(0.5, index=s.index)


def build_composite(df):
    """Recompute 3-factor composite (Value + Quality + Momentum) and assign quintiles.

    All three component scores are normalised to [0, 1] before combining so that
    the stated weights (35/35/30) reflect actual contribution to the composite.
    value_score and quality_score from step04 are already [0, 1]; momentum_score
    is a z-score and must be normalised here to the same scale.
    """
    mask_v = df["value_score"].notna()
    mask_q = df["quality_score"].notna()
    mask_m = df["momentum_score"].notna()

    # Normalise all three to [0, 1] so weights are meaningful
    v = _normalise_01(df["value_score"].fillna(df["value_score"].median()))
    q = _normalise_01(df["quality_score"].fillna(df["quality_score"].median()))
    m = _normalise_01(df["momentum_score"].fillna(df["momentum_score"].median()))

    num = mask_v * W_VALUE * v + mask_q * W_QUALITY * q + mask_m * W_MOMENTUM * m
    den = mask_v * W_VALUE + mask_q * W_QUALITY + mask_m * W_MOMENTUM

    composite_raw = pd.Series(np.where(den > 0, num / den, np.nan), index=df.index, dtype=float)
    df["composite_score"] = _to_zscore(composite_raw)

    valid = df["composite_score"].notna()
    n = valid.sum()
    pct = pd.Series(np.nan, index=df.index, dtype=float)
    if n > 0:
        ranks = df.loc[valid, "composite_score"].rank(method="average")
        pct[valid] = ranks / n
    df["composite_percentile"] = pct

    def _q(p):
        if pd.isna(p):
            return None
        if p >= 0.80:
            return 1
        if p >= 0.60:
            return 2
        if p >= 0.40:
            return 3
        if p >= 0.20:
            return 4
        return 5

    df["quintile"] = df["composite_percentile"].apply(_q)
    return df


# ── Phase 1: Score Dec 31 dates ───────────────────────────────────────────────
def score_dec_date(eng, rebalance_date):  # pragma: no cover
    """Add low_vol + momentum to an existing Dec 31 date, recompute composite."""
    print(f"\n{'='*55}")
    print(f"  Scoring {rebalance_date}")
    print(f"{'='*55}")

    with eng.connect() as conn:
        df = pd.read_sql(
            text(
                """
            SELECT TRIM(fv.symbol) AS symbol,
                   cs.gics_sector,
                   fv.value_score, fv.quality_score
            FROM systematic_equity.factor_values fv
            LEFT JOIN systematic_equity.company_static cs
                   ON TRIM(fv.symbol) = TRIM(cs.symbol)
            WHERE fv.period_date = :d
              AND fv.value_score IS NOT NULL
        """
            ),
            conn,
            params={"d": rebalance_date},
        )

    if df.empty:
        print("  No value/quality scores found — skipping")
        return

    df["gics_sector"] = df["gics_sector"].fillna("Unknown")
    symbols = df["symbol"].tolist()
    print(f"  {len(symbols)} companies with value+quality scores")
    print("  Downloading prices ...")

    all_prices, r_dt = fetch_prices_for_date(symbols, rebalance_date)
    print(f"  Prices retrieved: {len(all_prices)}/{len(symbols)}")

    # Low volatility
    lv_map = compute_low_vol(all_prices, symbols, r_dt)
    df["low_vol"] = df["symbol"].map(lv_map)
    df["z_low_vol"] = sector_neutral_zscore(-df["low_vol"], df["gics_sector"])
    df["low_vol_score"] = _to_zscore(df["z_low_vol"])
    n_lv = df["low_vol_score"].notna().sum()
    print(f"  Low vol computed: {n_lv}/{len(symbols)}")

    # Momentum
    mom_map = compute_momentum(all_prices, symbols, r_dt)
    df["momentum"] = df["symbol"].map(mom_map)
    df["z_momentum"] = sector_neutral_zscore(df["momentum"], df["gics_sector"])
    df["momentum_score"] = _to_zscore(df["z_momentum"])
    n_mom = df["momentum_score"].notna().sum()
    print(f"  Momentum computed: {n_mom}/{len(symbols)}")

    # Composite + quintiles
    df = build_composite(df)
    q_dist = df["quintile"].value_counts().sort_index().to_dict()
    print(f"  Quintiles: {q_dist}")

    # Update DB
    update_sql = text(
        """
        UPDATE systematic_equity.factor_values SET
            low_vol              = :low_vol,
            z_low_vol            = :z_low_vol,
            low_vol_score        = :low_vol_score,
            momentum             = :momentum,
            z_momentum           = :z_momentum,
            momentum_score       = :momentum_score,
            composite_score      = :composite_score,
            composite_percentile = :composite_percentile,
            quintile             = :quintile
        WHERE TRIM(symbol) = :symbol
          AND period_date  = :period_date
    """
    )
    records = [
        {
            "symbol": row["symbol"],
            "period_date": rebalance_date,
            "low_vol": _clean(row["low_vol"]),
            "z_low_vol": _clean(row["z_low_vol"]),
            "low_vol_score": _clean(row["low_vol_score"]),
            "momentum": _clean(row["momentum"]),
            "z_momentum": _clean(row["z_momentum"]),
            "momentum_score": _clean(row["momentum_score"]),
            "composite_score": _clean(row["composite_score"]),
            "composite_percentile": _clean(row["composite_percentile"]),
            "quintile": _clean(row["quintile"]),
        }
        for row in df.to_dict("records")
    ]
    with eng.begin() as conn:
        conn.execute(update_sql, records)
    print(f"  DB updated: {len(records)} rows")
    return df


# ── Phase 2: Insert quarterly dates ──────────────────────────────────────────
def insert_quarterly_date(eng, src_dec_date, target_date):  # pragma: no cover
    """Copy Dec fundamentals to a quarterly date, add fresh low_vol + momentum."""
    print(f"\n  → {target_date}  (fundamentals from {src_dec_date})")

    # Load scored Dec date as base
    with eng.connect() as conn:
        src = pd.read_sql(
            text(
                """
            SELECT TRIM(fv.symbol) AS symbol,
                   cs.gics_sector,
                   fv.value_score, fv.quality_score,
                   fv.bp, fv.ey, fv.cfy, fv.dy,
                   fv.gpa, fv.roa, fv.wca, fv.ltde,
                   fv.z_bp, fv.z_ey, fv.z_cfy, fv.z_dy,
                   fv.z_gpa, fv.z_roa, fv.z_wca, fv.z_ltde,
                   fv.market_cap, fv.book_value
            FROM systematic_equity.factor_values fv
            LEFT JOIN systematic_equity.company_static cs
                   ON TRIM(fv.symbol) = TRIM(cs.symbol)
            WHERE fv.period_date = :d
              AND fv.composite_score IS NOT NULL
        """
            ),
            conn,
            params={"d": src_dec_date},
        )

    if src.empty:
        print(f"    No data from {src_dec_date} — skipping")
        return

    src["gics_sector"] = src["gics_sector"].fillna("Unknown")
    symbols = src["symbol"].tolist()

    # Download prices for this quarterly date
    all_prices, r_dt = fetch_prices_for_date(symbols, target_date)
    print(f"    Prices: {len(all_prices)}/{len(symbols)}")

    # Low vol + momentum for this specific date
    lv_map = compute_low_vol(all_prices, symbols, r_dt)
    mom_map = compute_momentum(all_prices, symbols, r_dt)

    src["low_vol"] = src["symbol"].map(lv_map)
    src["momentum"] = src["symbol"].map(mom_map)

    src["z_low_vol"] = sector_neutral_zscore(-src["low_vol"], src["gics_sector"])
    src["z_momentum"] = sector_neutral_zscore(src["momentum"], src["gics_sector"])
    src["low_vol_score"] = _to_zscore(src["z_low_vol"])
    src["momentum_score"] = _to_zscore(src["z_momentum"])

    src = build_composite(src)
    q_dist = src["quintile"].value_counts().sort_index().to_dict()
    print(f"    Quintiles: {q_dist}")

    # Check if rows already exist for this date
    with eng.connect() as conn:
        existing = pd.read_sql(
            text(
                """
            SELECT COUNT(*) AS n FROM systematic_equity.factor_values
            WHERE period_date = :d
        """
            ),
            conn,
            params={"d": target_date},
        )
    n_exist = int(existing["n"].iloc[0])

    insert_sql = text(
        """
        INSERT INTO systematic_equity.factor_values
            (symbol, period_date, market_cap, book_value,
             bp, ey, cfy, dy, gpa, roa, wca, ltde,
             z_bp, z_ey, z_cfy, z_dy, z_gpa, z_roa, z_wca, z_ltde,
             value_score, quality_score,
             low_vol, z_low_vol, low_vol_score,
             momentum, z_momentum, momentum_score,
             composite_score, composite_percentile, quintile)
        VALUES
            (:symbol, :period_date, :market_cap, :book_value,
             :bp, :ey, :cfy, :dy, :gpa, :roa, :wca, :ltde,
             :z_bp, :z_ey, :z_cfy, :z_dy, :z_gpa, :z_roa, :z_wca, :z_ltde,
             :value_score, :quality_score,
             :low_vol, :z_low_vol, :low_vol_score,
             :momentum, :z_momentum, :momentum_score,
             :composite_score, :composite_percentile, :quintile)
        ON CONFLICT (symbol, period_date) DO UPDATE SET
            low_vol              = EXCLUDED.low_vol,
            z_low_vol            = EXCLUDED.z_low_vol,
            low_vol_score        = EXCLUDED.low_vol_score,
            momentum             = EXCLUDED.momentum,
            z_momentum           = EXCLUDED.z_momentum,
            momentum_score       = EXCLUDED.momentum_score,
            composite_score      = EXCLUDED.composite_score,
            composite_percentile = EXCLUDED.composite_percentile,
            quintile             = EXCLUDED.quintile,
            value_score          = EXCLUDED.value_score,
            quality_score        = EXCLUDED.quality_score
    """
    )

    def _s(r, c):
        return _clean(r.get(c))

    records = [
        {
            "symbol": r["symbol"],
            "period_date": target_date,
            "market_cap": _s(r, "market_cap"),
            "book_value": _s(r, "book_value"),
            "bp": _s(r, "bp"),
            "ey": _s(r, "ey"),
            "cfy": _s(r, "cfy"),
            "dy": _s(r, "dy"),
            "gpa": _s(r, "gpa"),
            "roa": _s(r, "roa"),
            "wca": _s(r, "wca"),
            "ltde": _s(r, "ltde"),
            "z_bp": _s(r, "z_bp"),
            "z_ey": _s(r, "z_ey"),
            "z_cfy": _s(r, "z_cfy"),
            "z_dy": _s(r, "z_dy"),
            "z_gpa": _s(r, "z_gpa"),
            "z_roa": _s(r, "z_roa"),
            "z_wca": _s(r, "z_wca"),
            "z_ltde": _s(r, "z_ltde"),
            "value_score": _s(r, "value_score"),
            "quality_score": _s(r, "quality_score"),
            "low_vol": _s(r, "low_vol"),
            "z_low_vol": _s(r, "z_low_vol"),
            "low_vol_score": _s(r, "low_vol_score"),
            "momentum": _s(r, "momentum"),
            "z_momentum": _s(r, "z_momentum"),
            "momentum_score": _s(r, "momentum_score"),
            "composite_score": _s(r, "composite_score"),
            "composite_percentile": _s(r, "composite_percentile"),
            "quintile": _s(r, "quintile"),
        }
        for r in src.to_dict("records")
    ]

    with eng.begin() as conn:
        conn.execute(insert_sql, records)
    action = "updated" if n_exist > 0 else "inserted"
    print(f"    DB {action}: {len(records)} rows")
    return src


# ── Phase 3: Compute holding-period returns ───────────────────────────────────
def compute_period_returns(eng, start_date, end_date):  # pragma: no cover
    """Download prices at start and end, compute returns by quintile."""
    # Load quintiles at start_date
    with eng.connect() as conn:
        df = pd.read_sql(
            text(
                """
            SELECT TRIM(fv.symbol) AS symbol,
                   fv.quintile, fv.composite_score,
                   fv.value_score, fv.quality_score, fv.momentum_score
            FROM systematic_equity.factor_values fv
            WHERE fv.period_date = :d
              AND fv.quintile IS NOT NULL
        """
            ),
            conn,
            params={"d": start_date},
        )

    if df.empty:
        print(f"  No data for {start_date}")
        return pd.DataFrame()

    symbols = df["symbol"].tolist()

    # Slice from in-memory price cache — no API call needed
    all_prices = {
        sym.strip(): get_prices_for_symbol(sym.strip())
        for sym in symbols
        if get_prices_for_symbol(sym.strip()) is not None
    }

    rows = []
    for _, row in df.iterrows():
        sym = row["symbol"]
        series = all_prices.get(sym)
        if series is None:
            continue
        px = series / 100.0 if sym.endswith(".L") else series
        p_start = price_on_or_after(px, start_date)
        p_end = price_on_or_before(px, end_date)
        if p_start is None or p_end is None or p_start <= 0:
            continue
        gross_ret = (p_end / p_start) - 1.0
        net_ret = gross_ret - TC_RT
        rows.append(
            {
                "symbol": sym,
                "start_date": start_date,
                "end_date": end_date,
                "quintile": int(row["quintile"]),
                "composite_score": _clean(row["composite_score"]),
                "value_score": _clean(row.get("value_score")),
                "quality_score": _clean(row.get("quality_score")),
                "momentum_score": _clean(row.get("momentum_score")),
                "gross_return": gross_ret,
                "net_return": net_ret,
            }
        )

    result = pd.DataFrame(rows)
    print(f"  {start_date} → {end_date}: {len(result)} returns")
    return result


# ── Phase 4: Combine results + summary ───────────────────────────────────────
def print_summary(all_returns):  # pragma: no cover
    """Print period-by-period table and aggregate stats."""
    print(f"\n{'='*75}")
    print("FULL BACKTEST SUMMARY (2016–2025, 40 quarters)")
    print(f"{'='*75}")

    periods = all_returns.groupby(["start_date", "end_date"])
    header = f"{'Period':<33} {'Q1':>7} {'Q5':>7} {'Spread':>8} {'BM':>7} {'Works'}"
    print(f"\n{header}")
    print("-" * 70)

    works_list = []
    for (s, e), grp in periods:
        bm = grp["net_return"].mean()
        q1 = grp[grp["quintile"] == 1]["net_return"].mean()
        q5 = grp[grp["quintile"] == 5]["net_return"].mean()
        if pd.isna(q1) or pd.isna(q5):
            continue
        spread = q1 - q5
        works = spread > 0
        works_list.append(works)
        tick = "OK" if works else "--"
        period_str = f"{str(s)[:10]} → {str(e)[:10]}"
        print(f"  {period_str:<31} {q1:>6.2%}  {q5:>6.2%}  {spread:>7.2%}  " f"{bm:>6.2%}  {tick}")

    print(f"\n{'='*75}")
    print(
        f"  Factor works: {sum(works_list)}/{len(works_list)} quarters "
        f"({100*sum(works_list)/max(len(works_list), 1):.0f}%)"
    )

    for q in [1, 5]:
        qd = all_returns[all_returns["quintile"] == q]
        period_net = qd.groupby("start_date")["net_return"].mean().sort_index()
        avg = period_net.mean()
        ann = (1 + avg) ** 4 - 1
        ann_vol = period_net.std(ddof=1) * np.sqrt(4)
        rf_q = rf_quarterly_series(period_net.index)
        excess = period_net.values - rf_q.values
        ann_excess = float(np.mean(excess)) * 4
        sharpe = ann_excess / ann_vol if ann_vol > 0 else np.nan
        print(f"  Q{q}: {ann:+.2%} p.a.  vol={ann_vol:.2%}  Sharpe={sharpe:.3f}")

    # Compute period-level Q1-Q5 spread (mean return per quintile per period)
    q1_period = all_returns[all_returns["quintile"] == 1].groupby("start_date")["net_return"].mean()
    q5_period = all_returns[all_returns["quintile"] == 5].groupby("start_date")["net_return"].mean()
    common = q1_period.index.intersection(q5_period.index)
    spread_mean = (q1_period[common] - q5_period[common]).mean()
    print(f"  Avg Q1-Q5 spread: {spread_mean:+.2%}/quarter")


def make_nav_chart(all_returns):  # pragma: no cover
    COLORS = {1: "#2166ac", 2: "#74add1", 3: "#fee090", 4: "#f46d43", 5: "#d73027"}

    fig, axes = plt.subplots(2, 1, figsize=(13, 10))

    # Top panel: full 10-year NAV
    ax = axes[0]
    for q in range(1, 6):
        # Average across stocks per period first, THEN compound
        qd = (
            all_returns[all_returns["quintile"] == q]
            .groupby(["start_date", "end_date"])["net_return"]
            .mean()
            .reset_index()
            .sort_values("start_date")
        )
        nav = np.insert((1 + qd["net_return"]).cumprod().values, 0, 1.0)
        dates = [qd["start_date"].iloc[0]] + list(qd["end_date"])
        ax.plot(dates, nav * 100, label=f"Q{q}", color=COLORS[q], linewidth=2)

    bm_by_period = all_returns.groupby(["start_date", "end_date"])["net_return"].mean()
    bm_nav = np.insert((1 + bm_by_period.values).cumprod(), 0, 1.0)
    bm_dates = [bm_by_period.index[0][0]] + [e for _, e in bm_by_period.index]
    ax.plot(
        bm_dates, bm_nav * 100, label="EW Benchmark", color="black", linewidth=1.5, linestyle="--"
    )

    # Shade 2022 bear market
    ax.axvspan(
        pd.Timestamp("2022-01-01"),
        pd.Timestamp("2022-12-31"),
        alpha=0.08,
        color="red",
        label="2022 Bear",
    )
    ax.axvspan(
        pd.Timestamp("2020-01-01"),
        pd.Timestamp("2020-06-30"),
        alpha=0.08,
        color="orange",
        label="COVID crash",
    )

    ax.set_title(
        "3-Factor Model: 10-Year Backtest NAV by Quintile (2016–2025)\n"
        "40% Value + 40% Quality + 20% Momentum  |  base = 100",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("NAV (base 100)")
    ax.legend(loc="upper left", fontsize=9, ncol=2)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    # Bottom panel: annual Q1-Q5 spread
    ax2 = axes[1]
    periods = all_returns.groupby(["start_date", "end_date"])
    spread_rows = []
    for (s, e), grp in periods:
        q1 = grp[grp["quintile"] == 1]["net_return"].mean()
        q5 = grp[grp["quintile"] == 5]["net_return"].mean()
        if not (pd.isna(q1) or pd.isna(q5)):
            spread_rows.append({"date": pd.Timestamp(e), "spread": q1 - q5})
    sdf = pd.DataFrame(spread_rows).sort_values("date")
    colors = ["#2166ac" if v > 0 else "#d73027" for v in sdf["spread"]]
    ax2.bar(sdf["date"], sdf["spread"] * 100, color=colors, width=60, alpha=0.8)
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_title(
        "Q1 − Q5 Spread per Quarter (positive = factor worked)", fontsize=11, fontweight="bold"
    )
    ax2.set_ylabel("Net return spread (%)")
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))

    fig.tight_layout(pad=2.5)
    path = CHARTS / "21_10year_nav.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path.name}")


def make_ic_chart(all_returns):  # pragma: no cover
    """Rolling IC bar chart over 40 quarters."""
    with _engine().connect() as conn:
        scores = pd.read_sql(
            text(
                """
            SELECT TRIM(symbol) AS symbol, period_date, composite_score
            FROM systematic_equity.factor_values
            WHERE period_date >= '2015-12-31'
              AND composite_score IS NOT NULL
        """
            ),
            conn,
        )
    scores["period_date"] = pd.to_datetime(scores["period_date"])

    scores = scores.rename(columns={"composite_score": "factor_score"})
    merged = all_returns.merge(
        scores, left_on=["start_date", "symbol"], right_on=["period_date", "symbol"], how="left"
    )

    ic_rows = []
    for (s, e), grp in merged.groupby(["start_date", "end_date"]):
        g = grp.dropna(subset=["factor_score", "net_return"])
        if len(g) >= 10:
            ic, _ = spearmanr(g["factor_score"], g["net_return"])
            ic_rows.append({"date": pd.Timestamp(e), "ic": ic})

    idf = pd.DataFrame(ic_rows).sort_values("date")

    fig, ax = plt.subplots(figsize=(14, 4))
    colors = ["#2166ac" if v > 0 else "#d73027" for v in idf["ic"]]
    ax.bar(idf["date"], idf["ic"] * 100, color=colors, width=60, alpha=0.85)
    ax.axhline(0, color="black", linewidth=0.8)

    mean_ic = idf["ic"].mean()
    ax.axhline(
        mean_ic * 100,
        color="#2166ac",
        linewidth=1.5,
        linestyle="--",
        label=f"Mean IC = {mean_ic:.2%}",
    )

    hit_rate = (idf["ic"] > 0).mean()
    ax.set_title(
        f"Spearman IC per Quarter — 10-Year Backtest\n"
        f"Mean IC = {mean_ic:.2%}  |  Hit Rate = {hit_rate:.0%}  "
        f"({int(hit_rate*len(idf))}/{len(idf)} quarters)",
        fontsize=11,
        fontweight="bold",
    )
    ax.set_ylabel("IC (%)")
    ax.legend(fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))

    fig.tight_layout()
    path = CHARTS / "22_10year_ic.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():  # pragma: no cover
    eng = _engine()

    # ── Price cache (download once, reuse everywhere) ─────────────────────────
    print("\n" + "=" * 55)
    print("PRICE CACHE")
    print("=" * 55)
    cache = load_price_cache()
    if cache is None:
        # Collect all symbols from DB
        with eng.connect() as conn:
            sym_df = pd.read_sql(
                text(
                    """
                SELECT DISTINCT TRIM(symbol) AS symbol
                FROM systematic_equity.factor_values
                WHERE period_date >= '2015-12-31'
                  AND composite_score IS NOT NULL
            """
                ),
                conn,
            )
        all_symbols = sym_df["symbol"].tolist()
        build_price_cache(all_symbols)
    else:
        print("  Cache already exists — skipping download.")

    # ── Phase 1: Score Dec 31 dates 2015–2020 ────────────────────────────────
    print("\n" + "=" * 55)
    print("PHASE 1: Scoring Dec 31 dates (2015–2020)")
    print("=" * 55)
    for dec_date in DEC_DATES:
        score_dec_date(eng, dec_date)

    # ── Phase 2: Insert quarterly dates ──────────────────────────────────────
    print("\n" + "=" * 55)
    print("PHASE 2: Inserting quarterly rebalance dates")
    print("=" * 55)
    for dec_date, quarterly_dates in QUARTERLY_MAP.items():
        print(f"\nFundamentals from {dec_date}:")
        for q_date in quarterly_dates:
            insert_quarterly_date(eng, dec_date, q_date)

    # ── Phase 3: Compute holding-period returns ───────────────────────────────
    print("\n" + "=" * 55)
    print("PHASE 3: Computing 24 new holding-period returns")
    print("=" * 55)

    new_return_rows = []
    for start_date, end_date in NEW_PERIODS:
        period_df = compute_period_returns(eng, start_date, end_date)
        if not period_df.empty:
            new_return_rows.append(period_df)

    new_returns = (
        pd.concat(new_return_rows, ignore_index=True) if new_return_rows else pd.DataFrame()
    )

    # Save new returns
    if not new_returns.empty:
        new_returns["start_date"] = pd.to_datetime(new_returns["start_date"])
        new_returns["end_date"] = pd.to_datetime(new_returns["end_date"])
        new_returns.to_csv(RESULTS / "stock_returns_2015_2021.csv", index=False)
        print(f"\n  Saved stock_returns_2015_2021.csv ({len(new_returns)} rows)")

    # ── Phase 4: Combine with existing extended results ───────────────────────
    print("\n" + "=" * 55)
    print("PHASE 4: Combining all results")
    print("=" * 55)

    all_returns = new_returns.sort_values(["start_date", "symbol"]).reset_index(drop=True)
    all_returns.to_csv(RESULTS / "stock_returns_10year.csv", index=False)
    print(
        f"  Saved stock_returns_10year.csv ({len(all_returns)} rows, "
        f"{all_returns.groupby(['start_date', 'end_date']).ngroups} periods)"
    )

    # ── Summary + charts ──────────────────────────────────────────────────────
    print_summary(all_returns)

    print("\nGenerating charts...")
    make_nav_chart(all_returns)
    make_ic_chart(all_returns)

    print("\nDone. 10-year backtest complete.")
    print("New files:")
    print("  results/stock_returns_2015_2021.csv  — 24 new quarters")
    print("  results/stock_returns_10year.csv     — all 40 quarters")
    print("  results/charts/21_10year_nav.png     — full NAV chart")
    print("  results/charts/22_10year_ic.png      — IC bar chart")


if __name__ == "__main__":
    main()
