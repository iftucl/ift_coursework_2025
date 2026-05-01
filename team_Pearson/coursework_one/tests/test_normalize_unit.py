from modules.output.normalize import normalize_financial_records, normalize_records


def test_normalize_from_alternative_keys_and_type_cast():
    raw = [
        {
            "symbol": "SYM00001",
            "date": "2026-02-14T12:00:00Z",
            "metric": "pb_ratio",
            "value": "1.2",
        }
    ]
    out = normalize_records(raw)

    assert len(out) == 1
    assert out[0]["symbol"] == "SYM00001"
    assert out[0]["observation_date"] == "2026-02-14"
    assert out[0]["factor_name"] == "pb_ratio"
    assert out[0]["factor_value"] == 1.2
    assert out[0]["source"] == "unknown"
    assert out[0]["metric_frequency"] == "unknown"


def test_normalize_prefers_explicit_factor_value():
    raw = [
        {
            "symbol": "SYM00002",
            "observation_date": "2026-02-14",
            "factor_name": "debt_to_equity",
            "factor_value": 3.0,
            "value": 99.0,
            "source": "alpha_vantage",
            "metric_frequency": "DAILY",
        }
    ]
    out = normalize_records(raw)
    assert out[0]["observation_date"] == "2026-02-14"
    assert out[0]["factor_value"] == 3.0
    assert out[0]["source"] == "alpha_vantage"
    assert out[0]["metric_frequency"] == "daily"


def test_normalize_empty_or_nan_values_become_none():
    raw = [
        {
            "symbol": "SYM00003",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_nan",
            "factor_value": "NaN",
        },
        {
            "symbol": "SYM00004",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_empty",
            "value": "",
        },
    ]
    out = normalize_records(raw)
    assert out[0]["factor_value"] is None
    assert out[1]["factor_value"] is None


def test_normalize_drops_invalid_observation_date():
    raw = [
        {
            "symbol": "SYM1",
            "observation_date": "2026-02-14",
            "factor_name": "test_factor_valid",
            "value": 1.0,
        },
        {
            "symbol": "SYM2",
            "observation_date": "NaT",
            "factor_name": "test_factor_nat",
            "value": 2.0,
        },
        {
            "symbol": "SYM3",
            "observation_date": "",
            "factor_name": "test_factor_empty_date",
            "value": 3.0,
        },
    ]
    out = normalize_records(raw)
    assert len(out) == 1
    assert out[0]["symbol"] == "SYM1"


def test_normalize_financial_records_maps_semantic_fields():
    raw = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-02-14",
            "factor_name": "enterprise_revenue",
            "value": "123.4",
            "source": "alpha_vantage",
            "period_type": "ttm",
            "currency": "usd",
            "source_report_date": "2025-12-31",
            "metric_definition": "provider_reported",
        }
    ]
    out = normalize_financial_records(raw)
    assert len(out) == 1
    row = out[0]
    assert row["symbol"] == "AAPL"
    assert row["metric_name"] == "enterprise_revenue"
    assert row["metric_value"] == 123.4
    assert row["report_date"] == "2025-12-31"
    assert row["as_of"] == "2026-02-14"
    assert row["period_type"] == "ttm"
    assert row["currency"] == "USD"


def test_normalize_financial_records_requires_real_report_date():
    raw = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-02-14",
            "factor_name": "total_debt",
            "value": "1000",
            "source": "alpha_vantage",
            "period_type": "quarterly",
        }
    ]
    out = normalize_financial_records(raw)
    assert out == []
