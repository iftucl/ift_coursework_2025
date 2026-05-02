"""Step 03 — IC Analysis and Performance Summary Table.

Reads from stock_returns_10year.csv (40 quarters, 2015–2025).

Produces:
  results/ic_analysis.csv          — Spearman IC per quarter
  results/charts/03_ic_per_period.png — IC bar chart (40 periods)

  Prints a full performance summary table to terminal for the report.

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step03_ic_analysis.py
"""

import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from _table_utils import save_table_png

warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
CHARTS = BASE / "results" / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

# ── Risk-free rate ────────────────────────────────────────────────────────────
# Period-varying 3-month T-bill yield (FRED DGS3MO) — see scripts/_rf_rates.py
from _rf_rates import rf_quarterly_series  # noqa: E402

STOCK_CSV = RESULTS / "stock_returns_10year.csv"
TC_RT = 0.004  # round-trip transaction cost


# ── Load ──────────────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:  # pragma: no cover
    df = pd.read_csv(STOCK_CSV)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df["net_return"] = df["gross_return"] - TC_RT
    df["quintile"] = pd.to_numeric(df["quintile"], errors="coerce")
    df = df.dropna(subset=["quintile"])
    df["quintile"] = df["quintile"].astype(int)
    print(
        f"  Loaded {len(df):,} stock-period rows across " f"{df['start_date'].nunique()} quarters"
    )
    return df


# ── IC Analysis ───────────────────────────────────────────────────────────────
def compute_ic(df: pd.DataFrame) -> pd.DataFrame:
    """Spearman IC between composite_score and next-quarter gross_return per period."""
    rows = []
    for s_date, grp in df.groupby("start_date"):
        grp = grp.dropna(subset=["composite_score", "gross_return"])
        if len(grp) < 10:
            continue
        ic, pval = stats.spearmanr(grp["composite_score"], grp["gross_return"])
        rows.append(
            {
                "start_date": s_date,
                "end_date": grp["end_date"].iloc[0],
                "ic": ic,
                "p_value": pval,
                "n_stocks": len(grp),
                "significant": pval < 0.05,
            }
        )
    ic_df = pd.DataFrame(rows).sort_values("start_date").reset_index(drop=True)
    ic_df.to_csv(RESULTS / "ic_analysis.csv", index=False)
    print(f"  Saved ic_analysis.csv ({len(ic_df)} periods)")
    return ic_df


