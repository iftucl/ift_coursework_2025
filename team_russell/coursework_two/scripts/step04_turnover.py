"""Step 04 — Turnover and Sector Diversification Analysis.

Reads directly from the 40-quarter dataset (stock_returns_10year.csv).
No PostgreSQL dependency for the main computation.

Computes:
  1. Q1 turnover per rebalance transition across all 40 quarters
  2. Average sector active weights (Q1 vs universe) — requires one DB
     lookup for symbol → GICS sector mapping.

Outputs:
  results/turnover.csv
  results/sector_weights.csv
  results/charts/06_turnover_per_period.png
  results/charts/07_sector_active_weights.png

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step04_turnover.py
"""

import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import seaborn as sns
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent))
from _table_utils import save_table_png

warnings.filterwarnings("ignore")
sns.set_theme(style="whitegrid", palette="muted", font_scale=1.05)

PG = dict(host="localhost", port=5439, user="postgres", password="postgres", database="fift")

BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
CHARTS = RESULTS / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

TC_RT = 0.004


# ── Load data ─────────────────────────────────────────────────────────────────
def load_returns() -> pd.DataFrame:  # pragma: no cover
    """Load the full 40-quarter stock-level dataset."""
    df = pd.read_csv(RESULTS / "stock_returns_10year.csv")
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df["quintile"] = pd.to_numeric(df["quintile"], errors="coerce")
    return df.dropna(subset=["quintile"])


def load_sector_map() -> dict:  # pragma: no cover
    """One-time DB lookup: symbol → GICS sector."""
    try:
        engine = create_engine(
            f"postgresql+psycopg2://{PG['user']}:{PG['password']}"
            f"@{PG['host']}:{PG['port']}/{PG['database']}"
        )
        with engine.connect() as conn:
            df = pd.read_sql(
                text(
                    """
                SELECT TRIM(symbol) AS symbol, gics_sector
                FROM systematic_equity.company_static
                WHERE gics_sector IS NOT NULL
            """
                ),
                conn,
            )
        return dict(zip(df["symbol"], df["gics_sector"]))
    except Exception as e:
        print(f"  Warning: could not load sector map from DB ({e}). Sector analysis skipped.")
        return {}


# ── Turnover ──────────────────────────────────────────────────────────────────
def compute_turnover(df: pd.DataFrame) -> pd.DataFrame:
    """Q1 turnover rate at each consecutive rebalance transition."""
    dates = sorted(df["start_date"].unique())
    rows = []
    for i in range(len(dates) - 1):
        d_from = dates[i]
        d_to = dates[i + 1]
        q1_from = set(df[(df["start_date"] == d_from) & (df["quintile"] == 1)]["symbol"])
        q1_to = set(df[(df["start_date"] == d_to) & (df["quintile"] == 1)]["symbol"])
        exits = q1_from - q1_to
        entries = q1_to - q1_from
        stays = q1_from & q1_to
        avg_sz = (len(q1_from) + len(q1_to)) / 2
        to_rate = (len(exits) + len(entries)) / (2 * avg_sz) * 100 if avg_sz > 0 else 0
        rows.append(
            {
                "from_date": d_from,
                "to_date": d_to,
                "q1_size_from": len(q1_from),
                "q1_size_to": len(q1_to),
                "exits": len(exits),
                "entries": len(entries),
                "stays": len(stays),
                "turnover_rate": round(to_rate, 1),
            }
        )
    return pd.DataFrame(rows)


# ── Sector weights ────────────────────────────────────────────────────────────
def compute_sector_weights(df: pd.DataFrame, sector_map: dict) -> pd.DataFrame:
    """Q1 vs universe sector weights per period."""
    if not sector_map:
        return pd.DataFrame()
    df = df.copy()
    df["gics_sector"] = df["symbol"].map(sector_map).fillna("Unknown")
    rows = []
    for d in sorted(df["start_date"].unique()):
        period = df[df["start_date"] == d]
        q1 = period[period["quintile"] == 1]
        total_u = len(period)
        total_q1 = len(q1)
        if total_q1 == 0:
            continue
        for sector in period["gics_sector"].unique():
            if sector == "Unknown":
                continue
            w_u = (period["gics_sector"] == sector).sum() / total_u
            w_q1 = (q1["gics_sector"] == sector).sum() / total_q1
            rows.append(
                {
                    "period_date": d,
                    "sector": sector,
                    "w_universe": round(w_u * 100, 2),
                    "w_q1": round(w_q1 * 100, 2),
                    "active_weight": round((w_q1 - w_u) * 100, 2),
                }
            )
    return pd.DataFrame(rows)


