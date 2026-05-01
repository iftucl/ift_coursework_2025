from modules.db.models import FactorObservation, FinancialObservation, PipelineRun


def test_factor_observation_model_core_metadata():
    table = FactorObservation.__table__
    assert table.schema == "systematic_equity"
    assert table.name == "factor_observations"
    assert {"symbol", "observation_date", "factor_name", "factor_value"}.issubset(table.c.keys())
    assert table.c["factor_value"].type.precision == 18
    assert table.c["factor_value"].type.scale == 6
    uniques = {c.name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert "uniq_observation" in uniques


def test_financial_observation_model_core_metadata():
    table = FinancialObservation.__table__
    assert table.schema == "systematic_equity"
    assert table.name == "financial_observations"
    assert {"symbol", "report_date", "metric_name", "metric_value"}.issubset(table.c.keys())
    assert table.c["metric_value"].type.precision == 24
    assert table.c["metric_value"].type.scale == 6
    uniques = {c.name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert "uniq_financial_observation" in uniques


def test_pipeline_run_model_core_metadata():
    table = PipelineRun.__table__
    assert table.schema == "systematic_equity"
    assert table.name == "pipeline_runs"
    assert {"run_id", "run_date", "started_at", "status"}.issubset(table.c.keys())
    assert table.c["run_id"].primary_key is True
