"""Streamlit dashboard — Team RUSSEL Systematic Equity Strategy.

Run:
    cd team_russell/coursework_one
    poetry run streamlit run ../coursework_two/dashboard/app.py

Reads data directly via the DuckDB query layer (no API call needed).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Allow importing from api/queries.py and scripts/_rf_rates.py
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import queries as q  # noqa: E402
from _rf_rates import rf_quarterly_series  # noqa: E402

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="RUSSEL Factor Strategy",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

RESULTS = Path(__file__).parent.parent / "results"
TC_RT = 0.004

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("📊 RUSSEL Factor Strategy")
st.sidebar.markdown(
    "**3-Factor Model**  \n"
    "Value 35% · Quality 35% · Momentum 30%  \n"
    "Net of 0.4% round-trip transaction cost"
)
page = st.sidebar.radio(
    "Navigate",
    ["🏠 Overview", "📈 Performance", "🔬 IC Analysis", "🔍 Stock Browser"],
)
st.sidebar.markdown("---")
st.sidebar.caption("Team RUSSEL · UCL IFT Big Data in Quantitative Finance · CW2")


# ── Cached data loaders ───────────────────────────────────────────────────────
@st.cache_data
def load_summary():
    return q.get_summary_stats()


@st.cache_data
def load_quintiles():
    return pd.DataFrame(q.get_quintile_summary())


@st.cache_data
def load_annual():
    return pd.DataFrame(q.get_annual_performance())


@st.cache_data
def load_ic_series():
    return pd.DataFrame(q.get_ic_series())


@st.cache_data
def load_ic_summary():
    return q.get_ic_summary()


@st.cache_data
def load_dates():
    return q.get_rebalance_dates()


@st.cache_data
def load_returns_10y():
    df = pd.read_csv(RESULTS / "stock_returns_10year.csv")
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    return df


@st.cache_data
def load_benchmark():
    path = RESULTS / "benchmark_comparison.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    return df.sort_values("start_date").reset_index(drop=True)


def make_nav(df, quintile):
    qd = (
        df[df["quintile"] == quintile]
        .groupby(["start_date", "end_date"])["gross_return"]
        .mean()
        .reset_index()
        .sort_values("start_date")
    )
    qd["net"] = qd["gross_return"] - TC_RT
    nav = np.insert((1 + qd["net"]).cumprod().values, 0, 1.0) * 100
    dates = [qd["start_date"].iloc[0]] + list(qd["end_date"])
    return dates, nav


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
if page == "🏠 Overview":
    st.title("RUSSEL Systematic Equity Strategy")
    st.markdown(
        "A **3-factor long-only equity strategy** (Value + Quality + Momentum) "
        "backtested over **40 quarterly periods** (Dec 2015 – Dec 2025) across "
        "a mixed US and European large-cap universe of up to 597 companies."
    )

    kpi = load_summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Q1 Ann. Net Return", f"{kpi['q1_ann_net_return_pct']:.1f}%")
    c2.metric("Q1 Sharpe Ratio", f"{kpi['q1_sharpe_ratio']:.3f}")
    c3.metric("Q1-Q5 Spread", f"+{kpi['q1_q5_spread_pct']:.2f}%")
    c4.metric("Q1 Hit Rate", f"{kpi['q1_hit_rate_pct']:.0f}%")

    st.markdown("---")

    # NAV chart
    st.subheader("10-Year Cumulative NAV by Quintile")
    df_10y = load_returns_10y()
    COLORS = {1: "#2166ac", 2: "#74add1", 3: "#a6a6a6", 4: "#f4a582", 5: "#d73027"}
    LABELS = {1: "Q1 (Top 20%)", 2: "Q2", 3: "Q3", 4: "Q4", 5: "Q5 (Bottom 20%)"}
    LW = {1: 3, 2: 1.5, 3: 1.5, 4: 1.5, 5: 3}

    fig = go.Figure()
    for qt in range(1, 6):
        dates, nav = make_nav(df_10y, qt)
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=nav,
                name=LABELS[qt],
                line=dict(color=COLORS[qt], width=LW[qt]),
                hovertemplate="%{y:.1f}<extra>" + LABELS[qt] + "</extra>",
            )
        )

    # Shade regimes
    for x0, x1, label in [
        ("2018-01-01", "2018-12-31", "2018 correction"),
        ("2020-01-01", "2020-06-30", "COVID crash"),
        ("2022-01-01", "2022-12-31", "2022 bear"),
    ]:
        fig.add_vrect(
            x0=x0,
            x1=x1,
            fillcolor="#d73027",
            opacity=0.07,
            layer="below",
            line_width=0,
            annotation_text=label,
            annotation_position="top left",
            annotation_font_size=10,
            annotation_font_color="#b2182b",
        )

    fig.add_hline(y=100, line_dash="dot", line_color="grey", line_width=1)
    fig.update_layout(
        height=420,
        yaxis_title="NAV (base 100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        hovermode="x unified",
        margin=dict(t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"Net of {TC_RT*100:.1f}% round-trip transaction cost. "
        "Shaded areas = stress market regimes. Base = 100 at Dec 2015."
    )

    # Benchmark comparison
    st.markdown("---")
    st.subheader("Q1 vs Benchmarks")
    bm_df = load_benchmark()
    if bm_df is None:
        st.info("Benchmark data not found. Run step06_benchmark.py to generate it.")
    else:
        bm_series = {
            "Q1 (Factor Strategy)": ("q1_net", "#2166ac", 3),
            "S&P 500 (SPY)": ("SPY_net", "#e66101", 1.5),
            "MSCI World (URTH)": ("URTH_net", "#5e3c99", 1.5),
            "MSCI ACWI": ("ACWI_net", "#4dac26", 1.5),
        }

        fig_bm = go.Figure()
        for label, (col, color, lw) in bm_series.items():
            nav = np.insert((1 + bm_df[col]).cumprod().values, 0, 1.0) * 100
            dates = [bm_df["start_date"].iloc[0]] + list(bm_df["end_date"])
            fig_bm.add_trace(
                go.Scatter(
                    x=dates,
                    y=nav,
                    name=label,
                    line=dict(color=color, width=lw),
                    hovertemplate="%{y:.1f}<extra>" + label + "</extra>",
                )
            )

        fig_bm.add_hline(y=100, line_dash="dot", line_color="grey", line_width=1)
        n_quarters = len(bm_df)
        start_yr = bm_df["start_date"].iloc[0].strftime("%b %Y")
        end_yr = bm_df["end_date"].iloc[-1].strftime("%b %Y")
        fig_bm.update_layout(
            height=380,
            yaxis_title="NAV (base 100)",
            legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
            hovermode="x unified",
            margin=dict(t=40, b=20),
        )
        st.plotly_chart(fig_bm, use_container_width=True)
        st.caption(
            f"{n_quarters} quarters ({start_yr} – {end_yr}). "
            "Q1 net of 0.4% round-trip transaction cost. Benchmarks net of 0.4% for comparability."
        )

        # Benchmark KPI row — Sharpe uses time-varying 3mo T-bill per quarter
        rf_q = rf_quarterly_series(bm_df["start_date"])

        def bm_stats(col):
            r = bm_df[col]
            ann = (1 + r.mean()) ** 4 - 1
            vol = r.std(ddof=1) * np.sqrt(4)
            excess = r.values - rf_q.values
            ann_excess = float(np.mean(excess)) * 4
            return ann * 100, vol * 100, ann_excess / vol if vol else 0

        b1, b2, b3, b4 = st.columns(4)
        for widget, label, col in [
            (b1, "Q1 Strategy", "q1_net"),
            (b2, "S&P 500", "SPY_net"),
            (b3, "MSCI World", "URTH_net"),
            (b4, "MSCI ACWI", "ACWI_net"),
        ]:
            ann, vol, sharpe = bm_stats(col)
            widget.metric(label, f"{ann:.1f}%", f"Sharpe {sharpe:.2f}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📈 Performance":
    st.title("Quintile Performance Analysis")

    # Quintile summary table
    st.subheader("10-Year Quintile Performance (40 quarters, net of costs)")
    qt_df = load_quintiles()
    display = qt_df.rename(
        columns={
            "quintile": "Quintile",
            "n_periods": "Periods",
            "ann_net_return_pct": "Ann. Net Return (%)",
            "ann_vol_pct": "Ann. Volatility (%)",
            "sharpe_ratio": "Sharpe Ratio",
            "sortino_ratio": "Sortino Ratio",
            "hit_rate_pct": "Hit Rate (%)",
        }
    )[
        [
            "Quintile",
            "Periods",
            "Ann. Net Return (%)",
            "Ann. Volatility (%)",
            "Sharpe Ratio",
            "Sortino Ratio",
            "Hit Rate (%)",
        ]
    ]

    def highlight_q1_q5(row):
        if row["Quintile"] == 1:
            return ["background-color: #1c3d5a; color: white"] * len(row)
        elif row["Quintile"] == 5:
            return ["background-color: #5c2010; color: white"] * len(row)
        return [""] * len(row)

    st.dataframe(
        display.style.apply(highlight_q1_q5, axis=1).format(
            {
                "Ann. Net Return (%)": "{:.2f}%",
                "Ann. Volatility (%)": "{:.2f}%",
                "Sharpe Ratio": "{:.3f}",
                "Sortino Ratio": "{:.3f}",
                "Hit Rate (%)": "{:.1f}%",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    # Annual performance
    st.subheader("Annual Q1 vs Q5 Performance")
    ann_df = load_annual()
    ann_df["Factor Worked"] = ann_df["spread_pct"] > 0

    fig2 = go.Figure()
    colors = ["#2166ac" if v else "#d73027" for v in ann_df["Factor Worked"]]
    fig2.add_trace(
        go.Bar(
            x=ann_df["year"],
            y=ann_df["spread_pct"],
            marker_color=colors,
            name="Q1-Q5 Spread",
            hovertemplate="Year %{x}<br>Spread: %{y:.2f}%/qtr<extra></extra>",
        )
    )
    fig2.add_hline(y=0, line_color="black", line_width=1)
    fig2.update_layout(
        height=320,
        yaxis_title="Q1 − Q5 Avg Quarterly Net Return (%)",
        xaxis=dict(tickmode="linear", dtick=1),
        hovermode="x unified",
        margin=dict(t=20, b=20),
        showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)

    years_worked = ann_df["Factor Worked"].sum()
    st.caption(
        f"Blue = factor worked (Q1 > Q5). "
        f"Factor delivered positive spread in **{years_worked}/{len(ann_df)} calendar years** ({years_worked/len(ann_df)*100:.0f}% annual hit rate)."
    )

    # Sharpe bar chart
    st.subheader("Sharpe Ratio by Quintile")
    fig3 = px.bar(
        qt_df,
        x="quintile",
        y="sharpe_ratio",
        color="sharpe_ratio",
        color_continuous_scale="RdBu",
        labels={"quintile": "Quintile", "sharpe_ratio": "Sharpe Ratio"},
    )
    fig3.update_layout(height=300, coloraxis_showscale=False, margin=dict(t=20, b=20))
    fig3.update_traces(hovertemplate="Q%{x}<br>Sharpe: %{y:.3f}<extra></extra>")
    st.plotly_chart(fig3, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — IC ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔬 IC Analysis":
    st.title("Information Coefficient (IC) Analysis")
    st.markdown(
        "The **IC** is the Spearman rank correlation between composite factor scores "
        "and subsequent quarterly returns. Positive IC = factor was directionally correct."
    )

    ic_sum = load_ic_summary()
    c1, c2, c3 = st.columns(3)
    c1.metric("Mean IC", f"{ic_sum['mean_ic_pct']:+.2f}%")
    c2.metric("ICIR", f"{ic_sum['icir']:.3f}")
    c3.metric(
        "Hit Rate",
        f"{ic_sum['hit_rate_pct']:.0f}%  ({int(ic_sum['hit_rate_pct']/100*ic_sum['n_periods'])}/{ic_sum['n_periods']} quarters)",
    )

    st.markdown("---")
    st.subheader("IC per Quarter")
    ic_df = load_ic_series()
    ic_df["label"] = pd.to_datetime(ic_df["start_date"]).dt.strftime("%b'%y")

    fig4 = go.Figure()
    bar_colors = ["#2166ac" if v > 0 else "#d73027" for v in ic_df["ic_pct"]]
    fig4.add_trace(
        go.Bar(
            x=ic_df["label"],
            y=ic_df["ic_pct"],
            marker_color=bar_colors,
            hovertemplate="%{x}<br>IC: %{y:.2f}%<extra></extra>",
        )
    )
    fig4.add_hline(y=0, line_color="black", line_width=1)
    fig4.add_hline(
        y=ic_sum["mean_ic_pct"],
        line_dash="dash",
        line_color="#2166ac",
        line_width=1.5,
        annotation_text=f"Mean IC: {ic_sum['mean_ic_pct']:+.2f}%",
        annotation_position="top right",
    )
    fig4.update_layout(
        height=380,
        yaxis_title="IC (%)",
        xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
        hovermode="x unified",
        margin=dict(t=20, b=60),
    )
    st.plotly_chart(fig4, use_container_width=True)

    st.subheader("Period-by-Period Detail")
    display_ic = ic_df[["start_date", "end_date", "ic_pct", "n_stocks"]].copy()
    display_ic.columns = ["Start", "End", "IC (%)", "N stocks"]

    def colour_ic(row):
        if row["IC (%)"] > 0:
            return ["background-color: #1c3d5a; color: white"] * len(row)
        return ["background-color: #5c2010; color: white"] * len(row)

    st.dataframe(
        display_ic.style.apply(colour_ic, axis=1).format({"IC (%)": "{:+.3f}%"}),
        use_container_width=True,
        hide_index=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — STOCK BROWSER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Stock Browser":
    st.title("Factor Score Browser")
    st.markdown(
        "Browse stocks ranked by composite factor score at any rebalance date. "
        "Powered by **DuckDB** querying the backtested dataset."
    )

    col1, col2, col3 = st.columns([2, 1, 1])
    dates = load_dates()
    selected_date = col1.selectbox("Rebalance date", dates)
    selected_q = col2.selectbox("Quintile", ["All", 1, 2, 3, 4, 5])
    limit = col3.slider("Max rows", 10, 200, 50)

    q_filter = None if selected_q == "All" else int(selected_q)

    with st.spinner("Querying DuckDB..."):
        stocks_df = pd.DataFrame(q.get_stocks_by_date_quintile(selected_date, q_filter, limit))

    if stocks_df.empty:
        st.warning("No data found for the selected filters.")
    else:
        st.markdown(
            f"**{len(stocks_df)} stocks** at `{selected_date}`"
            + (f" · Q{selected_q}" if selected_q != "All" else " · All quintiles")
        )

        QUINTILE_COLORS = {1: "#2166ac", 2: "#74add1", 3: "#a6a6a6", 4: "#f4a582", 5: "#d73027"}

        def colour_quintile(row):
            c = QUINTILE_COLORS.get(row["Q"], "#ffffff")
            return [f"background-color: {c}22"] * len(row)

        display_cols = {
            "symbol": "Ticker",
            "quintile": "Q",
            "composite_score": "Composite",
            "value_score": "Value",
            "quality_score": "Quality",
            "momentum_score": "Momentum",
            "gross_return_pct": "Gross Ret (%)",
            "net_return_pct": "Net Ret (%)",
        }
        show_df = stocks_df[list(display_cols.keys())].rename(columns=display_cols)

        st.dataframe(
            show_df.style.apply(colour_quintile, axis=1).format(
                {
                    "Composite": "{:.4f}",
                    "Value": "{:.4f}",
                    "Quality": "{:.4f}",
                    "Momentum": "{:.4f}",
                    "Gross Ret (%)": "{:+.2f}%",
                    "Net Ret (%)": "{:+.2f}%",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

        # Score distribution
        st.subheader("Composite Score Distribution")
        fig5 = px.histogram(
            stocks_df,
            x="composite_score",
            color="quintile",
            color_discrete_map=QUINTILE_COLORS,
            nbins=40,
            labels={"composite_score": "Composite Score", "quintile": "Quintile"},
        )
        fig5.update_layout(height=280, margin=dict(t=20, b=20), bargap=0.1, showlegend=True)
        st.plotly_chart(fig5, use_container_width=True)
