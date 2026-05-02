"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Unit tests for the backtesting-pitfalls audit table
Project : CW2 - Value-Sentiment Investment Strategy
"""

import pandas as pd

from modules.analytics.pitfalls import build_pitfalls_table


REQUIRED_PITFALLS = {
    'Look-ahead bias',
    'Survivorship bias',
    'Execution timing optimism',
    'Zero transaction costs',
    'Static-weight return calculation',
    'Sector concentration (HML overweights Financials/Utilities)',
    'Overweighting wire-copy news',
    'Multiple-testing / data snooping',
    'IID-bootstrap mis-specification',
    'OLS standard-error mis-specification',
    'Concentration risk hidden by averages',
    'Backtest length too short for regime coverage',
}


class TestPitfallsTable:

    def test_returns_dataframe_with_required_columns(self):
        df = build_pitfalls_table()
        assert isinstance(df, pd.DataFrame)
        for col in ['pitfall', 'risk', 'mitigation', 'location', 'status']:
            assert col in df.columns

    def test_all_required_pitfalls_present(self):
        df = build_pitfalls_table()
        present = set(df['pitfall'])
        missing = REQUIRED_PITFALLS - present
        assert not missing, f"Missing pitfalls: {missing}"

    def test_all_status_pass(self):
        df = build_pitfalls_table()
        assert (df['status'] == 'PASS').all()

    def test_config_injection(self):
        cfg = {
            'backtest': {'reporting_lag_days': 75, 'execution_delay': 1, 'rebalance_frequency': 'monthly'},
            'costs': {'transaction_cost_bps': 10, 'stress_test_bps': 20},
        }
        df = build_pitfalls_table(cfg)
        # Lag days from cfg should appear in mitigation text
        lag_row = df[df['pitfall'] == 'Look-ahead bias']
        assert '75-day' in lag_row['mitigation'].iloc[0]
        # Cost bps from cfg should appear
        cost_row = df[df['pitfall'] == 'Zero transaction costs']
        assert '10 bps' in cost_row['mitigation'].iloc[0]

    def test_locations_point_to_real_paths(self):
        df = build_pitfalls_table()
        for loc in df['location']:
            assert 'modules/' in loc, f"Location should reference modules/: {loc}"