# ── Chart 03 — IC per period ──────────────────────────────────────────────────
def chart_ic(ic_df: pd.DataFrame):  # pragma: no cover
    labels = [pd.Timestamp(d).strftime("%b'%y") for d in ic_df["start_date"]]
    colors = ["#2166ac" if v > 0 else "#d73027" for v in ic_df["ic"]]

    mean_ic = ic_df["ic"].mean()
    std_ic = ic_df["ic"].std(ddof=1)
    icir = mean_ic / std_ic if std_ic > 0 else np.nan
    hit_rate = (ic_df["ic"] > 0).mean()

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(range(len(ic_df)), ic_df["ic"] * 100, color=colors, edgecolor="white", width=0.7)
    ax.set_xticks(range(len(ic_df)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.axhline(0, color="black", linewidth=0.8)

    stats_text = (
        f"Mean IC: {mean_ic*100:.2f}%\n"
        f"IC IR:   {icir:.3f}\n"
        f"Hit Rate: {hit_rate*100:.1f}%  ({(ic_df['ic'] > 0).sum()}/{len(ic_df)})"
    )
    ax.text(
        0.02,
        0.97,
        stats_text,
        transform=ax.transAxes,
        va="top",
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.9),
    )

    ax.set_title(
        "Spearman Information Coefficient (IC) per Quarter — 40 Periods (Dec 2015 – Dec 2025)\n"
        "Blue = factor predicted returns correctly, Red = factor predicted incorrectly",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("IC (%)")
    fig.tight_layout()
    path = CHARTS / "03_ic_per_period.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path.name}")


# ── Performance Summary Table ─────────────────────────────────────────────────
def print_performance_table(df: pd.DataFrame, ic_df: pd.DataFrame):
    """Print quintile performance table for the report."""
    rows = []
    for q in range(1, 6):
        q_df = df[df["quintile"] == q]
        # Average net return per period (one observation per period = EW portfolio)
        period_net = q_df.groupby("start_date")["net_return"].mean()
        ann_ret = (1 + period_net.mean()) ** 4 - 1
        ann_vol = period_net.std(ddof=1) * np.sqrt(4)
        rf_q = rf_quarterly_series(period_net.index)
        excess = period_net.values - rf_q.values
        ann_excess = float(np.mean(excess)) * 4
        sharpe = ann_excess / ann_vol if ann_vol > 0 else np.nan
        # Sortino: downside deviation of excess returns below Rf, annualised
        downside = np.minimum(excess, 0)
        down_dev = np.sqrt(np.mean(downside**2)) * np.sqrt(4)
        sortino = ann_excess / down_dev if down_dev > 0 else np.nan
        hit_rate = (period_net > 0).mean()
        rows.append(
            {
                "quintile": q,
                "n_periods": len(period_net),
                "ann_ret_pct": ann_ret * 100,
                "ann_vol_pct": ann_vol * 100,
                "sharpe": sharpe,
                "sortino": sortino,
                "hit_rate_pct": hit_rate * 100,
            }
        )
    perf = pd.DataFrame(rows)

    q1 = perf[perf["quintile"] == 1].iloc[0]
    q5 = perf[perf["quintile"] == 5].iloc[0]
    spread = q1["ann_ret_pct"] - q5["ann_ret_pct"]

    mean_ic = ic_df["ic"].mean()
    std_ic = ic_df["ic"].std(ddof=1)
    icir = mean_ic / std_ic if std_ic > 0 else np.nan
    hit_ic = (ic_df["ic"] > 0).mean()

    print("\n" + "=" * 85)
    print("PERFORMANCE SUMMARY TABLE (for report)  — 40 quarters, Dec 2015–Dec 2025")
    print("=" * 85)
    print(
        f"\n{'Quintile':<10} {'Ann.Return%':>12} {'Ann.Vol%':>10} {'Sharpe':>8} {'Sortino':>8} {'HitRate%':>10}"
    )
    print("-" * 65)
    for _, row in perf.iterrows():
        print(
            f"  Q{int(row['quintile'])}      {row['ann_ret_pct']:>10.2f}%  "
            f"{row['ann_vol_pct']:>8.2f}%  {row['sharpe']:>8.3f}  "
            f"{row['sortino']:>8.3f}  {row['hit_rate_pct']:>8.1f}%"
        )
    print(f"  Q1-Q5    {spread:>10.2f}%")

    print("\nIC Analysis (Spearman, composite score vs. forward gross returns):")
    print(f"  Mean IC:   {mean_ic*100:.3f}%")
    print(f"  IC Std:    {std_ic*100:.3f}%")
    print(f"  IC IR:     {icir:.4f}")
    print(f"  Hit Rate:  {hit_ic*100:.1f}%  ({(ic_df['ic'] > 0).sum()}/{len(ic_df)} periods)")
    print(f"  Sig (p<.05): {ic_df['significant'].sum()}/{len(ic_df)} periods")
    print()


# ── Table PNGs ────────────────────────────────────────────────────────────────
def save_performance_table_png(df: pd.DataFrame, ic_df: pd.DataFrame):  # pragma: no cover
    """Quintile performance summary as PNG."""
    rows_data = []
    for q in range(1, 6):
        q_df = df[df["quintile"] == q]
        period_net = q_df.groupby("start_date")["net_return"].mean()
        ann_ret = (1 + period_net.mean()) ** 4 - 1
        ann_vol = period_net.std(ddof=1) * np.sqrt(4)
        rf_q = rf_quarterly_series(period_net.index)
        excess = period_net.values - rf_q.values
        ann_excess = float(np.mean(excess)) * 4
        sharpe = ann_excess / ann_vol if ann_vol > 0 else np.nan
        downside = np.minimum(excess, 0)
        down_dev = np.sqrt(np.mean(downside**2)) * np.sqrt(4)
        sortino = ann_excess / down_dev if down_dev > 0 else np.nan
        hit_rate = (period_net > 0).mean()
        rows_data.append(
            [
                f"Q{q}",
                f"{ann_ret*100:.2f}%",
                f"{ann_vol*100:.2f}%",
                f"{sharpe:.3f}",
                f"{sortino:.3f}",
                f"{hit_rate*100:.1f}%",
            ]
        )

    # Q1-Q5 spread row
    q1_net = df[df["quintile"] == 1].groupby("start_date")["net_return"].mean()
    q5_net = df[df["quintile"] == 5].groupby("start_date")["net_return"].mean()
    spread = ((1 + q1_net.mean()) ** 4 - 1) - ((1 + q5_net.mean()) ** 4 - 1)
    rows_data.append(["Q1 − Q5", f"{spread*100:.2f}%", "—", "—", "—", "—"])

    save_table_png(
        headers=["Quintile", "Ann. Return", "Ann. Vol", "Sharpe", "Sortino", "Hit Rate"],
        rows=rows_data,
        title="Quintile Performance Summary  (40 quarters, Dec 2015–Dec 2025)\n"
        "Net of 0.4% TC  |  Rf = 3mo T-bill",
        filepath=CHARTS / "03b_performance_summary_table.png",
        col_widths=[1.2, 1.5, 1.4, 1.2, 1.2, 1.2],
        highlight_rows=[0],  # Q1
        bold_rows=[0, 5],  # Q1 and spread
    )

    # IC summary table
    mean_ic = ic_df["ic"].mean()
    std_ic = ic_df["ic"].std(ddof=1)
    icir = mean_ic / std_ic if std_ic > 0 else np.nan
    hit_ic = (ic_df["ic"] > 0).mean()
    sig = ic_df["significant"].sum()

    ic_rows = [
        ["Mean IC", f"{mean_ic*100:.3f}%"],
        ["IC Std Dev", f"{std_ic*100:.3f}%"],
        ["IC IR (Mean/Std)", f"{icir:.4f}"],
        ["Hit Rate (IC > 0)", f"{hit_ic*100:.1f}%  ({(ic_df['ic'] > 0).sum()}/{len(ic_df)})"],
        ["Significant (p<.05)", f"{sig}/{len(ic_df)} periods"],
    ]
    save_table_png(
        headers=["Metric", "Value"],
        rows=ic_rows,
        title="IC Analysis — Spearman ρ(composite score, forward return)\n"
        "40 quarters, Dec 2015–Dec 2025",
        filepath=CHARTS / "03c_ic_summary_table.png",
        col_widths=[2.5, 1.8],
        figsize=(7, 4),
    )


# ── Main ──────────────────────────────────────────────────────────────────────
def main():  # pragma: no cover
    print("Step 03 — IC Analysis (40 quarters)")
    df = load_data()
    ic_df = compute_ic(df)
    chart_ic(ic_df)
    print_performance_table(df, ic_df)
    save_performance_table_png(df, ic_df)
    print(f"  Done. Charts saved to {CHARTS}/")


if __name__ == "__main__":
    main()
