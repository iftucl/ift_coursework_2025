"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Main_CW2.py — Single entry point for CW2 backtest
Project : CW2 - Value-Sentiment Investment Strategy

Entry point for the CW2 backtesting pipeline.  Orchestrates the
full workflow:

  1. Load configuration from backtest_config.yaml
  2. Connect to CW1 PostgreSQL database
  3. Load prices, universe, and benchmark data
  4. Run backtests for all 4 portfolio variants
  5. Compute performance metrics and risk analysis
  6. Run robustness tests (6 tests)
  7. Generate all 12 charts and tearsheet
  8. Output summary tables

Usage::

    poetry run python Main_CW2.py --config config/backtest_config.yaml
    poetry run python Main_CW2.py --config config/backtest_config.yaml --skip-robustness
    poetry run python Main_CW2.py --config config/backtest_config.yaml --portfolio combined

Ref: Part D §D1 — Code Architecture
"""

import argparse
import io
import logging
import os
import sys
import time
from datetime import datetime

import pandas as pd
import yaml

# --- Configure logging (UTF-8 safe on Windows / non-UTF-8 locales) ---
# On Windows the default cp1251/cp1252 stdout encoding cannot represent
# characters like × → ± that appear in our log messages. Force UTF-8 on
# both the stdout stream and the log file so every run is portable.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backtest_run.log', mode='w', encoding='utf-8'),
    ],
)
logger = logging.getLogger('Main_CW2')


def parse_args():
    """Parse command-line arguments.

    :returns: Parsed argument namespace
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(
        description='CW2 Value-Sentiment Backtest Pipeline',
    )
    parser.add_argument(
        '--config', type=str, default='config/backtest_config.yaml',
        help='Path to backtest configuration YAML',
    )
    parser.add_argument(
        '--portfolio', type=str, default='all',
        choices=['all', 'combined', 'value_only', 'sentiment_only'],
        help='Which portfolio variant to run',
    )
    parser.add_argument(
        '--skip-robustness', action='store_true',
        help='Skip robustness testing (faster for development)',
    )
    parser.add_argument(
        '--skip-charts', action='store_true',
        help='Skip chart generation',
    )
    parser.add_argument(
        '--output-dir', type=str, default='output',
        help='Directory for output files',
    )
    return parser.parse_args()


def load_config(config_path: str) -> dict:
    """Load and validate backtest configuration.

    :param config_path: Path to YAML config file
    :type config_path: str
    :returns: Parsed configuration dict
    :rtype: dict
    :raises FileNotFoundError: If config file does not exist
    """
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    logger.info("Configuration loaded from %s", config_path)
    return config


def _build_top_quintile_sector_table(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    sector_map: dict,
    score_col: str = 'value_score',
    old_col: str = None,
    new_col: str = None,
) -> pd.DataFrame:
    """Summarise sector concentration of top quintile under OLD vs NEW scoring.

    Used for Tables 9 (value) and 10 (sentiment): shows the percentage of the
    top 20% of stocks by score falling into each GICS sector under each method.
    """
    old_col = old_col or score_col
    new_col = new_col or score_col

    def _sector_pcts(df, col):
        if df is None or len(df) == 0 or col not in df.columns:
            return pd.Series(dtype=float)
        d = df.copy()
        id_col = 'company_id' if 'company_id' in d.columns else d.index.name
        d['sector'] = d[id_col].map(sector_map) if id_col in d.columns else d.index.map(sector_map)
        valid = d[d[col].notna()]
        if len(valid) == 0:
            return pd.Series(dtype=float)
        top = valid.nlargest(max(1, int(len(valid) * 0.20)), col)
        return (top['sector'].value_counts() / len(top) * 100).round(2)

    old_pcts = _sector_pcts(old_df, old_col)
    new_pcts = _sector_pcts(new_df, new_col)
    sectors = sorted(set(old_pcts.index).union(new_pcts.index))
    return pd.DataFrame({
        'gics_sector': sectors,
        'old_pct': [old_pcts.get(s, 0.0) for s in sectors],
        'new_pct': [new_pcts.get(s, 0.0) for s in sectors],
        'delta_pct': [round(new_pcts.get(s, 0.0) - old_pcts.get(s, 0.0), 2) for s in sectors],
    })


