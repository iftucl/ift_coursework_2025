"""Step 07 — Final Chart Generation.

Regenerates the primary presentation charts from saved CSV data.
Run this after step05 to fix or refresh charts without re-running the full pipeline.

Charts produced:
  01_10year_nav.png            — 10-year quintile NAV + Q1-Q5 spread bar (primary result)
  02_q1_vs_q5.png              — Clean Q1 vs Q5 comparison with all quintiles overlaid
  07c_q1_annual_returns_table.png — Long-only Q1 annual return table (2016–2025)

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step07_final_charts.py
"""

import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

warnings.filterwarnings("ignore")

BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
CHARTS = RESULTS / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

TC_RT = 0.004
COLORS = {1: "#2166ac", 2: "#74add1", 3: "#a6a6a6", 4: "#f4a582", 5: "#d73027"}
LABELS = {1: "Q1 (Top 20%)", 2: "Q2", 3: "Q3 (Middle)", 4: "Q4", 5: "Q5 (Bottom 20%)"}
LW = {1: 2.5, 2: 1.2, 3: 1.2, 4: 1.2, 5: 2.5}

sns.set_theme(style="whitegrid", font_scale=1.05)


# ── Helpers ───────────────────────────────────────────────────────────────────
def load_returns() -> pd.DataFrame:  # pragma: no cover
    df = pd.read_csv(RESULTS / "stock_returns_10year.csv")
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df["quintile"] = pd.to_numeric(df["quintile"], errors="coerce")
    return df


def make_nav(df: pd.DataFrame, quintile: int):
    """Average across stocks per period first, then compound. Avoids overflow."""
    qd = (
        df[df["quintile"] == quintile]
        .groupby(["start_date", "end_date"])["gross_return"]
        .mean()
        .reset_index()
        .sort_values("start_date")
    )
    qd["net_return"] = qd["gross_return"] - TC_RT
    nav = np.insert((1 + qd["net_return"]).cumprod().values, 0, 1.0) * 100
    dates = [qd["start_date"].iloc[0]] + list(qd["end_date"])
    return dates, nav


