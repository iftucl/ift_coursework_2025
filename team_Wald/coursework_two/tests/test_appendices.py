"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for auto-generated appendices F, G, H
Project : CW2 - Value-Sentiment Investment Strategy
"""

import pandas as pd
import pytest

from modules.analytics.appendices import (
    build_code_quality_summary,
    build_config_dump,
)


# ---------------------------------------------------------------------------
# Appendix G — code quality summary
# ---------------------------------------------------------------------------

class TestCodeQualitySummary:

    def test_returns_dataframe_with_required_columns(self):
        df = build_code_quality_summary()
        for col in ('category', 'metric', 'value'):
            assert col in df.columns
        assert len(df) > 0

    def test_includes_test_count(self):
        df = build_code_quality_summary()
        test_cases_row = df[df['metric'] == 'test_cases']
        assert len(test_cases_row) == 1
        # We should have many test cases at this point in the project
        assert int(test_cases_row['value'].iloc[0]) >= 50

    def test_includes_source_loc(self):
        df = build_code_quality_summary()
        loc_row = df[df['metric'] == 'lines_of_code']
        assert len(loc_row) == 1
        assert int(loc_row['value'].iloc[0]) > 0

    def test_init_files_documented(self):
        df = build_code_quality_summary()
        total_inits = int(df[df['metric'] == '__init__.py_files']['value'].iloc[0])
        documented = int(df[df['metric'] == 'documented___init__.py']['value'].iloc[0])
        # All __init__.py files should have a docstring after the v2.1 pass
        assert documented == total_inits


# ---------------------------------------------------------------------------
# Appendix H — config dump
# ---------------------------------------------------------------------------

class TestConfigDump:

    def test_flattens_nested_dict(self):
        cfg = {
            'backtest': {
                'start_date': '2023-01-01',
                'rebalance_months': [1, 4, 7, 10],
            },
            'scoring': {
                'value_weight': 0.6,
                'sentiment_weight': 0.4,
                'inner': {'deeper': True},
            },
        }
        df = build_config_dump(cfg)
        params = set(df['parameter'])
        assert 'backtest.start_date' in params
        assert 'backtest.rebalance_months' in params
        assert 'scoring.value_weight' in params
        assert 'scoring.inner.deeper' in params

    def test_records_value_types(self):
        cfg = {'a': 1, 'b': 1.5, 'c': 'hello', 'd': True, 'e': [1, 2]}
        df = build_config_dump(cfg)
        type_map = dict(zip(df['parameter'], df['type']))
        assert type_map['a'] == 'int'
        assert type_map['b'] == 'float'
        assert type_map['c'] == 'str'
        assert type_map['d'] == 'bool'
        assert type_map['e'] == 'list'

    def test_handles_none(self):
        df = build_config_dump({'k': None})
        assert df['value'].iloc[0] == ''

    def test_real_backtest_config_loads(self):
        """End-to-end: actual backtest_config.yaml flattens cleanly."""
        import os
        from pathlib import Path
        import yaml
        # Resolve relative to this test file so it works regardless of CWD
        config_path = Path(__file__).resolve().parents[1] / 'config' / 'backtest_config.yaml'
        if not config_path.exists():
            pytest.skip(f"config not found at {config_path}")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        df = build_config_dump(cfg)
        # Should have all the expected top-level groups
        params = df['parameter'].tolist()
        assert any(p.startswith('backtest.') for p in params)
        assert any(p.startswith('scoring.') for p in params)
        assert any(p.startswith('portfolio.') for p in params)
        assert any(p.startswith('costs.') for p in params)
        # And the canonical 60/40 weights
        assert df[df['parameter'] == 'scoring.value_weight']['value'].iloc[0] == '0.6'
        assert df[df['parameter'] == 'scoring.sentiment_weight']['value'].iloc[0] == '0.4'
