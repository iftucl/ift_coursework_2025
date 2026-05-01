"""Methodology.

Strategy description, formulas, references, and known limitations.
"""

import streamlit as st
from lib.components import page_setup, section_header
from lib.theme import install_template

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

page_setup("Methodology", icon="📚")
install_template()

st.title("Methodology")
st.caption(
    "How the strategy is constructed, how the metrics are computed, and the "
    "known limitations of this backtest."
)


# ---------------------------------------------------------------------------
# Strategy overview
# ---------------------------------------------------------------------------

section_header("Strategy overview")

st.markdown("""
The strategy is a **130/30 long-short multi-factor equity portfolio** with
sector neutrality across the 11 GICS sectors. The pipeline runs monthly:

1. **Universe filter** - Liquidity screen using ADV ≥ $1M and Amihud ILLIQ rank
   (top 10% removed)
2. **Factor scoring** - Compute Value, Quality, Momentum, Low-Volatility raw
   metrics → winsorise within sector → standardise to z-scores → orthogonalise
   Low-Vol against Momentum
3. **Composite score** - IC-weighted combination of the four factor z-scores,
   using rolling 36-month mean IC (negative ICs floored to zero)
4. **Stock selection** - Within each sector, top 10% by composite enter long
   basket; bottom 10% enter short basket. Buffer zone (10-20%) holds existing
   positions for up to 3 months
5. **Risk-adjusted weights** - EWMA volatility (λ=0.94) divides the composite
   score; weights normalised to 130% long / 30% short per-sector targets
6. **Liquidity cap** - Position size cannot exceed 5% of 20-day ADTV
7. **No-trade zone** - If target weight change < 1%, hold current position
8. **Backtest** - Walk-forward, point-in-time, monthly rebalance, transaction
   costs and short-borrow charges deducted from gross returns
""")


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------

section_header("Key formulas")

st.markdown("**IC-weighted composite score**")
st.latex(
    r"\text{composite}_i = \sum_{f \in \{V, Q, M, L\}} w_f \cdot z_{f,i}, "
    r"\quad w_f = \frac{\max(\overline{IC}_f, 0)}{\sum_g \max(\overline{IC}_g, 0)}"
)

st.markdown("**Risk-adjusted score for weighting**")
st.latex(
    r"\text{score}_i^{\text{adj}} = \frac{\text{composite}_i}"
    r"{\sigma_i^{\text{EWMA}}}, \quad "
    r"(\sigma_t^{\text{EWMA}})^2 = \lambda \sigma_{t-1}^2 + (1-\lambda) r_{t-1}^2"
)

st.markdown("**Sharpe / Sortino / Calmar / Information Ratio**")
st.latex(
    r"\text{Sharpe} = \frac{R_p - R_f}{\sigma_p}, \quad "
    r"\text{Sortino} = \frac{R_p - R_f}{\sigma_p^{\text{down}}}"
)
st.latex(
    r"\text{Calmar} = \frac{R_p}{|MD|}, \quad "
    r"\text{IR} = \frac{R_p - R_b}{\sigma_{p-b}}"
)

st.markdown("**Walk-forward backtest**")
st.latex(
    r"R_t^{\text{net}} = R_t^{\text{gross}} - c \cdot \tau_t - "
    r"\frac{r^{\text{borrow}}}{12} \cdot |w^{\text{short}}_t|"
)
st.caption(
    "where τ is monthly turnover, c the per-side cost in bps, and "
    r"r^{\text{borrow}} the annual short-borrow rate."
)


# ---------------------------------------------------------------------------
# Known limitations
# ---------------------------------------------------------------------------

section_header("Known limitations")

st.markdown("""
1. **Factor ICs are weak** in the 2021-2026 window. Average rolling-36m ICs
   for all four factors are below the academic 0.02 threshold. Quality has the
   highest avg IC (~0.002), Value is slightly negative (~-0.011). The strategy's
   alpha is real in this period but probably driven more by sector neutrality
   and risk-adjusted weighting than by factor predictiveness.

2. **Backtest period is 5 years** which is short for a multi-factor strategy.
   Different regimes (e.g. 2008, 2018, 2020) would be informative but require
   the data pipeline to be extended further back.

3. **Variant scenarios persist only summary metrics**. The portfolio_positions,
   factor_scores, and selection_status tables only contain baseline data.
   For deep-dive on a specific variant (e.g. excl_quality holdings), the user
   would need to re-run the pipeline with that as baseline.

4. **130/30 constraint drift** of 1-3% is observed and is inherent to the
   strategy mechanics (liquidity caps, no-trade-zone interactions). Tolerated
   in line with industry 130/30 practice.

5. **MSCI USA proxy** uses the EUSA ETF since the actual index is not freely
   accessible. Tracking is close but not identical.
""")


# ---------------------------------------------------------------------------
# Database schema overview
# ---------------------------------------------------------------------------

section_header("Database schema")

st.markdown("""
Tables that this dashboard reads from (all in schema `team_wittgenstein`):

| Table | Contents |
|-------|----------|
| `price_data` | Daily OHLCV + adjusted close (~1M rows) |
| `financial_data` | Quarterly fundamentals from EDGAR / SimFin / yfinance |
| `risk_free_rates` | Monthly risk-free rates by country |
| `factor_metrics` | Raw factor inputs per stock per month |
| `factor_scores` | Sector-relative z-scores + composite |
| `ic_weights` | Rolling 36m IC and derived weights per factor per month |
| `selection_status` | Long/short/buffer status per stock per month |
| `portfolio_positions` | Final weights per stock per month |
| `liquidity_metrics` | ADV20 + Amihud ILLIQ + screening flags |
| `backtest_returns` | Monthly returns per scenario |
| `backtest_summary` | Headline metrics per scenario (23 rows) |
| `benchmark_returns` | Cached MSCI USA monthly returns |
""")


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

section_header("References")

st.markdown("""
- Amihud, Y. (2002). Illiquidity and stock returns. *Journal of Financial Markets*.
- Asness, C., Frazzini, A., Israel, R., Moskowitz, T. (2015). Fact, fiction, and
  value investing. *Journal of Portfolio Management*.
- Fama, E. F., French, K. R. (1993). Common risk factors in the returns on
  stocks and bonds. *Journal of Financial Economics*.
- Grinold, R., Kahn, R. (1999). *Active Portfolio Management*. McGraw-Hill.
- Jegadeesh, N., Titman, S. (1993). Returns to buying winners and selling
  losers. *Journal of Finance*.
- Novy-Marx, R. (2013). The other side of value: The gross profitability
  premium. *Journal of Financial Economics*.
- Sortino, F., van der Meer, R. (1991). Downside risk. *Journal of Portfolio
  Management*.
- RiskMetrics Group (1996). *RiskMetrics Technical Document*.
""")


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    "Big Data in Quantitative Finance - Coursework 2 - Team Wittgenstein. "
    "Dashboard built with Streamlit + Plotly. Data backed by PostgreSQL "
    "running locally in Docker."
)
