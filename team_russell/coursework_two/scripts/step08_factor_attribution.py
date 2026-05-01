"""Step 08 — Factor Attribution Analysis.

Compares single-factor portfolios (Value-only, Quality-only, Momentum-only)
against the combined 3-Factor composite to answer the question:
"Does combining factors add value beyond any single factor alone?"

Methodology:
  For each quarterly period, stocks are ranked independently by each factor score.
  The top-quintile (top 20%) of each single-factor ranking forms a separate
  portfolio. Returns are computed equal-weighted, net of 0.4% transaction cost.
  Momentum score is derived from the composite: mom = (composite - 0.4V - 0.4Q) / 0.2

Window: Dec 2022 – Sep 2025 (12 quarters) — periods with full individual factor scores.

Outputs:
  results/factor_attribution.csv
  results/charts/08_factor_attribution_nav.png
  results/charts/09_factor_attribution_bar.png

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step12_factor_attribution.py
"""

import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

sys.path.insert(0, str(Path(__file__).parent))
from _table_utils import save_table_png

warnings.filterwarnings("ignore")

BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
CHARTS = RESULTS / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

TC_RT = 0.004

# Mean annualised 3-month T-bill yield (^IRX) over Dec 2015 – Dec 2025
from _rf_rates import rf_quarterly_series  # noqa: E402

sns.set_theme(style="whitegrid", font_scale=1.05)

# ── Config ────────────────────────────────────────────────────────────────────
PORTFOLIOS = {
    "Value Only": dict(color="#d73027", lw=1.8, ls="--"),
    "Quality Only": dict(color="#f97d20", lw=1.8, ls="--"),
    "Momentum Only": dict(color="#4dac26", lw=1.8, ls="--"),
    "3F Composite": dict(color="#2166ac", lw=2.8, ls="-"),
    "EW Universe": dict(color="#555555", lw=1.5, ls=":"),
}


# ── Load and prepare data ─────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:  # pragma: no cover
    df = pd.read_csv(RESULTS / "stock_returns_10year.csv")
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])

    # Keep only periods with complete individual factor scores
    has_scores = (
        df["value_score"].notna()
        & df["quality_score"].notna()
        & df["composite_score"].notna()
        & df["momentum_score"].notna()
    )
    df = df[has_scores].copy()

    print(
        f"Loaded {len(df):,} stock-period observations across "
        f"{df['start_date'].nunique()} periods"
    )
    return df


# ── Assign single-factor quintiles per period ─────────────────────────────────
def assign_single_factor_quintiles(df: pd.DataFrame) -> pd.DataFrame:
    """For each period, rank stocks by each individual factor and assign quintile 1-5."""
    results = []
    for (s, e), grp in df.groupby(["start_date", "end_date"]):
        g = grp.copy()
        for factor, col in [
            ("value_score", "value_quintile"),
            ("quality_score", "quality_quintile"),
            ("momentum_score", "momentum_quintile"),
        ]:
            valid = g[factor].notna()
            n = valid.sum()
            if n < 10:
                g[col] = np.nan
                continue
            # Rank descending (highest score = rank 1 = best)
            ranks = g.loc[valid, factor].rank(ascending=False, method="first")
            q_size = n / 5
            g.loc[valid, col] = np.ceil(ranks / q_size).clip(1, 5).astype(int)
        results.append(g)
    return pd.concat(results, ignore_index=True)


