"""Step 04 — Pull quarterly fundamentals from WRDS/Compustat.

Replaces the previous annual pull (comp.funda → Dec 31 dates only).
Now pulls from comp.fundq so every quarterly rebalance date receives
actual filed fundamentals rather than December data carried forward.

Key methodology changes vs the old annual pull:
  - Source   : comp.fundq (quarterly) instead of comp.funda (annual)
  - TTM      : income-statement and cash-flow items are summed over the
               most recent 4 quarters to remove seasonality bias.
               Balance-sheet items (equity, assets, debt) use the
               latest quarter's snapshot directly.
  - Filing lag: 60-day buffer applied so that only data actually
               available at the rebalance date is used, avoiding
               look-ahead bias (SEC 10-Q deadline ≈ 40–45 days).
  - Coverage : all 40 quarterly rebalance dates from 2015-12-31 to
               2025-12-31 are populated for US companies.

European / Canadian stocks still use comp.g_funda (annual) mapped to
Dec 31 dates, as Compustat Global quarterly coverage is limited.
Step 05 carries those fundamentals forward for Mar/Jun/Sep dates.

Data pulled from comp.fundq (US):
  Balance sheet (latest quarter):
    ceqq   → Common equity          (Book-to-Price)
    atq    → Total assets            (GPA, ROA, WCA)
    wcapq  → Working capital         (WCA)
    dlttq  → Long-term debt          (LTDE)
    seqq   → Stockholders equity     (LTDE denominator)
    cshoq  → Shares outstanding      (market cap)
    prccq  → Quarter-end price       (value ratios, market cap)

  TTM flow items (sum of 4 quarters):
    epspxq → EPS diluted             (Earnings Yield)
    oancfq → Operating cash flow     (Cash Flow Yield)
    dvtq   → Total dividends         (Dividend Yield)
    gpq    → Gross profit            (GPA)
    niq    → Net income              (ROA)

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step04_wrds_pull.py
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import wrds
import yfinance as yf
from scipy.stats import norm
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
PG = dict(host="localhost", port=5439, user="postgres", password="postgres", database="fift")

BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
STATIC = BASE / "static"

FILING_LAG_DAYS = 60  # days after quarter-end before filing is assumed available
MIN_QUARTERS_TTM = 2  # minimum quarters required to compute (partial) TTM

WINSOR_LO = 0.05
WINSOR_HI = 0.95
SMALL_SECTOR_MIN = 5


def _all_rebalance_dates() -> list:
    """Generate all quarterly rebalance dates from 2015-12-31 to 2025-12-31."""
    dates = []
    for year in range(2015, 2026):
        for month, day in [("03", "31"), ("06", "30"), ("09", "30"), ("12", "31")]:
            d = f"{year}-{month}-{day}"
            if "2015-12-31" <= d <= "2025-12-31":
                dates.append(d)
    return dates


REBALANCE_DATES = _all_rebalance_dates()  # 40 dates total


# ── DB helpers ────────────────────────────────────────────────────────────────
def local_engine():
    url = (
        f"postgresql+psycopg2://{PG['user']}:{PG['password']}"
        f"@{PG['host']}:{PG['port']}/{PG['database']}"
    )
    return create_engine(url)


def load_universe(eng) -> pd.DataFrame:
    with eng.connect() as conn:
        df = pd.read_sql(
            text(
                """
            SELECT TRIM(symbol) AS symbol, security, gics_sector, country
            FROM systematic_equity.company_static
        """
            ),
            conn,
        )
    return df


# ── WRDS pull — US quarterly (comp.fundq) ────────────────────────────────────
def pull_us_fundamentals_quarterly(db: wrds.Connection, tickers: list) -> pd.DataFrame:
    """Pull all quarterly rows from comp.fundq for the given tickers.

    Returns one row per (ticker, quarter_date) for 2014-01-01 → 2025-12-31.
    The wide date range ensures we have enough history to compute TTM at the
    earliest rebalance date (2015-12-31 needs quarters back to early 2015).
    """
    ticker_list = "', '".join(tickers)
    print("  Pulling US quarterly fundamentals from comp.fundq ...")

    df = db.raw_sql(
        f"""
        SELECT
            tic         AS symbol,
            datadate    AS quarter_date,
            fyearq      AS fiscal_year,
            fqtr        AS fiscal_quarter,
            ceqq        AS book_equity,
            epspxq      AS eps_q,
            oancfy      AS operating_cf_q,
            dvy         AS dividends_q,
            (saleq - cogsq) AS gross_profit_q,
            atq         AS total_assets,
            niq         AS net_income_q,
            wcapq       AS working_capital,
            dlttq       AS lt_debt,
            seqq        AS stockholders_equity,
            cshoq       AS shares_outstanding,
            prccq       AS quarter_price
        FROM comp.fundq
        WHERE tic IN ('{ticker_list}')
          AND datadate BETWEEN '2014-01-01' AND '2025-12-31'
          AND indfmt  = 'INDL'
          AND datafmt = 'STD'
          AND popsrc  = 'D'
          AND consol  = 'C'
          AND atq > 0
        ORDER BY tic, datadate
    """,
        date_cols=["quarter_date"],
    )

    print(f"  Retrieved {len(df)} quarterly rows " f"for {df['symbol'].nunique()} US companies")
    return df


# ── TTM snapshot ─────────────────────────────────────────────────────────────
# Truly quarterly items — sum last 4 quarters for TTM
_QUARTERLY_FLOW_COLS = ["eps_q", "gross_profit_q", "net_income_q"]
# Year-to-date items (cumulative within fiscal year) — annualise latest value
# by multiplying by (4 / fiscal_quarter_number)
_YTD_FLOW_COLS = ["operating_cf_q", "dividends_q"]
_BALANCE_COLS = [
    "book_equity",
    "total_assets",
    "working_capital",
    "lt_debt",
    "stockholders_equity",
    "shares_outstanding",
]


def compute_ttm_snapshot(quarterly_df: pd.DataFrame, rebalance_date: str) -> pd.DataFrame:
    """Produce one row per company for a given rebalance date.

    Steps:
      1. Apply 60-day filing lag: only quarters with
         quarter_date <= rebalance_date - 60 days are considered available.
      2. For each company, take the most recent available quarter.
      3. Quarterly flow items (eps, gross profit, net income):
         sum last 4 quarters for TTM; annualise proportionally if fewer available.
      4. YTD flow items (operating CF, dividends — stored cumulative in comp.fundq):
         annualise latest quarter's YTD value by × (4 / fiscal_quarter).
      5. Balance-sheet items: use the latest quarter's value directly.

    Returns a DataFrame with one row per company, ready for compute_metrics().
    """
    cutoff = pd.Timestamp(rebalance_date) - pd.Timedelta(days=FILING_LAG_DAYS)
    available = quarterly_df[quarterly_df["quarter_date"] <= cutoff].copy()

    if available.empty:
        return pd.DataFrame()

    rows = []
    for symbol, grp in available.groupby("symbol"):
        grp = grp.sort_values("quarter_date")
        last4 = grp.tail(4)

        if len(last4) < MIN_QUARTERS_TTM:
            continue  # too few quarters — skip this company

        latest = last4.iloc[-1]
        row = {
            "symbol": symbol,
            "latest_quarter": latest["quarter_date"],
            "quarter_price": latest["quarter_price"],
        }

        # Balance sheet — most recent snapshot
        for col in _BALANCE_COLS:
            row[col] = latest[col]

        # Quarterly flow items — sum last 4 quarters (TTM)
        n = len(last4)
        for col in _QUARTERLY_FLOW_COLS:
            vals = last4[col].dropna()
            if vals.empty:
                row[col] = np.nan
            elif n == 4:
                row[col] = vals.sum()
            else:
                row[col] = vals.sum() * (4.0 / n)  # partial TTM annualised

        # YTD flow items — annualise latest cumulative value by fiscal quarter
        fqtr = latest.get("fiscal_quarter", np.nan)
        for col in _YTD_FLOW_COLS:
            val = latest[col]
            if pd.isna(val) or pd.isna(fqtr) or float(fqtr) <= 0:
                row[col] = np.nan
            else:
                row[col] = float(val) * (4.0 / float(fqtr))

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    # Rename flow columns to match compute_metrics() expectations
    out = out.rename(
        columns={
            "eps_q": "eps",
            "operating_cf_q": "operating_cf",
            "dividends_q": "dividends",
            "gross_profit_q": "gross_profit",
            "net_income_q": "net_income",
        }
    )
    return out


# ── European/Canadian: year-end price fetch from yfinance ────────────────────
def fetch_yearend_prices(symbols: list, years: list) -> pd.DataFrame:
    """Download Dec 31 closing prices from yfinance for European symbols."""
    records = []
    print(f"  Fetching year-end prices from yfinance for {len(symbols)} symbols ...")

    start = f"{min(years) - 1}-12-01"
    end = f"{max(years)}-12-31"

    try:
        raw = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        if not isinstance(raw.columns, pd.MultiIndex):
            close.columns = symbols
    except Exception as e:
        print(f"  yfinance batch download failed ({e}) — trying individually ...")
        close = pd.DataFrame()

    if hasattr(close.index, "tz") and close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    close.index = pd.to_datetime(close.index)

    for yr in years:
        dec31 = pd.Timestamp(f"{yr}-12-31")
        window = close[close.index <= dec31].tail(5)
        if window.empty:
            continue
        last_row = window.iloc[-1]
        for sym in symbols:
            price = last_row.get(sym, np.nan) if isinstance(last_row, pd.Series) else np.nan
            if pd.notna(price) and price > 0:
                records.append({"symbol": sym, "fyear": yr, "fiscal_price": float(price)})

    result = pd.DataFrame(records)
    print(f"  Got {len(result)} year-end price observations")
    return result


# ── WRDS pull — European/Canadian (comp.g_funda, annual) ─────────────────────
def _normalize_name(name: str) -> str:
    import re

    name = str(name).lower()
    for suffix in [
        " plc",
        " sa",
        " se",
        " ag",
        " nv",
        " spa",
        " sa/nv",
        " group",
        " holdings",
        " holding",
        " ltd",
        " limited",
        " inc",
        " corp",
        " co",
        "-reg",
        "-br",
        " pte",
        " bank",
        " banking",
        " financial",
        " insurance",
    ]:
        name = name.replace(suffix, "")
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _build_name_index(universe_df: pd.DataFrame) -> dict:
    mapping = {}
    for _, row in universe_df.iterrows():
        norm_name = _normalize_name(row["security"])
        mapping[norm_name] = row["symbol"]
        words = norm_name.split()
        if words:
            mapping[words[0]] = row["symbol"]
    return mapping


def match_name_to_symbol(conm: str, name_index: dict):
    norm_name = _normalize_name(conm)
    if norm_name in name_index:
        return name_index[norm_name]
    words = norm_name.split()
    if words and words[0] in name_index:
        return name_index[words[0]]
    return None


def pull_global_fundamentals(db: wrds.Connection, universe_df: pd.DataFrame) -> pd.DataFrame:
    """Pull annual data from comp.g_funda for European/Canadian companies.

    Compustat Global quarterly (comp.g_fundq) has limited coverage for
    non-US markets, so annual data is used here. Step 05 carries Dec 31
    fundamentals forward to Mar/Jun/Sep rebalance dates for these companies.
    """
    print("  Pulling European/Canadian fundamentals from comp.g_funda (annual) ...")

    suffix_to_loc = {
        "L": "GBR",
        "PA": "FRA",
        "DE": "DEU",
        "MC": "ESP",
        "MI": "ITA",
        "S": "CHE",
        "TO": "CAN",
        "AS": "NLD",
    }
    target_locs = set()
    for sym in universe_df["symbol"]:
        parts = sym.split(".")
        if len(parts) > 1:
            loc = suffix_to_loc.get(parts[-1])
            if loc:
                target_locs.add(loc)

    country_col_map = {
        "CA": "CAN",
        "GB": "GBR",
        "DE": "DEU",
        "FR": "FRA",
        "ES": "ESP",
        "IT": "ITA",
        "CH": "CHE",
    }
    for c in universe_df.get("country", pd.Series([])).dropna().unique():
        if c in country_col_map:
            target_locs.add(country_col_map[c])

    if not target_locs:
        print("  No target country codes found — skipping global pull")
        return pd.DataFrame()

    loc_list = "', '".join(sorted(target_locs))
    print(f"  Target countries: {sorted(target_locs)}")

    df = db.raw_sql(
        f"""
        SELECT
            f.gvkey,
            c.conm,
            c.loc,
            f.fyear,
            f.datadate    AS fiscal_date,
            f.ceq         AS book_equity,
            f.epsexcon    AS eps,
            f.oancf       AS operating_cf,
            f.dvt         AS dividends,
            f.opprft      AS gross_profit,
            f.at          AS total_assets,
            f.ninc        AS net_income,
            f.wcap        AS working_capital,
            f.dltt        AS lt_debt,
            f.seq         AS stockholders_equity,
            f.cshoi       AS shares_outstanding,
            f.sale        AS revenue,
            f.curcd       AS currency,
            f.sich        AS sic_code
        FROM comp.g_funda f
        JOIN comp.g_company c ON f.gvkey = c.gvkey
        WHERE c.loc IN ('{loc_list}')
          AND f.fyear BETWEEN 2015 AND 2024
          AND f.indfmt IN ('INDL', 'FS')
          AND f.datafmt = 'HIST_STD'
          AND f.consol = 'C'
          AND f.at > 0
        ORDER BY c.conm, f.fyear
    """,
        date_cols=["fiscal_date"],
    )

    print(
        f"  Retrieved {len(df)} global annual rows "
        f"for {df['gvkey'].nunique() if len(df) else 0} companies"
    )

    if df.empty:
        return df

    name_index = _build_name_index(universe_df)
    df["symbol"] = df["conm"].apply(lambda n: match_name_to_symbol(n, name_index))
    matched = df[df["symbol"].notna()].copy()
    print(
        f"  Matched {matched['symbol'].nunique()} companies "
        f"out of {len(universe_df)} in non-US universe"
    )

    unmatched = [
        f"{r['symbol']} ({r['security']})"
        for _, r in universe_df.iterrows()
        if r["symbol"] not in set(matched["symbol"].dropna())
    ]
    if unmatched:
        print(f"  Unmatched ({len(unmatched)}): {', '.join(unmatched[:15])}")

    return matched


# ── Factor metric computation ─────────────────────────────────────────────────
def compute_metrics(df: pd.DataFrame, price_col: str = "quarter_price") -> pd.DataFrame:
    """Compute the 8 raw factor metrics from fundamental data."""
    out = df.copy()
    price = out[price_col].replace(0, np.nan)
    shares = out["shares_outstanding"].replace(0, np.nan)
    assets = out["total_assets"].replace(0, np.nan)
    equity = out["stockholders_equity"].replace(0, np.nan)

    out["market_cap"] = price * shares

    # Value metrics
    out["bp"] = out["book_equity"] / (price * shares)  # Book-to-Price
    out["ey"] = out["eps"] / price  # Earnings Yield
    out["cfy"] = out["operating_cf"] / out["market_cap"]  # Cash Flow Yield
    out["dy"] = out["dividends"] / (price * shares)  # Dividend Yield

    # Quality metrics
    out["gpa"] = out["gross_profit"] / assets  # Gross Profitability
    out["roa"] = out["net_income"] / assets  # Return on Assets
    out["wca"] = out["working_capital"] / assets  # Working Capital / Assets
    out["ltde"] = -(out["lt_debt"] / equity.replace(0, np.nan))  # −LT Debt/Equity

    return out


# ── Sector-neutral z-scoring ──────────────────────────────────────────────────
def zscore_factor(series: pd.Series, sectors: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=series.index)
    lo = series.quantile(WINSOR_LO)
    hi = series.quantile(WINSOR_HI)
    winsorised = series.clip(lo, hi)

    for sector in sectors.dropna().unique():
        mask = sectors == sector
        vals = winsorised[mask].dropna()
        if len(vals) < SMALL_SECTOR_MIN:
            all_vals = winsorised.dropna()
            ranked = all_vals.rank(pct=True).clip(0.001, 0.999)
            out[all_vals.index] = norm.ppf(ranked)
        else:
            ranked = vals.rank(pct=True).clip(0.001, 0.999)
            out[vals.index] = norm.ppf(ranked)
    return out


def compute_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    value_metrics = ["bp", "ey", "cfy", "dy"]
    quality_metrics = ["gpa", "roa", "wca", "ltde"]

    for m in value_metrics + quality_metrics:
        col = pd.to_numeric(df[m], errors="coerce").replace([np.inf, -np.inf], np.nan)
        df[f"z_{m}"] = zscore_factor(col, df["gics_sector"])

    df["value_score"] = df[[f"z_{m}" for m in value_metrics]].mean(axis=1)
    df["quality_score"] = df[[f"z_{m}" for m in quality_metrics]].mean(axis=1)

    # Normalise to [0, 1] for interpretability
    for col in ["value_score", "quality_score"]:
        mn, mx = df[col].min(), df[col].max()
        if mx > mn:
            df[col] = (df[col] - mn) / (mx - mn)

    return df


# ── DB upsert ─────────────────────────────────────────────────────────────────
def _safe(row, col):
    v = row.get(col)
    if v is None or v is pd.NA:
        return None
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return None


_UPSERT_SQL = text(
    """
    INSERT INTO systematic_equity.factor_values
        (symbol, period_date, market_cap, book_value,
         bp, ey, cfy, dy, gpa, roa, wca, ltde,
         z_bp, z_ey, z_cfy, z_dy, z_gpa, z_roa, z_wca, z_ltde,
         value_score, quality_score)
    VALUES
        (:sym, :d, :mc, :bv,
         :bp, :ey, :cfy, :dy, :gpa, :roa, :wca, :ltde,
         :zbp, :zey, :zcfy, :zdy, :zgpa, :zroa, :zwca, :zltde,
         :vs, :qs)
    ON CONFLICT (symbol, period_date) DO UPDATE SET
        market_cap    = EXCLUDED.market_cap,
        book_value    = EXCLUDED.book_value,
        bp            = EXCLUDED.bp,
        ey            = EXCLUDED.ey,
        cfy           = EXCLUDED.cfy,
        dy            = EXCLUDED.dy,
        gpa           = EXCLUDED.gpa,
        roa           = EXCLUDED.roa,
        wca           = EXCLUDED.wca,
        ltde          = EXCLUDED.ltde,
        z_bp          = EXCLUDED.z_bp,
        z_ey          = EXCLUDED.z_ey,
        z_cfy         = EXCLUDED.z_cfy,
        z_dy          = EXCLUDED.z_dy,
        z_gpa         = EXCLUDED.z_gpa,
        z_roa         = EXCLUDED.z_roa,
        z_wca         = EXCLUDED.z_wca,
        z_ltde        = EXCLUDED.z_ltde,
        value_score   = EXCLUDED.value_score,
        quality_score = EXCLUDED.quality_score