def run_pipeline():
    """Execute the full CW2 backtest pipeline."""
    args = parse_args()
    start_time = time.time()

    # --- Banner ---
    logger.info("=" * 70)
    logger.info("  CW2 VALUE-SENTIMENT INVESTMENT STRATEGY — BACKTEST PIPELINE")
    logger.info("  Team Wald — UCL Institute of Finance & Technology")
    logger.info("  IFTE0003: Big Data in Quantitative Finance")
    logger.info("  Run started: %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    logger.info("=" * 70)

    # --- Step 1: Load configuration ---
    config = load_config(args.config)
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'charts'), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'tables'), exist_ok=True)

    # --- Step 2: Initialise data layer ---
    logger.info("--- STEP 2: Initialising data layer ---")
    from modules.data.data_loader import DataLoader
    from modules.data.universe import UniverseConstructor
    from modules.data.benchmark import BenchmarkLoader

    loader = DataLoader(config)
    company_df = loader.load_company_static()

    start_date = config['backtest']['start_date']
    end_date = config['backtest']['end_date']

    prices = loader.load_daily_prices(start_date, end_date)
    logger.info("Prices loaded: %d dates × %d tickers", len(prices), len(prices.columns))

    universe = UniverseConstructor(company_df, prices, config)
    benchmark_loader = BenchmarkLoader(config)

    # --- Step 3: Load benchmark data (3 benchmarks per Part A §A7.3) ---
    logger.info("--- STEP 3: Loading benchmark data ---")
    benchmark_prices = benchmark_loader.load_primary(start_date, end_date)
    benchmark_returns = benchmark_loader.compute_benchmark_returns(benchmark_prices)

    # Secondary benchmark (MSCI World Value via IWVL.L)
    secondary_returns = pd.Series(dtype=float)
    try:
        secondary_prices = benchmark_loader.load_secondary(start_date, end_date)
        if len(secondary_prices) > 0:
            secondary_returns = benchmark_loader.compute_benchmark_returns(secondary_prices)
            logger.info("Secondary benchmark (MSCI World Value): %d days", len(secondary_returns))
    except Exception as e:
        logger.warning("Secondary benchmark load failed: %s", e)

    # Equal-weight universe benchmark — isolates value of stock selection
    ew_universe_returns = benchmark_loader.compute_equal_weight_universe_returns(
        prices, prices.columns.tolist(),
    )

    # --- Step 4: Run backtests ---
    logger.info("--- STEP 4: Running backtests ---")
    from modules.backtest.backtester import Backtester

    backtester = Backtester(loader, universe, config)

    portfolio_types = ['combined', 'value_only', 'sentiment_only']
    if args.portfolio != 'all':
        portfolio_types = [args.portfolio]

    results = {}
    for ptype in portfolio_types:
        logger.info(">>> Running %s portfolio backtest", ptype)
        result = backtester.run(prices, portfolio_type=ptype)
        results[ptype] = result
        logger.info(
            "  %s: %d trading days, total return = %.2f%%",
            ptype, len(result['returns']),
            ((1 + result['returns']).prod() - 1) * 100 if len(result['returns']) > 0 else 0,
        )

    # --- Step 4b: Weighting scheme comparison (guide A5) ---
    # Run combined portfolio with all 3 weighting schemes for comparison
    weighting_schemes = ['equal_weight', 'score_weight', 'inverse_volatility']
    weighting_results = {}
    if 'combined' in portfolio_types:
        logger.info("--- STEP 4b: Weighting scheme comparison ---")
        for scheme in weighting_schemes:
            label = f'combined_{scheme}'
            logger.info(">>> Running combined portfolio with %s weighting", scheme)
            result = backtester.run(prices, scheme_override=scheme, portfolio_type='combined')
            weighting_results[label] = result
            logger.info(
                "  %s: %d trading days, total return = %.2f%%",
                label, len(result['returns']),
                ((1 + result['returns']).prod() - 1) * 100 if len(result['returns']) > 0 else 0,
            )

    # --- Step 5: Performance evaluation ---
    logger.info("--- STEP 5: Performance evaluation ---")
    from modules.analytics.performance import (
        compute_performance_summary,
        compute_top_drawdowns,
    )
    from modules.analytics.risk import compute_fama_french_regression, compute_var, compute_cvar
    from modules.analytics.turnover import compute_turnover_summary
    from modules.analytics.diversification import (
        compute_diversification_metrics,
        compute_diversification_over_time,
        compute_sector_allocation,
    )
    from modules.analytics.pitfalls import build_pitfalls_table
    from modules.analytics.appendices import write_all_appendices

    rf_rate = config.get('risk_free', {}).get('annual_rate', 0.04)
    sector_map = universe.get_sector_map()

    ff_result = None
    random_result = None

    all_metrics = []
    for ptype, result in results.items():
        metrics = compute_performance_summary(
            result['returns'], benchmark_returns, rf_rate, ptype,
        )

        # Add turnover summary
        turnover_summary = compute_turnover_summary(result['turnover'], result['costs'])
        metrics.update(turnover_summary)

        # Add risk metrics
        metrics['var_95'] = compute_var(result['returns'], 0.95)
        metrics['cvar_95'] = compute_cvar(result['returns'], 0.95)

        # Diversification at last rebalance
        if result['weights_history']:
            last_weights = list(result['weights_history'].values())[-1]
            div_metrics = compute_diversification_metrics(last_weights, sector_map, result['returns'])
            metrics.update(div_metrics)

        all_metrics.append(metrics)
        logger.info("  %s: Sharpe=%.3f, Return=%.2f%%, MaxDD=%.2f%%",
                     ptype, metrics['sharpe_ratio'],
                     metrics['annualised_return'] * 100,
                     metrics['max_drawdown'] * 100)

    # Add benchmark performance rows for context
    if len(benchmark_returns) > 0:
        bm_metrics = compute_performance_summary(
            benchmark_returns, benchmark_returns, rf_rate, 'S&P 500 (benchmark)',
        )
        all_metrics.append(bm_metrics)
    if len(secondary_returns) > 0:
        sec_metrics = compute_performance_summary(
            secondary_returns, benchmark_returns, rf_rate, 'MSCI World Value (IWVL.L)',
        )
        all_metrics.append(sec_metrics)
    if len(ew_universe_returns) > 0:
        ew_metrics = compute_performance_summary(
            ew_universe_returns, benchmark_returns, rf_rate, 'Equal-Weight Universe',
        )
        all_metrics.append(ew_metrics)

    # Save summary table
    summary_df = pd.DataFrame(all_metrics)
    summary_path = os.path.join(args.output_dir, 'tables', 'performance_summary.csv')
    summary_df.to_csv(summary_path, index=False)
    logger.info("Performance summary saved to %s", summary_path)

    # --- Table 11: Backtesting pitfalls addressed ---
    pitfalls_df = build_pitfalls_table(config)
    pitfalls_path = os.path.join(args.output_dir, 'tables', 'backtesting_pitfalls.csv')
    pitfalls_df.to_csv(pitfalls_path, index=False)
    logger.info("Backtesting pitfalls table saved to %s (%d rows)", pitfalls_path, len(pitfalls_df))

    # --- Diversification through time (combined portfolio) ---
    div_over_time = pd.DataFrame()
    if 'combined' in results and results['combined']['weights_history']:
        div_over_time = compute_diversification_over_time(
            results['combined']['weights_history'], sector_map,
        )
        div_path = os.path.join(args.output_dir, 'tables', 'diversification_over_time.csv')
        div_over_time.to_csv(div_path)
        logger.info("Diversification over time saved to %s", div_path)

    # Top 3 drawdown events (Table 7)
    if 'combined' in results and len(results['combined']['returns']) > 0:
        top_dd = compute_top_drawdowns(results['combined']['returns'], n=3)
        top_dd_path = os.path.join(args.output_dir, 'tables', 'top_drawdowns.csv')
        top_dd.to_csv(top_dd_path, index=False)
        logger.info("Top drawdowns saved to %s", top_dd_path)

    # Fama-French regression for combined portfolio
    if 'combined' in results:
        logger.info("Running Fama-French 5-factor regression...")
        ff_result = compute_fama_french_regression(results['combined']['returns'])
        ff_path = os.path.join(args.output_dir, 'tables', 'fama_french_regression.csv')
        ff_df = pd.DataFrame([{
            'Factor': 'Alpha (annualised)',
            'Coefficient': ff_result['alpha_annualised'],
            't-stat': ff_result['alpha_tstat'],
            'p-value': ff_result['alpha_pvalue'],
        }])
        for factor in ff_result['betas']:
            ff_df = pd.concat([ff_df, pd.DataFrame([{
                'Factor': factor,
                'Coefficient': ff_result['betas'][factor],
                't-stat': ff_result['tstats'][factor],
                'p-value': ff_result['pvalues'][factor],
            }])], ignore_index=True)
        ff_df.to_csv(ff_path, index=False)

    # Weighting scheme comparison table (guide A5 / C2 Table 6)
    if weighting_results:
        logger.info("Computing weighting scheme comparison...")
        weighting_metrics = []
        for label, result in weighting_results.items():
            wm = compute_performance_summary(
                result['returns'], benchmark_returns, rf_rate, label,
            )
            turnover_sm = compute_turnover_summary(result['turnover'], result['costs'])
            wm.update(turnover_sm)
            weighting_metrics.append(wm)
        weighting_df = pd.DataFrame(weighting_metrics)
        weighting_path = os.path.join(args.output_dir, 'tables', 'weighting_scheme_comparison.csv')
        weighting_df.to_csv(weighting_path, index=False)
        logger.info("Weighting scheme comparison saved to %s", weighting_path)

    # --- Step 6: Robustness testing ---
    weight_df = None
    threshold_df = None
    if not args.skip_robustness and 'combined' in results:
        logger.info("--- STEP 6: Robustness testing ---")
        from modules.robustness.bootstrap import stationary_bootstrap_sharpe
        from modules.robustness.random_portfolios import random_portfolio_test
        from modules.robustness.sensitivity import (
            sub_period_analysis,
            weight_sensitivity_analysis,
            threshold_sensitivity_analysis,
            sector_attribution_analysis,
        )

        # Test 3: Sub-period / year-by-year analysis (Table 3)
        logger.info("Test 3: Sub-period analysis (year-by-year)...")
        subperiod_df = sub_period_analysis(
            results['combined']['returns'], benchmark_returns,
        )
        subperiod_path = os.path.join(args.output_dir, 'tables', 'sub_period_analysis.csv')
        subperiod_df.to_csv(subperiod_path, index=False)

        # Test 4: Bootstrap CIs (Sharpe + return + vol + MaxDD)
        logger.info("Test 4: Bootstrap confidence intervals (2500 reps)...")
        bootstrap_result = stationary_bootstrap_sharpe(
            results['combined']['returns'],
            n_reps=2500, risk_free_rate=rf_rate,
        )
        bootstrap_path = os.path.join(args.output_dir, 'tables', 'bootstrap_ci.csv')
        pd.DataFrame([
            {
                'Metric': 'Sharpe Ratio',
                'Point Estimate': bootstrap_result['point_estimate'],
                'CI Lower (95%)': bootstrap_result['ci_lower'],
                'CI Upper (95%)': bootstrap_result['ci_upper'],
                'P(Metric > 0)': bootstrap_result['prob_sharpe_positive'],
            },
            {
                'Metric': 'Annualised Return',
                'Point Estimate': bootstrap_result['return_point'],
                'CI Lower (95%)': bootstrap_result['return_ci_lower'],
                'CI Upper (95%)': bootstrap_result['return_ci_upper'],
                'P(Metric > 0)': float('nan'),
            },
            {
                'Metric': 'Annualised Volatility',
                'Point Estimate': bootstrap_result['vol_point'],
                'CI Lower (95%)': bootstrap_result['vol_ci_lower'],
                'CI Upper (95%)': bootstrap_result['vol_ci_upper'],
                'P(Metric > 0)': float('nan'),
            },
            {
                'Metric': 'Max Drawdown',
                'Point Estimate': bootstrap_result['max_dd_point'],
                'CI Lower (95%)': bootstrap_result['max_dd_ci_lower'],
                'CI Upper (95%)': bootstrap_result['max_dd_ci_upper'],
                'P(Metric > 0)': float('nan'),
            },
        ]).to_csv(bootstrap_path, index=False)

        # Test 5: Random portfolios
        logger.info("Test 5: Random portfolio comparison (10,000 simulations)...")
        daily_rets = prices.pct_change().dropna(how='all')
        strategy_sharpe = next(
            m['sharpe_ratio'] for m in all_metrics if m['portfolio'] == 'combined'
        )
        random_result = random_portfolio_test(
            daily_rets, strategy_sharpe,
            n_holdings=40, n_simulations=10000,
            risk_free_rate=rf_rate,
        )
        random_path = os.path.join(args.output_dir, 'tables', 'random_portfolios.csv')
        pd.DataFrame([{
            'Strategy Sharpe': random_result['strategy_sharpe'],
            'Random Mean': random_result['random_mean'],
            'Random Std': random_result['random_std'],
            'Percentile Rank': random_result['percentile_rank'],
            'P(Random Beats)': random_result['prob_random_beats'],
        }]).to_csv(random_path, index=False)

        # --- Tests 1, 2, 6: Config-varying sensitivity analyses ---
        # These re-run the backtest with modified config per combination.
        def run_with_config(cfg):
            bt = Backtester(loader, universe, cfg)
            res = bt.run(prices, portfolio_type='combined')
            return res['returns']

        # Test 1: Weight sensitivity (Table 4)
        logger.info("Test 1: Weight sensitivity (value/sentiment mix)...")
        # PDF §A8 specifies 5% increments → 21 weight combinations
        weight_df = weight_sensitivity_analysis(run_with_config, config, steps=21)
        weight_path = os.path.join(args.output_dir, 'tables', 'weight_sensitivity.csv')
        weight_df.to_csv(weight_path, index=False)

        # Test 2: Threshold sensitivity (Table 5)
        logger.info("Test 2: Threshold sensitivity (selection pctl × D/E)...")
        threshold_df = threshold_sensitivity_analysis(run_with_config, config)
        threshold_path = os.path.join(args.output_dir, 'tables', 'threshold_sensitivity.csv')
        threshold_df.to_csv(threshold_path, index=False)

        # Test 6: Sector attribution (leave-one-out)
        logger.info("Test 6: Sector attribution (leave-one-sector-out)...")
        sectors = sorted({s for s in sector_map.values() if s})
        sector_df = sector_attribution_analysis(run_with_config, config, sectors)
        sector_path = os.path.join(args.output_dir, 'tables', 'sector_attribution.csv')
        sector_df.to_csv(sector_path, index=False)

    # --- Step 7: Generate charts ---
    if not args.skip_charts:
        logger.info("--- STEP 7: Generating charts ---")
        from modules.visualization.charts import (
            plot_cumulative_returns,
            plot_drawdown,
            plot_monthly_heatmap,
            plot_rolling_sharpe,
            plot_weight_sensitivity_heatmap,
            plot_factor_loadings,
            plot_sector_allocation,
            plot_random_portfolio_histogram,
            plot_turnover_per_rebalance,
            plot_threshold_sensitivity,
            plot_old_vs_new_value_scores,
            plot_pipeline_flowchart,
            plot_diversification_over_time,
            plot_cumulative_cost_impact,
            plot_executive_summary_card,
        )
        from modules.visualization.tearsheet import generate_tearsheet

        chart_dir = os.path.join(args.output_dir, 'charts')

        # Chart 1: Cumulative returns (portfolios + EW universe overlay)
        port_returns = {name: r['returns'] for name, r in results.items()}
        if len(ew_universe_returns) > 0:
            port_returns['ew_universe'] = ew_universe_returns
        plot_cumulative_returns(port_returns, benchmark_returns,
                                os.path.join(chart_dir, 'cumulative_returns.png'))

        # Chart 2: Drawdown
        if 'combined' in results:
            plot_drawdown(results['combined']['returns'], 'Combined',
                          os.path.join(chart_dir, 'drawdown.png'))

        # Chart 3: Monthly heatmap
        if 'combined' in results:
            plot_monthly_heatmap(results['combined']['returns'],
                                 os.path.join(chart_dir, 'monthly_heatmap.png'))

        # Chart 4: Rolling Sharpe
        plot_rolling_sharpe(port_returns,
                            output_path=os.path.join(chart_dir, 'rolling_sharpe.png'))

        # Chart 5: Weight sensitivity heatmap
        if weight_df is not None and len(weight_df) > 0:
            plot_weight_sensitivity_heatmap(
                weight_df, os.path.join(chart_dir, 'weight_sensitivity.png'),
            )

        # Chart 6: Factor loadings
        if 'combined' in results and ff_result:
            plot_factor_loadings(ff_result,
                                 os.path.join(chart_dir, 'factor_loadings.png'))

        # Chart 7: Sector allocation
        if 'combined' in results and results['combined']['weights_history']:
            last_w = list(results['combined']['weights_history'].values())[-1]
            sect_alloc = compute_sector_allocation(last_w, sector_map)
            plot_sector_allocation(sect_alloc,
                                   output_path=os.path.join(chart_dir, 'sector_allocation.png'))

        # Chart 8: Random portfolios
        if random_result is not None:
            plot_random_portfolio_histogram(random_result,
                                            os.path.join(chart_dir, 'random_portfolios.png'))

        # Chart 9: Threshold sensitivity
        if threshold_df is not None and len(threshold_df) > 0:
            plot_threshold_sensitivity(
                threshold_df, os.path.join(chart_dir, 'threshold_sensitivity.png'),
            )

        # Chart 10: Turnover
        if 'combined' in results:
            plot_turnover_per_rebalance(results['combined']['rebalance_info'],
                                        os.path.join(chart_dir, 'turnover.png'))

        # QuantStats tearsheet
        if 'combined' in results:
            generate_tearsheet(
                results['combined']['returns'],
                benchmark_returns,
                'Value-Sentiment Combined Strategy',
                os.path.join(chart_dir, 'tearsheet.html'),
            )

        # Chart 11 + Tables 9/10: OLD vs NEW signal sector concentration
        if 'combined' in results:
            logger.info("Generating Chart 11 + Tables 9/10: OLD vs NEW signals...")
            try:
                latest_rebal = sorted(results['combined']['weights_history'].keys())[-1]
                data_date = (latest_rebal - pd.Timedelta(days=config['backtest']['reporting_lag_days']))
                old_scores = loader.load_composite_rankings(data_date.strftime('%Y-%m-%d'))
                new_value_df = loader.load_value_metrics(data_date.strftime('%Y-%m-%d'))
                from modules.signals.value_signal import ValueSignal
                vs = ValueSignal(config)
                new_scores = vs.compute(new_value_df, sector_map)
                plot_old_vs_new_value_scores(
                    old_scores, new_scores, sector_map,
                    os.path.join(chart_dir, 'old_vs_new_value.png'),
                )

                # Table 9: OLD vs NEW value sector concentration (top quintile)
                value_compare = _build_top_quintile_sector_table(
                    old_scores, new_scores, sector_map, score_col='value_score',
                )
                value_compare.to_csv(
                    os.path.join(args.output_dir, 'tables', 'old_vs_new_value.csv'),
                    index=False,
                )

                # Table 10: OLD vs NEW sentiment sector concentration
                old_sent_df = loader.load_sentiment_scores(data_date.strftime('%Y-%m-%d'))
                from modules.signals.sentiment_signal import SentimentSignal
                ss = SentimentSignal(config)
                new_sent = ss.compute(
                    loader.load_news_article_metadata(data_date.strftime('%Y-%m-%d')),
                    latest_rebal,
                )
                sent_compare = _build_top_quintile_sector_table(
                    old_sent_df, new_sent, sector_map,
                    old_col='avg_sentiment', new_col='sentiment_score',
                )
                sent_compare.to_csv(
                    os.path.join(args.output_dir, 'tables', 'old_vs_new_sentiment.csv'),
                    index=False,
                )
            except Exception as e:
                logger.warning("Chart 11 / Tables 9-10 generation failed: %s", e)

        # Chart 12: Pipeline flowchart (CW1→CW2)
        plot_pipeline_flowchart(os.path.join(chart_dir, 'pipeline_flowchart.png'))

        # Chart 13: Diversification over time (HHI / sectors / max sector)
        if len(div_over_time) > 0:
            plot_diversification_over_time(
                div_over_time,
                os.path.join(chart_dir, 'diversification_over_time.png'),
            )

        # Chart 14: Cumulative cost-impact drag
        if 'combined' in results and len(results['combined']['rebalance_info']) > 0:
            plot_cumulative_cost_impact(
                results['combined']['rebalance_info'],
                os.path.join(chart_dir, 'cost_impact.png'),
            )

        # Executive summary card (one-page fact sheet for the report cover)
        bootstrap_dict = None
        if not args.skip_robustness and 'combined' in results:
            try:
                bootstrap_dict = {
                    'point_estimate': bootstrap_result['point_estimate'],
                    'ci_lower': bootstrap_result['ci_lower'],
                    'ci_upper': bootstrap_result['ci_upper'],
                    'prob_sharpe_positive': bootstrap_result['prob_sharpe_positive'],
                }
            except (NameError, KeyError):
                bootstrap_dict = None
        plot_executive_summary_card(
            all_metrics,
            bootstrap_result=bootstrap_dict,
            ff_result=ff_result,
            random_result=random_result,
            output_path=os.path.join(chart_dir, 'executive_summary.png'),
        )

    # --- Step 7b: Appendix B — complete backtest results (monthly × portfolio) ---
    # Part C §C3 Appendix B: "Complete backtest results (all months, all portfolios)"
    try:
        monthly_rows = []
        for ptype, result in results.items():
            rets = result.get('returns')
            if rets is None or len(rets) == 0:
                continue
            monthly = rets.resample('ME').apply(lambda x: (1 + x).prod() - 1)
            for date, ret in monthly.items():
                monthly_rows.append({
                    'portfolio': ptype,
                    'month': date.strftime('%Y-%m'),
                    'return': float(ret),
                })
        if monthly_rows:
            appendix_b_path = os.path.join(
                args.output_dir, 'tables', 'appendix_b_monthly_returns.csv',
            )
            pd.DataFrame(monthly_rows).pivot(
                index='month', columns='portfolio', values='return',
            ).to_csv(appendix_b_path)
            logger.info('Appendix B saved: %s', appendix_b_path)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning('Appendix B generation failed: %s', exc)

    # --- Step 8: Auto-generated appendices (F, G, H) ---
    logger.info("--- STEP 8: Generating appendices F, G, H ---")
    try:
        appendix_paths = write_all_appendices(loader, config, args.output_dir)
        for label, path in appendix_paths.items():
            logger.info("  Appendix %s -> %s", label, path)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Appendix generation failed: %s", exc)

    # --- Final summary ---
    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info("  BACKTEST PIPELINE COMPLETE")
    logger.info("  Elapsed time: %.1f seconds", elapsed)
    logger.info("  Output directory: %s", args.output_dir)
    logger.info("=" * 70)

    # Print summary table
    if all_metrics:
        print("\n" + "=" * 110)
        print("PERFORMANCE SUMMARY (per Part C §C2 Table 1)")
        print("=" * 110)
        header = (
            f"{'Portfolio':<28} {'Return':>9} {'Vol':>9} "
            f"{'Sharpe':>9} {'Sortino':>9} {'Calmar':>9} "
            f"{'MaxDD':>9} {'IR':>9}"
        )
        print(header)
        print("-" * 110)
        for m in all_metrics:
            print(
                f"{m['portfolio']:<28} "
                f"{m['annualised_return']*100:>8.2f}% "
                f"{m['annualised_volatility']*100:>8.2f}% "
                f"{m['sharpe_ratio']:>9.3f} "
                f"{m.get('sortino_ratio', 0):>9.3f} "
                f"{m.get('calmar_ratio', 0):>9.3f} "
                f"{m['max_drawdown']*100:>8.2f}% "
                f"{m.get('information_ratio', 0):>9.3f}"
            )
        print("=" * 110)


if __name__ == '__main__':
    run_pipeline()
