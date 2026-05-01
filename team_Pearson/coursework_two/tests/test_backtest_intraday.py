"""Unit tests for the CW2 daily trigger overlay."""

import math
from datetime import date
from types import SimpleNamespace

import pandas as pd
from team_Pearson.coursework_two.modules.backtest import intraday as intraday_mod
from team_Pearson.coursework_two.modules.backtest.intraday import run_intraday_period


def _config(
    *, enabled: bool = True, save_daily_state: bool = False, **intraday_overrides: object
) -> dict:
    intraday = {
        "enabled": enabled,
        "stock_stop_loss_pct": -0.07,
        "vix_spike_pct": 0.20,
        "vix_recovery_threshold": 25.0,
        "vix_recovery_consecutive_days": 5,
        "regime_switch_mode": "next_day_rebalance",
        "transaction_cost_bps": 15,
        "save_daily_state": save_daily_state,
    }
    intraday.update(intraday_overrides)
    return {
        "backtest": {
            "transaction_cost_bps": 15,
            "max_forward_fill_days": 5,
            "intraday_triggers": intraday,
        }
    }


def _panel(rows: dict[str, list[float]]) -> pd.DataFrame:
    idx = [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
    ]
    return pd.DataFrame(rows, index=idx)


def test_no_trigger_when_disabled():
    close_panel = _panel({"AAA": [100.0, 103.0, 105.0]})
    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(enabled=False),
    )
    assert math.isclose(result.period_gross_return, 0.05, rel_tol=0, abs_tol=1e-12)
    assert result.total_intraday_cost == 0.0
    assert result.events == []


def test_publish_requested_risk_action_records_ops_event_when_monitor_engine_provided(
    monkeypatch,
):
    captured = {}

    monkeypatch.setattr(intraday_mod, "publish_json_events", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        intraday_mod,
        "resolve_kafka_config",
        lambda config, *, default_client_id: SimpleNamespace(  # noqa: ARG005
            enabled=True,
            topics={"cw2_risk_actions_requested": "cw2.risk.actions.requested.v1"},
        ),
    )
    monkeypatch.setattr(intraday_mod, "record_ops_event", lambda **kwargs: captured.update(kwargs))

    pending_action = intraday_mod.PendingRiskAction(
        event_type="news_sentiment_trim",
        action_scope="symbol",
        action_family="event_de_risk",
        urgency="high",
        reason_code="negative_sentiment_surprise",
        scheduled_for=date(2026, 1, 6),
        symbol="AAPL",
        trim_fraction=0.25,
    )

    intraday_mod._publish_requested_risk_action(
        {"kafka": {"enabled": True}},
        pending_action,
        trigger_date=date(2026, 1, 5),
        regime_before="normal",
        regime_after="normal",
        monitor_engine=object(),
        monitor_run_id="run-123",
    )

    assert captured["producer_component"] == "cw2.intraday_overlay"
    assert captured["topic_key"] == "cw2_risk_actions_requested"
    assert captured["topic_name"] == "cw2.risk.actions.requested.v1"
    assert captured["publish_status"] == "published"
    assert captured["run_id"] == "run-123"
    assert captured["symbol"] == "AAPL"