# ── Charts ────────────────────────────────────────────────────────────────────
def chart_turnover(to_df: pd.DataFrame):  # pragma: no cover
    labels = [r.from_date.strftime("%b'%y") for r in to_df.itertuples()]
    avg = to_df["turnover_rate"].mean()

    fig, ax = plt.subplots(figsize=(14, 5))
    bars = ax.bar(
        range(len(to_df)),
        to_df["turnover_rate"],
        color="#2166ac",
        edgecolor="white",
        linewidth=0.6,
        alpha=0.85,
    )
    ax.axhline(avg, color="#d73027", linewidth=1.5, linestyle="--", label=f"Average: {avg:.1f}%")
    for bar, val in zip(bars, to_df["turnover_rate"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.4,
            f"{val:.0f}%",
            ha="center",
            va="bottom",
            fontsize=7,
        )
    ax.set_xticks(range(len(to_df)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Q1 Turnover Rate (%)")
    ax.set_title(
        f"Q1 Portfolio Turnover per Rebalance Period — 40 Quarters (Dec 2015 – Dec 2025)\n"
        f"Avg {avg:.1f}%/quarter  |  Turnover = (entries + exits) / (2 × avg Q1 size)",
        fontsize=12,
        fontweight="bold",
    )
    ax.legend()
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    fig.tight_layout()
    out = CHARTS / "06_turnover_per_period.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out.name}")


def chart_sector_weights(sec_df: pd.DataFrame):  # pragma: no cover
    if sec_df.empty:
        return
    avg = sec_df.groupby("sector")["active_weight"].mean().sort_values(ascending=False)
    colors = ["#2166ac" if v >= 0 else "#d73027" for v in avg]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(range(len(avg)), avg.values, color=colors, edgecolor="white", linewidth=0.6, alpha=0.85)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(range(len(avg)))
    ax.set_xticklabels(avg.index, rotation=35, ha="right", fontsize=9)
    ax.set_ylabel("Active Weight vs Universe (%)")
    ax.set_title(
        "Average Active Sector Weights: Q1 vs Equal-Weighted Universe\n"
        "Blue = overweight, Red = underweight  |  Averaged across 40 quarters",
        fontsize=12,
        fontweight="bold",
    )
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    fig.tight_layout()
    out = CHARTS / "07_sector_active_weights.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():  # pragma: no cover
    print("Loading 40-quarter dataset...")
    df = load_returns()
    n_periods = df["start_date"].nunique()
    print(f"  {len(df):,} stock-period rows across {n_periods} rebalance dates")

    # ── Turnover ──────────────────────────────────────────────────────────────
    print("\nComputing Q1 turnover...")
    to_df = compute_turnover(df)
    to_df.to_csv(RESULTS / "turnover.csv", index=False)

    avg_to = to_df["turnover_rate"].mean()
    min_to = to_df["turnover_rate"].min()
    max_to = to_df["turnover_rate"].max()
    ann_to = (1 - (1 - avg_to / 100) ** 4) * 100

    print(f"\n{'='*65}")
    print("Q1 TURNOVER ANALYSIS  (40 quarters, Dec 2015 – Dec 2025)")
    print(f"{'='*65}")
    print(f"\n{'Transition':<32} {'Exits':>5} {'Entries':>7} {'Stays':>6} {'Turnover':>9}")
    print("-" * 62)
    for r in to_df.itertuples():
        label = f"{r.from_date.strftime('%Y-%m-%d')} → {r.to_date.strftime('%Y-%m-%d')}"
        print(
            f"  {label:<30} {r.exits:>4}   {r.entries:>5}   {r.stays:>5}   {r.turnover_rate:>7.1f}%"
        )

    print(f"\n  Average quarterly turnover: {avg_to:.1f}%")
    print(f"  Min / Max:                  {min_to:.1f}% / {max_to:.1f}%")
    print(f"  Implied annual turnover:    ~{ann_to:.0f}%")

    # ── Sector analysis ───────────────────────────────────────────────────────
    print("\nLoading sector map from DB...")
    sector_map = load_sector_map()
    if sector_map:
        print(f"  {len(sector_map)} symbols mapped")
        sec_df = compute_sector_weights(df, sector_map)
        sec_df.to_csv(RESULTS / "sector_weights.csv", index=False)

        avg_active = sec_df.groupby("sector")["active_weight"].mean().sort_values(ascending=False)
        print(f"\n{'='*65}")
        print("AVERAGE SECTOR ACTIVE WEIGHTS (Q1 vs Universe, 40 quarters)")
        print(f"{'='*65}")
        print(f"\n{'Sector':<35} {'Avg Q1':>8} {'Avg Univ':>9} {'Active':>8}")
        print("-" * 62)
        for sector in avg_active.index:
            s = sec_df[sec_df["sector"] == sector]
            wq1 = s["w_q1"].mean()
            wu = s["w_universe"].mean()
            wa = avg_active[sector]
            flag = "  << LARGE" if abs(wa) > 3 else ""
            print(f"  {sector:<33} {wq1:>7.1f}%  {wu:>8.1f}%  {wa:>7.1f}%{flag}")

    # ── Charts ────────────────────────────────────────────────────────────────
    print("\nGenerating charts...")
    chart_turnover(to_df)
    if sector_map:
        chart_sector_weights(sec_df)

    # ── Table PNGs ────────────────────────────────────────────────────────────
    print("Generating table PNGs...")

    # Turnover per-period table
    to_rows = [
        [
            f"{r.from_date.strftime('%Y-%m-%d')} → {r.to_date.strftime('%Y-%m-%d')}",
            str(r.exits),
            str(r.entries),
            str(r.stays),
            f"{r.turnover_rate:.1f}%",
        ]
        for r in to_df.itertuples()
    ]
    save_table_png(
        headers=["Transition", "Exits", "Entries", "Stays", "Turnover"],
        rows=to_rows,
        title=f"Q1 Turnover per Rebalance — 39 transitions\n"
        f"Avg {avg_to:.1f}%/qtr  |  Implied annual ~{ann_to:.0f}%  |  "
        f"Min {min_to:.1f}%  Max {max_to:.1f}%",
        filepath=CHARTS / "06b_turnover_table.png",
        col_widths=[3.5, 1, 1, 1, 1.2],
        figsize=(11, 14),
        fontsize=8,
    )

    # Sector active weights table
    if sector_map:
        sec_rows = []
        for sector in avg_active.index:
            s = sec_df[sec_df["sector"] == sector]
            wq1 = s["w_q1"].mean()
            wu = s["w_universe"].mean()
            wa = avg_active[sector]
            flag = "Large" if abs(wa) > 3 else ""
            sec_rows.append([sector, f"{wq1:.1f}%", f"{wu:.1f}%", f"{wa:+.1f}%", flag])
        large_idx = [i for i, r in enumerate(sec_rows) if r[4] == "Large"]
        save_table_png(
            headers=["Sector", "Avg Q1 Wt", "Avg Universe Wt", "Active Wt", "Flag"],
            rows=sec_rows,
            title="Average Sector Active Weights: Q1 vs EW Universe\n"
            "Averaged across 40 quarters  |  Positive = overweight in Q1",
            filepath=CHARTS / "07b_sector_weights_table.png",
            col_widths=[3.5, 1.4, 1.8, 1.4, 1],
            highlight_rows=large_idx,
            figsize=(11, 6),
        )

    print("\nSaved: turnover.csv, sector_weights.csv")


if __name__ == "__main__":
    main()