def shade_regimes(ax):
    regimes = [
        (pd.Timestamp("2018-01-01"), pd.Timestamp("2018-12-31"), "#d73027", "2018\ncorrection"),
        (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"), "#f97d20", "COVID\ncrash"),
        (pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31"), "#d73027", "2022\nbear"),
    ]
    for x0, x1, col, label in regimes:
        ax.axvspan(x0, x1, alpha=0.08, color=col)
        ax.text(
            x0 + (x1 - x0) / 2,
            108,
            label,
            fontsize=7.5,
            color="#b2182b",
            ha="center",
            va="bottom",
            style="italic",
        )


# ── Chart 23: 10-Year NAV + Spread ───────────────────────────────────────────
def chart_10year_nav(df: pd.DataFrame):  # pragma: no cover
    fig, axes = plt.subplots(2, 1, figsize=(13, 10))

    # ── Top: cumulative NAV ──
    ax = axes[0]
    for q in range(1, 6):
        dates, nav = make_nav(df, q)
        ax.plot(dates, nav, label=LABELS[q], color=COLORS[q], linewidth=LW[q])

    bm = (
        df.groupby(["start_date", "end_date"])["gross_return"]
        .mean()
        .reset_index()
        .sort_values("start_date")
    )
    bm_nav = np.insert((1 + bm["gross_return"] - TC_RT).cumprod().values, 0, 1.0) * 100
    bm_dates = [bm["start_date"].iloc[0]] + list(bm["end_date"])
    ax.plot(bm_dates, bm_nav, label="EW Benchmark", color="black", linewidth=1.5, linestyle="--")

    shade_regimes(ax)
    ax.axhline(100, color="grey", linewidth=0.5, linestyle="--")

    for q in [1, 5]:
        dates_q, nav_q = make_nav(df, q)
        ax.annotate(
            f"Q{q}: {nav_q[-1]:.0f}",
            xy=(dates_q[-1], nav_q[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            fontsize=9,
            color=COLORS[q],
            fontweight="bold",
            va="center",
        )

    ax.set_title(
        "3-Factor Model: 10-Year Backtest NAV by Quintile (2016–2025)\n"
        "40% Value + 40% Quality + 20% Momentum  |  Net of 0.4% TC  |  base = 100",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("NAV (base 100)")
    ax.legend(loc="upper left", fontsize=9, ncol=2)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    # ── Bottom: Q1-Q5 spread per quarter ──
    ax2 = axes[1]
    rows = []
    for (_, e), grp in df.groupby(["start_date", "end_date"]):
        q1r = grp[grp["quintile"] == 1]["gross_return"].mean() - TC_RT
        q5r = grp[grp["quintile"] == 5]["gross_return"].mean() - TC_RT
        if not (pd.isna(q1r) or pd.isna(q5r)):
            rows.append({"date": pd.Timestamp(e), "spread": (q1r - q5r) * 100})
    sdf = pd.DataFrame(rows).sort_values("date")
    bar_colors = ["#2166ac" if v > 0 else "#d73027" for v in sdf["spread"]]
    ax2.bar(
        sdf["date"],
        sdf["spread"],
        color=bar_colors,
        width=60,
        alpha=0.85,
        edgecolor="white",
        linewidth=0.4,
    )
    ax2.axhline(0, color="black", linewidth=0.8)
    pos = (sdf["spread"] > 0).sum()
    ax2.text(
        0.98,
        0.96,
        f"Avg: {sdf['spread'].mean():+.2f}%/qtr  |  Positive: {pos}/{len(sdf)} quarters",
        transform=ax2.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9),
    )
    ax2.set_title(
        "Q1 − Q5 Net Return Spread per Quarter  (blue = factor worked)",
        fontsize=11,
        fontweight="bold",
    )
    ax2.set_ylabel("Spread (%)")
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))

    fig.tight_layout(pad=2.5)
    out = CHARTS / "01_10year_nav.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ── Chart 21: Q1 vs Q5 clean comparison ──────────────────────────────────────
def chart_q1_vs_q5(df: pd.DataFrame):  # pragma: no cover
    fig, ax = plt.subplots(figsize=(13, 6))

    for q in range(1, 6):
        dates, nav = make_nav(df, q)
        ax.plot(dates, nav, label=LABELS[q], color=COLORS[q], linewidth=LW[q])

    shade_regimes(ax)
    ax.axhline(100, color="grey", linewidth=0.5, linestyle="--")

    for q in [1, 5]:
        dates_q, nav_q = make_nav(df, q)
        ax.annotate(
            f"Q{q}: {nav_q[-1]:.0f}",
            xy=(dates_q[-1], nav_q[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            fontsize=9,
            color=COLORS[q],
            fontweight="bold",
            va="center",
        )

    ax.set_title(
        "Quintile Cumulative NAV: Q1 vs Q5 (base=100)\n"
        "Net of 0.4% round-trip transaction cost  |  Dec 2015 – Dec 2025  |  40 quarters",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("NAV (base 100)")
    ax.legend(loc="upper left", fontsize=9, ncol=2)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    fig.tight_layout()
    out = CHARTS / "02_q1_vs_q5.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ── Annual returns table ──────────────────────────────────────────────────────
REGIMES = {
    2016: "Growth rally",
    2017: "Broad bull market",
    2018: "Market correction",
    2019: "Late-cycle rally",
    2020: "COVID crash + recovery",
    2021: "Post-COVID reflation",
    2022: "Bear market / rate hikes",
    2023: "AI bull market begins",
    2024: "AI bull continues",
    2025: "Volatility / tariff shock",
}

_HDR_BG = "#2166ac"
_HDR_FG = "white"
_ALT_ROW = "#eef2f7"
_AMBER = "#fff3cd"
_GREEN = "#155724"
_RED = "#721c24"
_BORDER = "#cccccc"


def compute_annual_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Compound quarterly Q1 and EW returns to annual figures."""
    df = df.copy()
    df = df.dropna(subset=["quintile", "gross_return"])
    df["year"] = df["end_date"].dt.year

    rows = []
    for year, grp in df.groupby("year"):
        if year not in REGIMES:
            continue
        q1_qtrs, ew_qtrs = [], []
        for _, pgrp in grp.groupby(["start_date", "end_date"]):
            q1 = pgrp[pgrp["quintile"] == 1]
            if not q1.empty:
                q1_qtrs.append(q1["gross_return"].mean())
            ew_qtrs.append(pgrp["gross_return"].mean())
        if not q1_qtrs:
            continue
        q1_gross = np.prod([1 + r for r in q1_qtrs]) - 1
        q1_net = np.prod([1 + r - TC_RT for r in q1_qtrs]) - 1
        ew_net = np.prod([1 + r - TC_RT for r in ew_qtrs]) - 1
        rows.append(
            {
                "year": year,
                "q1_gross": q1_gross,
                "q1_net": q1_net,
                "ew_net": ew_net,
                "vs_bm": "▲" if q1_net > ew_net else "▼",
                "result": "OK" if q1_net > 0 else "FAIL",
                "regime": REGIMES[year],
            }
        )
    _COLS = ["year", "q1_gross", "q1_net", "ew_net", "vs_bm", "result", "regime"]
    if not rows:
        return pd.DataFrame(columns=_COLS)
    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


def chart_annual_returns_table(ann: pd.DataFrame):  # pragma: no cover
    """Render the long-only Q1 annual return table as a styled PNG."""
    headers = ["Year", "Q1 Gross", "Q1 Net", "EW Net", "vs BM", "Result", "Market Regime"]
    col_widths = [0.07, 0.11, 0.10, 0.10, 0.08, 0.09, 0.24]

    table_data = [
        [
            str(int(r["year"])),
            f"{r['q1_gross']*100:+.1f}%",
            f"{r['q1_net']*100:+.1f}%",
            f"{r['ew_net']*100:+.1f}%",
            r["vs_bm"],
            r["result"],
            r["regime"],
        ]
        for _, r in ann.iterrows()
    ]

    fig, ax = plt.subplots(figsize=(13, 5.2))
    ax.axis("off")

    tbl = ax.table(
        cellText=table_data,
        colLabels=headers,
        loc="center",
        cellLoc="center",
        colWidths=col_widths,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1, 1.85)

    n_cols = len(headers)
    for j in range(n_cols):
        cell = tbl[0, j]
        cell.set_facecolor(_HDR_BG)
        cell.set_text_props(color=_HDR_FG, fontweight="bold")
        cell.set_edgecolor(_HDR_BG)

    for i, row in ann.iterrows():
        is_fail = row["result"] == "FAIL"
        for j in range(n_cols):
            cell = tbl[i + 1, j]
            cell.set_edgecolor(_BORDER)
            if is_fail:
                cell.set_facecolor(_AMBER)
            elif i % 2 == 1:
                cell.set_facecolor(_ALT_ROW)
            else:
                cell.set_facecolor("white")
            if j == 4:  # vs BM arrow
                col = _GREEN if row["vs_bm"] == "▲" else _RED
                cell.set_text_props(color=col, fontweight="bold", fontsize=12)
            if j == 5:  # Result text
                col = _GREEN if row["result"] == "OK" else _RED
                cell.set_text_props(color=col, fontweight="bold")
            if j == 6:  # Market Regime — left-align
                cell._loc = "left"
                cell.PAD = 0.05

    fig.text(
        0.5,
        0.97,
        "Long-Only Q1 Annual Return (2016\u20132025)",
        ha="center",
        va="top",
        fontsize=12,
        fontweight="bold",
        color="#222222",
    )
    fig.text(
        0.5,
        0.91,
        "Q1 Net = compounded quarterly gross \u2212 0.4% TC each quarter"
        "\u2003|\u2003\u25b2 = beat EW Universe\u2003|\u2003OK = positive net return",
        ha="center",
        va="top",
        fontsize=9,
        color="#444444",
    )

    fig.tight_layout(rect=[0, 0, 1, 0.90])
    out = CHARTS / "07c_q1_annual_returns_table.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():  # pragma: no cover
    print("Loading 10-year stock returns...")
    df = load_returns()
    print(
        f"  {len(df):,} rows | {df['start_date'].nunique()} periods | "
        f"{df['start_date'].min().date()} -> {df['end_date'].max().date()}"
    )

    print("Generating charts...")
    chart_10year_nav(df)
    chart_q1_vs_q5(df)
    ann = compute_annual_returns(df)
    chart_annual_returns_table(ann)
    print("Done.")


if __name__ == "__main__":
    main()