def test_period_gross_return_handles_open_gap_once():
    close_panel = _panel({"AAA": [100.0, 110.0, 110.0]})
    open_panel = _panel({"AAA": [100.0, 110.0, 110.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )
    assert math.isclose(result.period_gross_return, 0.10, rel_tol=0, abs_tol=1e-12)


def test_stop_loss_executes_at_open_when_gap_down():
    close_panel = _panel({"AAA": [100.0, 91.0, 91.0]})
    open_panel = _panel({"AAA": [100.0, 92.0, 91.0]})
    high_panel = _panel({"AAA": [101.0, 94.0, 91.0]})
    low_panel = _panel({"AAA": [99.0, 90.0, 91.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert result.intraday_stop_loss_count == 1
    assert math.isclose(result.period_gross_return, -0.08, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.final_weights["_CASH"], 1.0, rel_tol=0, abs_tol=1e-12)
    assert result.events[0]["event_type"] == "stock_stop_loss"
    assert math.isclose(result.events[0]["execution_price"], 92.0, rel_tol=0, abs_tol=1e-12)


def test_stop_loss_executes_at_barrier_when_intraday_touch():
    close_panel = _panel({"AAA": [100.0, 95.0, 95.0]})
    open_panel = _panel({"AAA": [100.0, 98.0, 95.0]})
    high_panel = _panel({"AAA": [101.0, 99.0, 95.0]})
    low_panel = _panel({"AAA": [99.0, 92.0, 95.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert result.intraday_stop_loss_count == 1
    assert math.isclose(result.period_gross_return, -0.07, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.events[0]["execution_price"], 93.0, rel_tol=0, abs_tol=1e-12)


def test_stop_loss_skips_incomplete_ohlc_bar_even_when_filled_prices_cross_threshold():
    close_panel = _panel({"AAA": [100.0, 95.0, 95.0]})
    open_panel = _panel({"AAA": [100.0, None, 95.0]})
    high_panel = _panel({"AAA": [101.0, 96.0, 95.0]})
    low_panel = _panel({"AAA": [99.0, 92.0, 95.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert result.intraday_stop_loss_count == 0
    assert result.events == []
    assert math.isclose(result.period_gross_return, -0.05, rel_tol=0, abs_tol=1e-12)


def test_stop_loss_triggers_on_low_price():
    close_panel = _panel({"AAA": [100.0, 95.0, 95.0]})
    open_panel = _panel({"AAA": [100.0, 98.0, 95.0]})
    high_panel = _panel({"AAA": [101.0, 98.5, 95.0]})
    low_panel = _panel({"AAA": [99.0, 92.5, 95.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert result.events[0]["low_price"] < 93.0
    assert math.isclose(result.events[0]["execution_price"], 93.0, rel_tol=0, abs_tol=1e-12)


def test_stop_loss_not_triggered_on_entry_date():
    close_panel = _panel({"AAA": [95.0, 96.0, 97.0]})
    open_panel = _panel({"AAA": [100.0, 95.0, 96.0]})
    high_panel = _panel({"AAA": [101.0, 97.0, 98.0]})
    low_panel = _panel({"AAA": [90.0, 94.0, 95.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert result.intraday_stop_loss_count == 0
    assert result.events == []
    assert "AAA" in result.final_weights


def test_entry_day_open_missing_falls_back_to_close():
    close_panel = _panel({"AAA": [100.0, 101.0, 102.0]})
    open_panel = _panel({"AAA": [float("nan"), 101.0, 102.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert result.intraday_stop_loss_count == 0
    assert "AAA" in result.final_weights
    assert "_CASH" not in result.final_weights


def test_stop_loss_converts_weight_to_cash():
    close_panel = _panel({"AAA": [100.0, 91.0, 91.0]})
    open_panel = _panel({"AAA": [100.0, 92.0, 91.0]})
    high_panel = _panel({"AAA": [101.0, 94.0, 91.0]})
    low_panel = _panel({"AAA": [99.0, 90.0, 91.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(save_daily_state=True),
    )

    assert "AAA" not in result.final_weights
    assert math.isclose(result.final_weights["_CASH"], 1.0, rel_tol=0, abs_tol=1e-12)
    assert any(row["symbol"] == "_CASH" for row in result.daily_state)


def test_vix_regime_rebalance_creates_turnover_and_cost():
    close_panel = _panel(
        {
            "AAA": [100.0, 100.0, 100.0],
            "BBB": [100.0, 100.0, 102.0],
        }
    )
    open_panel = _panel(
        {
            "AAA": [100.0, 100.0, 100.0],
            "BBB": [100.0, 100.0, 100.0],
        }
    )
    high_panel = close_panel.copy()
    low_panel = close_panel.copy()

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"BBB": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 25.0, 24.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert result.intraday_regime_switch_count == 1
    assert math.isclose(result.total_intraday_cost, 0.003, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.period_gross_return, 0.02, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.final_weights["BBB"], 1.0, rel_tol=0, abs_tol=1e-12)
    assert result.events[0]["event_type"] == "vix_spike_regime"
    assert result.events[0]["rebalance_scheduled_for"] == date(2026, 1, 7)


def test_vix_recovery_requires_consecutive_days():
    idx = [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 12),
        date(2026, 1, 13),
        date(2026, 1, 14),
    ]
    close_panel = pd.DataFrame({"AAA": [100.0] * len(idx), "BBB": [100.0] * len(idx)}, index=idx)
    open_panel = close_panel.copy()
    high_panel = close_panel.copy()
    low_panel = close_panel.copy()
    vix = pd.Series([20.0, 25.0, 24.0, 24.0, 24.0, 24.0, 24.0, 24.0], index=idx)

    result = run_intraday_period(
        execution_date=idx[0],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"BBB": 1.0},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=vix,
        initial_target_variant="normal",
        config=_config(),
    )

    event_types = [event["event_type"] for event in result.events]
    assert event_types == ["vix_spike_regime", "vix_recovery_regime"]
    assert result.events[1]["rebalance_scheduled_for"] == date(2026, 1, 14)


def test_vix_recovery_resets_on_spike():
    idx = [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 12),
        date(2026, 1, 13),
        date(2026, 1, 14),
    ]
    close_panel = pd.DataFrame({"AAA": [100.0] * len(idx), "BBB": [100.0] * len(idx)}, index=idx)
    vix = pd.Series([20.0, 25.0, 24.0, 24.0, 24.0, 26.0, 24.0, 24.0], index=idx)

    result = run_intraday_period(
        execution_date=idx[0],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"BBB": 1.0},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=vix,
        initial_target_variant="normal",
        config=_config(),
    )

    assert [event["event_type"] for event in result.events] == ["vix_spike_regime"]


def test_intraday_cost_added_on_stop_loss():
    close_panel = _panel({"AAA": [100.0, 91.0, 91.0]})
    open_panel = _panel({"AAA": [100.0, 92.0, 91.0]})
    high_panel = _panel({"AAA": [101.0, 94.0, 91.0]})
    low_panel = _panel({"AAA": [99.0, 90.0, 91.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert math.isclose(result.total_intraday_cost, 0.00138, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.events[0]["transaction_cost"], 0.00138, rel_tol=0, abs_tol=1e-12)


def test_missing_vix_data_skips_vix_check():
    close_panel = _panel({"AAA": [100.0, 100.0, 100.0], "BBB": [100.0, 100.0, 100.0]})
    vix = pd.Series([20.0, float("nan"), 30.0], index=close_panel.index)

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"BBB": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=vix,
        initial_target_variant="normal",
        config=_config(),
    )

    assert result.intraday_regime_switch_count == 0
    assert result.events == []


def test_vix_spike_requires_absolute_level_gate():
    close_panel = _panel({"AAA": [100.0, 100.0, 100.0], "BBB": [100.0, 100.0, 100.0]})
    vix = pd.Series([10.0, 12.5, 12.5], index=close_panel.index)

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"BBB": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=vix,
        initial_target_variant="normal",
        config=_config(vix_spike_min_level=25.0),
    )

    assert result.intraday_regime_switch_count == 0
    assert result.events == []


def test_vix_spike_can_require_term_spread_confirmation():
    close_panel = _panel({"AAA": [100.0, 100.0, 100.0], "BBB": [100.0, 100.0, 100.0]})
    vix = pd.Series([20.0, 25.0, 25.0], index=close_panel.index)
    term_spread = pd.Series([0.5, 0.4, 0.4], index=close_panel.index)

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"BBB": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=vix,
        term_spread_series=term_spread,
        initial_target_variant="normal",
        config=_config(
            vix_spike_min_level=25.0,
            term_spread_confirm_enabled=True,
            term_spread_stress_threshold=0.0,
            vix_hard_stress_level=35.0,
        ),
    )

    assert result.intraday_regime_switch_count == 0
    assert result.events == []


def test_final_weights_sum_to_one():
    close_panel = _panel({"AAA": [100.0, 91.0, 91.0], "BBB": [100.0, 101.0, 101.0]})
    open_panel = _panel({"AAA": [100.0, 92.0, 91.0], "BBB": [100.0, 101.0, 101.0]})
    high_panel = _panel({"AAA": [101.0, 94.0, 91.0], "BBB": [100.0, 101.0, 101.0]})
    low_panel = _panel({"AAA": [99.0, 90.0, 91.0], "BBB": [100.0, 101.0, 101.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 0.5, "BBB": 0.5},
        stress_target_weights={"AAA": 0.5, "BBB": 0.5},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 20.0, 20.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(),
    )

    assert math.isclose(sum(result.final_weights.values()), 1.0, rel_tol=0, abs_tol=1e-12)


def test_weekly_mid_frequency_rebalance_recenters_drifted_weights():
    idx = [d.date() for d in pd.bdate_range("2026-01-05", periods=7)]
    close_panel = pd.DataFrame(
        {
            "AAA": [100.0, 110.0, 115.0, 120.0, 125.0, 130.0, 131.0],
            "BBB": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        },
        index=idx,
    )
    result = run_intraday_period(
        execution_date=idx[0],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 0.5, "BBB": 0.5},
        stress_target_weights={"AAA": 0.5, "BBB": 0.5},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0] * len(idx), index=idx),
        initial_target_variant="normal",
        config=_config(
            mid_frequency_rebalance_enabled=True,
            mid_frequency_rebalance_weekday=0,
            mid_frequency_min_turnover=0.01,
        ),
    )

    weekly_events = [
        event for event in result.events if event["event_type"] == "weekly_target_rebalance"
    ]
    assert len(weekly_events) == 1
    assert result.total_intraday_cost > 0.0


def test_vol_scaled_stop_loss_uses_tighter_threshold_for_low_vol_name():
    idx = [d.date() for d in pd.bdate_range("2026-01-01", periods=22)]
    closes = []
    price = 100.0
    for i in range(len(idx) - 1):
        price *= 1.005 if i % 2 == 0 else 0.995
        closes.append(price)
    closes.append(99.0)

    close_panel = pd.DataFrame({"AAA": closes}, index=idx)
    open_values = list(close_panel["AAA"])
    open_values[-2] = 100.0
    open_values[-1] = 100.0
    open_panel = pd.DataFrame({"AAA": open_values}, index=idx)
    high_panel = open_panel.copy()
    low_panel = open_panel.copy()
    low_panel.iloc[-1, 0] = 96.5

    result = run_intraday_period(
        execution_date=idx[-2],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0] * len(idx), index=idx),
        initial_target_variant="normal",
        config=_config(
            stop_loss_mode="vol_scaled",
            stop_loss_vol_lookback_days=20,
            stop_loss_min_history_days=10,
            stop_loss_vol_multiplier=2.0,
            stop_loss_min_abs_pct=0.03,
            stop_loss_max_abs_pct=0.12,
        ),
    )

    assert result.intraday_stop_loss_count == 1
    assert math.isclose(result.events[0]["stop_loss_threshold"], -0.03, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.events[0]["execution_price"], 97.0, rel_tol=0, abs_tol=1e-12)


def test_stopped_names_do_not_reenter_by_default_on_regime_rebalance():
    close_panel = _panel({"AAA": [100.0, 91.0, 91.0]})
    open_panel = _panel({"AAA": [100.0, 92.0, 91.0]})
    high_panel = _panel({"AAA": [101.0, 94.0, 91.0]})
    low_panel = _panel({"AAA": [99.0, 90.0, 91.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 25.0, 25.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(
            vix_spike_min_level=25.0,
            allow_reentry_after_stop_loss=False,
        ),
    )

    assert "AAA" not in result.final_weights
    assert math.isclose(result.final_weights["_CASH"], 1.0, rel_tol=0, abs_tol=1e-12)


def test_stopped_names_can_reenter_when_config_enabled():
    close_panel = _panel({"AAA": [100.0, 91.0, 91.0]})
    open_panel = _panel({"AAA": [100.0, 92.0, 91.0]})
    high_panel = _panel({"AAA": [101.0, 94.0, 91.0]})
    low_panel = _panel({"AAA": [99.0, 90.0, 91.0]})

    result = run_intraday_period(
        execution_date=date(2026, 1, 5),
        next_execution_date=date(2026, 1, 7),
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=list(close_panel.index),
        price_panel=close_panel,
        open_panel=open_panel,
        high_panel=high_panel,
        low_panel=low_panel,
        vix_series=pd.Series([20.0, 25.0, 25.0], index=close_panel.index),
        initial_target_variant="normal",
        config=_config(vix_spike_min_level=25.0, allow_reentry_after_stop_loss=True),
    )

    assert math.isclose(result.final_weights["AAA"], 1.0, rel_tol=0, abs_tol=1e-12)
    assert "_CASH" not in result.final_weights


def test_news_sentiment_shock_trims_position_next_day():
    idx = [d.date() for d in pd.bdate_range("2026-01-05", periods=4)]
    close_panel = pd.DataFrame({"AAA": [100.0, 100.0, 100.0, 100.0]}, index=idx)
    signal_panels = {
        "sentiment_surprise": pd.DataFrame({"AAA": [None, -0.25, -0.25, -0.25]}, index=idx),
        "article_count_30d": pd.DataFrame({"AAA": [0.0, 8.0, 8.0, 8.0]}, index=idx),
        "sentiment_7d_avg": pd.DataFrame({"AAA": [0.0, -0.1, -0.1, -0.1]}, index=idx),
    }

    result = run_intraday_period(
        execution_date=idx[0],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0] * len(idx), index=idx),
        event_signal_panels=signal_panels,
        initial_target_variant="normal",
        config=_config(
            event_driven_enabled=True,
            news_sentiment_shock_enabled=True,
            news_sentiment_surprise_threshold=-0.15,
            news_sentiment_min_article_count=5.0,
            news_sentiment_trim_fraction=0.5,
            event_cooldown_days=5,
        ),
    )

    trim_events = [event for event in result.events if event["event_type"] == "news_sentiment_trim"]
    assert len(trim_events) == 1
    assert trim_events[0]["action_scope"] == "symbol"
    assert trim_events[0]["reason_code"] == "negative_sentiment_surprise"
    assert math.isclose(trim_events[0]["weight_before"], 1.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trim_events[0]["weight_after"], 0.5, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.final_weights["AAA"], 0.5, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.final_weights["_CASH"], 0.5, rel_tol=0, abs_tol=1e-12)


def test_news_sentiment_shock_respects_cooldown():
    idx = [d.date() for d in pd.bdate_range("2026-01-05", periods=5)]
    close_panel = pd.DataFrame({"AAA": [100.0] * len(idx)}, index=idx)
    signal_panels = {
        "sentiment_surprise": pd.DataFrame({"AAA": [None, -0.25, -0.30, -0.35, -0.40]}, index=idx),
        "article_count_30d": pd.DataFrame({"AAA": [0.0, 8.0, 8.0, 8.0, 8.0]}, index=idx),
    }

    result = run_intraday_period(
        execution_date=idx[0],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0] * len(idx), index=idx),
        event_signal_panels=signal_panels,
        initial_target_variant="normal",
        config=_config(
            event_driven_enabled=True,
            news_sentiment_shock_enabled=True,
            news_sentiment_surprise_threshold=-0.15,
            news_sentiment_min_article_count=5.0,
            news_sentiment_trim_fraction=0.5,
            event_cooldown_days=5,
        ),
    )

    trim_events = [event for event in result.events if event["event_type"] == "news_sentiment_trim"]
    assert len(trim_events) == 1


def test_earnings_negative_event_trims_after_publication():
    idx = [d.date() for d in pd.bdate_range("2026-02-09", periods=4)]
    close_panel = pd.DataFrame({"AAA": [100.0] * len(idx)}, index=idx)
    signal_panels = {
        "earnings_publication_flag": pd.DataFrame({"AAA": [0.0, 1.0, 0.0, 0.0]}, index=idx),
        "earnings_negative_news_count_daily": pd.DataFrame(
            {"AAA": [0.0, 2.0, 0.0, 0.0]}, index=idx
        ),
        "earnings_news_count_daily": pd.DataFrame({"AAA": [0.0, 3.0, 0.0, 0.0]}, index=idx),
    }

    result = run_intraday_period(
        execution_date=idx[0],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0] * len(idx), index=idx),
        event_signal_panels=signal_panels,
        initial_target_variant="normal",
        config=_config(
            event_driven_enabled=True,
            earnings_event_enabled=True,
            earnings_require_publication_flag=True,
            earnings_negative_news_min_count=1.0,
            earnings_trim_fraction=0.75,
            event_cooldown_days=5,
        ),
    )

    trim_events = [
        event for event in result.events if event["event_type"] == "earnings_negative_trim"
    ]
    assert len(trim_events) == 1
    assert trim_events[0]["action_family"] == "earnings_event"
    assert trim_events[0]["reason_code"] == "negative_earnings_news_after_publication"
    assert math.isclose(trim_events[0]["weight_after"], 0.25, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.final_weights["AAA"], 0.25, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.final_weights["_CASH"], 0.75, rel_tol=0, abs_tol=1e-12)


def test_rating_downgrade_event_trims_next_day():
    idx = [d.date() for d in pd.bdate_range("2026-02-09", periods=4)]
    close_panel = pd.DataFrame({"AAA": [100.0] * len(idx)}, index=idx)
    signal_panels = {
        "rating_downgrade_count_daily": pd.DataFrame({"AAA": [0.0, 1.0, 0.0, 0.0]}, index=idx),
    }

    result = run_intraday_period(
        execution_date=idx[0],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0] * len(idx), index=idx),
        event_signal_panels=signal_panels,
        initial_target_variant="normal",
        config=_config(
            event_driven_enabled=True,
            rating_downgrade_event_enabled=True,
            rating_downgrade_min_count=1.0,
            rating_trim_fraction=0.35,
            event_cooldown_days=5,
        ),
    )

    trim_events = [
        event for event in result.events if event["event_type"] == "rating_downgrade_trim"
    ]
    assert len(trim_events) == 1
    assert trim_events[0]["action_family"] == "rating_event"
    assert trim_events[0]["reason_code"] == "analyst_downgrade_news"
    assert math.isclose(result.final_weights["AAA"], 0.65, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.final_weights["_CASH"], 0.35, rel_tol=0, abs_tol=1e-12)


def test_stronger_symbol_event_replaces_weaker_pending_action():
    idx = [d.date() for d in pd.bdate_range("2026-02-09", periods=4)]
    close_panel = pd.DataFrame({"AAA": [100.0] * len(idx)}, index=idx)
    signal_panels = {
        "sentiment_surprise": pd.DataFrame({"AAA": [None, -0.25, 0.0, 0.0]}, index=idx),
        "article_count_30d": pd.DataFrame({"AAA": [0.0, 8.0, 0.0, 0.0]}, index=idx),
        "earnings_publication_flag": pd.DataFrame({"AAA": [0.0, 1.0, 0.0, 0.0]}, index=idx),
        "earnings_negative_news_count_daily": pd.DataFrame(
            {"AAA": [0.0, 1.0, 0.0, 0.0]}, index=idx
        ),
        "earnings_news_count_daily": pd.DataFrame({"AAA": [0.0, 2.0, 0.0, 0.0]}, index=idx),
    }

    result = run_intraday_period(
        execution_date=idx[0],
        next_execution_date=idx[-1],
        normal_target_weights={"AAA": 1.0},
        stress_target_weights={"AAA": 1.0},
        trading_calendar=idx,
        price_panel=close_panel,
        open_panel=close_panel,
        high_panel=close_panel,
        low_panel=close_panel,
        vix_series=pd.Series([20.0] * len(idx), index=idx),
        event_signal_panels=signal_panels,
        initial_target_variant="normal",
        config=_config(
            event_driven_enabled=True,
            news_sentiment_shock_enabled=True,
            news_sentiment_surprise_threshold=-0.15,
            news_sentiment_min_article_count=5.0,
            news_sentiment_trim_fraction=0.5,
            earnings_event_enabled=True,
            earnings_require_publication_flag=True,
            earnings_negative_news_min_count=1.0,
            earnings_trim_fraction=0.75,
            event_cooldown_days=5,
        ),
    )

    news_events = [event for event in result.events if event["event_type"] == "news_sentiment_trim"]
    earnings_events = [
        event for event in result.events if event["event_type"] == "earnings_negative_trim"
    ]
    assert news_events == []
    assert len(earnings_events) == 1
    assert math.isclose(result.final_weights["AAA"], 0.25, rel_tol=0, abs_tol=1e-12)