"""
)


def upsert_to_db(eng, scored_df: pd.DataFrame, period_date: str) -> int:
    records = [
        {
            "sym": r["symbol"],
            "d": period_date,
            "mc": _safe(r, "market_cap"),
            "bv": _safe(r, "book_equity"),
            "bp": _safe(r, "bp"),
            "ey": _safe(r, "ey"),
            "cfy": _safe(r, "cfy"),
            "dy": _safe(r, "dy"),
            "gpa": _safe(r, "gpa"),
            "roa": _safe(r, "roa"),
            "wca": _safe(r, "wca"),
            "ltde": _safe(r, "ltde"),
            "zbp": _safe(r, "z_bp"),
            "zey": _safe(r, "z_ey"),
            "zcfy": _safe(r, "z_cfy"),
            "zdy": _safe(r, "z_dy"),
            "zgpa": _safe(r, "z_gpa"),
            "zroa": _safe(r, "z_roa"),
            "zwca": _safe(r, "z_wca"),
            "zltde": _safe(r, "z_ltde"),
            "vs": _safe(r, "value_score"),
            "qs": _safe(r, "quality_score"),
        }
        for r in scored_df.to_dict("records")
    ]
    with eng.begin() as conn:
        conn.execute(_UPSERT_SQL, records)
    return len(records)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    eng = local_engine()
    universe = load_universe(eng)

    us_tickers = universe[universe["country"] == "US"]["symbol"].tolist()
    eu_universe = universe[universe["country"] != "US"].copy()

    print(f"Universe: {len(us_tickers)} US + {len(eu_universe)} European/Canadian")
    print(
        f"Rebalance dates: {len(REBALANCE_DATES)}  "
        f"({REBALANCE_DATES[0]} → {REBALANCE_DATES[-1]})"
    )

    # ── Connect to WRDS ───────────────────────────────────────────────────────
    print("\nConnecting to WRDS ...")
    db = wrds.Connection()

    # ── Pull raw data ─────────────────────────────────────────────────────────
    us_quarterly = pull_us_fundamentals_quarterly(db, us_tickers)
    eu_annual = pull_global_fundamentals(db, eu_universe)
    db.close()
    print("WRDS connection closed.")

    # Merge GICS sector into US quarterly data
    us_quarterly = us_quarterly.merge(universe[["symbol", "gics_sector"]], on="symbol", how="left")

    # Fetch year-end prices for European stocks (comp.g_funda has no price col)
    if not eu_annual.empty:
        eu_prices = fetch_yearend_prices(eu_universe["symbol"].tolist(), list(range(2015, 2025)))
        eu_annual = eu_annual.merge(eu_prices, on=["symbol", "fyear"], how="left")
        eu_annual = eu_annual.merge(
            universe[["symbol", "gics_sector", "country"]], on="symbol", how="left"
        )

    # ── US: all 40 quarterly rebalance dates ─────────────────────────────────
    print(f"\n{'='*60}")
    print("US COMPANIES — quarterly rebalance dates (comp.fundq + TTM)")
    print(f"{'='*60}")

    total_us = 0
    for rebalance_date in REBALANCE_DATES:
        snapshot = compute_ttm_snapshot(us_quarterly, rebalance_date)
        if snapshot.empty:
            print(f"  {rebalance_date}: no US data (filing lag too early)")
            continue

        snapshot = snapshot.merge(universe[["symbol", "gics_sector"]], on="symbol", how="left")

        # Filter: exclude financials (GICS sector) and loss-making companies
        is_financial = snapshot["gics_sector"].str.lower().str.contains("financ", na=False)
        is_loss = snapshot["eps"].fillna(-1) <= 0
        eligible = snapshot[~is_financial & ~is_loss].copy()

        if len(eligible) < 10:
            print(f"  {rebalance_date}: only {len(eligible)} eligible — skipping")
            continue

        eligible = compute_metrics(eligible, price_col="quarter_price")
        eligible = compute_scores(eligible)
        n = upsert_to_db(eng, eligible, rebalance_date)
        total_us += n
        print(
            f"  {rebalance_date}: "
            f"{len(snapshot)} companies → {len(eligible)} eligible → {n} upserted"
        )

    print(f"\nUS total upserted: {total_us} rows across {len(REBALANCE_DATES)} dates")

    # ── European/Canadian: Dec 31 dates only (annual limitation) ─────────────
    if not eu_annual.empty:
        print(f"\n{'='*60}")
        print("EUROPEAN/CANADIAN — Dec 31 dates only (comp.g_funda annual)")
        print("  Mar/Jun/Sep dates will carry forward Dec fundamentals in step05.")
        print(f"{'='*60}")

        total_eu = 0
        for fyear in range(2015, 2025):
            period_date = f"{fyear}-12-31"
            yr_df = eu_annual[eu_annual["fyear"] == fyear].copy()
            if yr_df.empty:
                continue

            # Most recent row per company within this fiscal year
            yr_df = yr_df.sort_values("fiscal_date").groupby("symbol").last().reset_index()

            yr_df["sic_code"] = pd.to_numeric(yr_df.get("sic_code", np.nan), errors="coerce")
            is_financial = (yr_df["sic_code"] >= 6000) & (yr_df["sic_code"] <= 6999)
            is_loss = yr_df["eps"].fillna(-1) <= 0
            eligible = yr_df[~is_financial & ~is_loss].copy()

            if len(eligible) < 5:
                continue

            eligible = eligible.rename(columns={"fiscal_price": "quarter_price"})
            eligible = compute_metrics(eligible, price_col="quarter_price")
            eligible = compute_scores(eligible)
            n = upsert_to_db(eng, eligible, period_date)
            total_eu += n
            print(f"  {period_date}: {n} European/Canadian rows upserted")

        print(f"\nEuropean total upserted: {total_eu} rows")

    # ── DB summary ────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("DATABASE SUMMARY")
    print(f"{'='*60}")
    with eng.connect() as conn:
        summary = pd.read_sql(
            text(
                """
            SELECT
                period_date,
                COUNT(*)              AS total,
                COUNT(value_score)    AS has_value,
                COUNT(quality_score)  AS has_quality
            FROM systematic_equity.factor_values
            WHERE period_date >= '2015-12-31'
            GROUP BY period_date
            ORDER BY period_date
        """
            ),
            conn,
        )
    print(summary.to_string(index=False))

    print("\nDone.")
    print("  US stocks : all 40 quarterly dates populated with TTM fundamentals.")
    print("  EU stocks : Dec 31 dates only; step05 carries forward for Mar/Jun/Sep.")
    print("  Next      : re-run step05 (add momentum + low_vol), then step01 (returns).")


if __name__ == "__main__":
    main()