# ── Compute portfolio returns per period ──────────────────────────────────────
def compute_portfolio_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Equal-weighted Q1 return per period for each single-factor + composite + EW."""
    rows = []
    for (s, e), grp in df.groupby(["start_date", "end_date"]):
        row = {"start_date": s, "end_date": e}

        # Single-factor Q1 portfolios
        for name, col in [
            ("Value Only", "value_quintile"),
            ("Quality Only", "quality_quintile"),
            ("Momentum Only", "momentum_quintile"),
        ]:
            q1 = grp[grp[col] == 1]
            row[name] = q1["gross_return"].mean() - TC_RT if len(q1) >= 5 else np.nan

        # 3F Composite Q1 (uses the pre-assigned quintile column)
        q1c = grp[grp["quintile"] == 1]
        row["3F Composite"] = q1c["gross_return"].mean() - TC_RT if len(q1c) >= 5 else np.nan

        # EW Universe
        row["EW Universe"] = grp["gross_return"].mean() - TC_RT

        rows.append(row)
    return pd.DataFrame(rows).sort_values("start_date").reset_index(drop=True)


# ── Summary statistics ────────────────────────────────────────────────────────
def compute_stats(port_df: pd.DataFrame) -> pd.DataFrame:
    stats = []
    for name in PORTFOLIOS:
        mask = port_df[name].notna()
        series = port_df.loc[mask, name]
        start_dates = port_df.loc[mask, "start_date"]
        n = len(series)
        mean_q = series.mean()
        std_q = series.std(ddof=1)
        ann = (1 + mean_q) ** 4 - 1
        vol = std_q * np.sqrt(4)
        rf_q = rf_quarterly_series(start_dates)
        excess = series.values - rf_q.values
        ann_excess = float(np.mean(excess)) * 4
        sharpe = ann_excess / vol if vol > 0 else np.nan
        downside = np.minimum(excess, 0)
        down_dev = np.sqrt(np.mean(downside**2)) * np.sqrt(4) if np.any(downside < 0) else 0.0
        sortino = ann_excess / down_dev if down_dev > 0 else np.nan
        cum = (1 + series).prod() - 1
        hit = (series > 0).mean()
        stats.append(
            {
                "Portfolio": name,
                "N Periods": n,
                "Ann. Net Ret (%)": round(ann * 100, 2),
                "Ann. Vol (%)": round(vol * 100, 2),
                "Sharpe": round(sharpe, 3),
                "Sortino": round(sortino, 3),
                "Cumulative (%)": round(cum * 100, 1),
                "Hit Rate (%)": round(hit * 100, 1),
            }
        )
    return pd.DataFrame(stats)


# ── Chart 1: Cumulative NAV ───────────────────────────────────────────────────
def chart_nav(
    port_df: pd.DataFrame, n_periods: int, start_yr: str, end_yr: str
):  # pragma: no cover
    fig, ax = plt.subplots(figsize=(13, 6))

    for name, style in PORTFOLIOS.items():
        series = port_df[name].dropna()
        dates = [port_df.loc[series.index[0], "start_date"]] + list(
            port_df.loc[series.index, "end_date"]
        )
        nav = np.insert((1 + series).cumprod().values, 0, 1.0) * 100
        ax.plot(
            dates,
            nav,
            label=name,
            color=style["color"],
            linewidth=style["lw"],
            linestyle=style["ls"],
        )
        # Annotate final value
        ax.annotate(
            f"{nav[-1]:.0f}",
            xy=(dates[-1], nav[-1]),
            xytext=(5, 0),
            textcoords="offset points",
            fontsize=8.5,
            color=style["color"],
            fontweight="bold",
            va="center",
        )

    ax.axhline(100, color="grey", linewidth=0.5, linestyle="--")

    # Shade 2022 bear (partially captured in this window)
    ax.axvspan(pd.Timestamp("2022-12-31"), pd.Timestamp("2023-03-31"), alpha=0.07, color="#d73027")
    ax.text(
        pd.Timestamp("2023-01-15"),
        101,
        "2022 bear\nend",
        fontsize=7,
        color="#b2182b",
        ha="center",
        style="italic",
    )

    ax.set_title(
        "Factor Attribution: Single-Factor vs 3F Composite (base=100)\n"
        f"Net of 0.4% TC  |  {start_yr} – {end_yr}  |  {n_periods} quarters  |  Equal-weighted Q1",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("NAV (base 100)")
    ax.legend(loc="upper left", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    fig.tight_layout()

    out = CHARTS / "08_factor_attribution_nav.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ── Chart 2: Per-period bar comparison ───────────────────────────────────────
def chart_period_bars(port_df: pd.DataFrame):  # pragma: no cover
    port_names = ["Value Only", "Quality Only", "Momentum Only", "3F Composite"]
    colors = [PORTFOLIOS[p]["color"] for p in port_names]
    labels = port_df["start_date"].dt.strftime("%b'%y").tolist()
    x = np.arange(len(port_df))
    w = 0.18

    fig, ax = plt.subplots(figsize=(14, 6))
    for i, (name, col) in enumerate(zip(port_names, colors)):
        ax.bar(
            x + (i - 1.5) * w,
            port_df[name] * 100,
            width=w,
            label=name,
            color=col,
            alpha=0.85,
            edgecolor="white",
            linewidth=0.4,
        )

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
    ax.set_ylabel("Net Return per Quarter (%)")
    ax.set_title(
        "Factor Attribution: Net Return per Quarter by Portfolio\n"
        "Value vs Quality vs Momentum vs 3F Composite",
        fontsize=12,
        fontweight="bold",
    )
    ax.legend(loc="upper right", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    fig.tight_layout()

    out = CHARTS / "09_factor_attribution_bar.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():  # pragma: no cover
    print("Loading data...")
    df = load_data()

    print("Assigning single-factor quintiles...")
    df = assign_single_factor_quintiles(df)

    print("Computing portfolio returns...")
    port_df = compute_portfolio_returns(df)

    print("Computing summary statistics...")
    stats = compute_stats(port_df)

    out_csv = RESULTS / "factor_attribution.csv"
    port_df.to_csv(out_csv, index=False)
    print(f"  Saved {out_csv.name} ({len(port_df)} rows)")

    n_periods = len(port_df)
    start_yr = port_df["start_date"].iloc[0].strftime("%b %Y")
    end_yr = port_df["end_date"].iloc[-1].strftime("%b %Y")

    print("\nGenerating charts...")
    chart_nav(port_df, n_periods, start_yr, end_yr)
    chart_period_bars(port_df)

    print("\n" + "=" * 65)
    print(f"FACTOR ATTRIBUTION RESULTS  ({n_periods} quarters, {start_yr} – {end_yr})")
    print("=" * 65)
    print(stats.to_string(index=False))

    # Key insight: does composite beat all single factors?
    composite_sharpe = stats.loc[stats["Portfolio"] == "3F Composite", "Sharpe"].values[0]
    best_single = stats[stats["Portfolio"].isin(["Value Only", "Quality Only", "Momentum Only"])]
    best_single_name = best_single.loc[best_single["Sharpe"].idxmax(), "Portfolio"]
    best_single_sharpe = best_single["Sharpe"].max()
    improvement = composite_sharpe - best_single_sharpe

    print("\nKey finding:")
    print(f"  3F Composite Sharpe:          {composite_sharpe:.3f}")
    print(f"  Best single factor ({best_single_name[:7]}): {best_single_sharpe:.3f}")
    print(f"  Diversification benefit:      {improvement:+.3f}")

    # ── Table PNG ─────────────────────────────────────────────────────────────
    print("\nGenerating table PNG...")
    composite_idx = stats.index[stats["Portfolio"] == "3F Composite"].tolist()
    table_rows = [
        [
            row["Portfolio"],
            str(row["N Periods"]),
            f"{row['Ann. Net Ret (%)']:.2f}%",
            f"{row['Ann. Vol (%)']:.2f}%",
            f"{row['Sharpe']:.3f}",
            f"{row['Sortino']:.3f}",
            f"{row['Cumulative (%)']:.1f}%",
            f"{row['Hit Rate (%)']:.1f}%",
        ]
        for _, row in stats.iterrows()
    ]
    save_table_png(
        headers=[
            "Portfolio",
            "N Periods",
            "Ann. Net Ret",
            "Ann. Vol",
            "Sharpe",
            "Sortino",
            "Cumulative",
            "Hit Rate",
        ],
        rows=table_rows,
        title=f"Factor Attribution: Single-Factor vs 3F Composite\n"
        f"{n_periods} quarters, {start_yr} – {end_yr}  |  Equal-weighted Q1  |  "
        f"Net of 0.4% TC  |  Diversification benefit: {improvement:+.3f} Sharpe",
        filepath=CHARTS / "08b_factor_attribution_table.png",
        col_widths=[2.2, 1.2, 1.6, 1.4, 1.2, 1.2, 1.5, 1.2],
        highlight_rows=[composite_idx[0] if composite_idx else 3],
        bold_rows=[composite_idx[0] if composite_idx else 3],
        figsize=(13, 5),
    )


if __name__ == "__main__":
    main()
