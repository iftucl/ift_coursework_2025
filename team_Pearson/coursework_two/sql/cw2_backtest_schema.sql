-- CW2 Backtest Schema
-- Separate from feature-engineering tables; consumes precomputed
-- portfolio_target_positions and writes period-by-period backtest outputs.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_runs (
    run_id               UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    run_name             VARCHAR(100)    NOT NULL UNIQUE,
    start_date           DATE            NOT NULL,
    end_date             DATE            NOT NULL,
    rebalance_freq       VARCHAR(20)     NOT NULL DEFAULT 'monthly',
    execution_lag        SMALLINT        NOT NULL DEFAULT 1,
    transaction_cost_bps NUMERIC(10, 4)  NOT NULL DEFAULT 15.0,
    weighting            VARCHAR(30)     NOT NULL DEFAULT 'equal',
    top_n                SMALLINT        NOT NULL DEFAULT 25,
    benchmark_ticker     VARCHAR(20)     NOT NULL DEFAULT 'SPY',
    model_version        VARCHAR(60),
    factor_definition_version VARCHAR(60),
    covariance_method_version VARCHAR(60),
    risk_overlay_policy_version VARCHAR(60),
    backtest_engine_version VARCHAR(60),
    config_hash          VARCHAR(64),
    config_snapshot      JSONB,
    status               VARCHAR(20)     NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ
);

ALTER TABLE systematic_equity.backtest_runs
    ADD COLUMN IF NOT EXISTS model_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_runs
    ADD COLUMN IF NOT EXISTS factor_definition_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_runs
    ADD COLUMN IF NOT EXISTS covariance_method_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_runs
    ADD COLUMN IF NOT EXISTS risk_overlay_policy_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_runs
    ALTER COLUMN transaction_cost_bps TYPE NUMERIC(10, 4)
    USING transaction_cost_bps::NUMERIC(10, 4);

ALTER TABLE systematic_equity.backtest_runs
    ALTER COLUMN transaction_cost_bps SET DEFAULT 15.0;

ALTER TABLE systematic_equity.backtest_runs
    ADD COLUMN IF NOT EXISTS backtest_engine_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_runs
    ADD COLUMN IF NOT EXISTS config_hash VARCHAR(64);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_holdings (
    id                  BIGSERIAL       PRIMARY KEY,
    run_id              UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    rebalance_date      DATE            NOT NULL,
    execution_date      DATE            NOT NULL,
    symbol              VARCHAR(50)     NOT NULL,
    target_weight       NUMERIC(12, 8)  NOT NULL,
    executed_weight     NUMERIC(12, 8),
    drifted_weight      NUMERIC(12, 8),
    requested_turnover_contrib NUMERIC(12, 8),
    turnover_contrib    NUMERIC(12, 8),
    execution_clipped   BOOLEAN         NOT NULL DEFAULT FALSE,
    composite_alpha     NUMERIC(18, 6),
    gics_sector         VARCHAR(60),
    regime              VARCHAR(20),

    CONSTRAINT uniq_backtest_holding
        UNIQUE (run_id, rebalance_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_backtest_holdings_run_date
    ON systematic_equity.backtest_holdings (run_id, rebalance_date);

ALTER TABLE systematic_equity.backtest_holdings
    ADD COLUMN IF NOT EXISTS executed_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_holdings
    ADD COLUMN IF NOT EXISTS requested_turnover_contrib NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_holdings
    ADD COLUMN IF NOT EXISTS execution_clipped BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_performance (
    id                  BIGSERIAL       PRIMARY KEY,
    run_id              UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    execution_date      DATE,
    period_end_date     DATE            NOT NULL,
    gross_return        NUMERIC(18, 8),
    net_return          NUMERIC(18, 8),
    benchmark_return    NUMERIC(18, 8),
    risk_free_return    NUMERIC(18, 8),
    excess_return       NUMERIC(18, 8),
    portfolio_nav       NUMERIC(18, 6),
    benchmark_nav       NUMERIC(18, 6),
    turnover            NUMERIC(10, 6),
    requested_turnover  NUMERIC(10, 6),
    gross_turnover      NUMERIC(10, 6),
    gross_requested_turnover NUMERIC(10, 6),
    transaction_cost    NUMERIC(18, 8),
    fixed_transaction_cost NUMERIC(18, 8),
    bid_ask_cost        NUMERIC(18, 8),
    slippage_cost       NUMERIC(18, 8),
    num_holdings        SMALLINT,
    regime              VARCHAR(20),
    vix_level           NUMERIC(10, 4),
    cash_start_weight   NUMERIC(12, 8),
    cash_after_execution_weight NUMERIC(12, 8),
    cash_end_weight     NUMERIC(12, 8),
    unfilled_buy_weight NUMERIC(12, 8),
    unfilled_sell_weight NUMERIC(12, 8),
    liquidity_clipped   BOOLEAN         NOT NULL DEFAULT FALSE,
    max_participation_used NUMERIC(12, 8),
    forward_filled_symbol_count SMALLINT NOT NULL DEFAULT 0,
    forward_fill_day_count SMALLINT      NOT NULL DEFAULT 0,
    drawdown_brake_active BOOLEAN       NOT NULL DEFAULT FALSE,
    drawdown_brake_drawdown NUMERIC(12, 8),
    drawdown_brake_fraction NUMERIC(12, 8),

    CONSTRAINT uniq_backtest_performance
        UNIQUE (run_id, period_end_date)
);

CREATE INDEX IF NOT EXISTS idx_backtest_performance_run_date
    ON systematic_equity.backtest_performance (run_id, period_end_date);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS execution_date DATE;

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS risk_free_return NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS requested_turnover NUMERIC(10, 6);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS gross_turnover NUMERIC(10, 6);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS gross_requested_turnover NUMERIC(10, 6);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS fixed_transaction_cost NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS bid_ask_cost NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS slippage_cost NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS cash_start_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS cash_after_execution_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS cash_end_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS unfilled_buy_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS unfilled_sell_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS liquidity_clipped BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS max_participation_used NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS forward_filled_symbol_count SMALLINT NOT NULL DEFAULT 0;

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS forward_fill_day_count SMALLINT NOT NULL DEFAULT 0;

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS drawdown_brake_active BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS drawdown_brake_drawdown NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS drawdown_brake_fraction NUMERIC(12, 8);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_cash_ledger (
    id                      BIGSERIAL       PRIMARY KEY,
    run_id                  UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    rebalance_date          DATE            NOT NULL,
    execution_date          DATE            NOT NULL,
    period_end_date         DATE            NOT NULL,
    cash_start_weight       NUMERIC(12, 8),
    cash_after_execution_weight NUMERIC(12, 8),
    cash_end_weight         NUMERIC(12, 8),
    requested_turnover      NUMERIC(10, 6),
    executed_turnover       NUMERIC(10, 6),
    gross_requested_turnover NUMERIC(10, 6),
    gross_executed_turnover NUMERIC(10, 6),
    fixed_transaction_cost  NUMERIC(18, 8),
    bid_ask_cost            NUMERIC(18, 8),
    slippage_cost           NUMERIC(18, 8),
    total_cost              NUMERIC(18, 8),
    unfilled_buy_weight     NUMERIC(12, 8),
    unfilled_sell_weight    NUMERIC(12, 8),
    liquidity_clipped       BOOLEAN         NOT NULL DEFAULT FALSE,
    max_participation_used  NUMERIC(12, 8),
    drawdown_brake_active   BOOLEAN         NOT NULL DEFAULT FALSE,
    drawdown_brake_drawdown NUMERIC(12, 8),
    drawdown_brake_fraction NUMERIC(12, 8),

    CONSTRAINT uniq_backtest_cash_ledger
        UNIQUE (run_id, rebalance_date)
);

CREATE INDEX IF NOT EXISTS idx_backtest_cash_ledger_run_date
    ON systematic_equity.backtest_cash_ledger (run_id, rebalance_date);

ALTER TABLE systematic_equity.backtest_cash_ledger
    ADD COLUMN IF NOT EXISTS bid_ask_cost NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_cash_ledger
    ADD COLUMN IF NOT EXISTS gross_requested_turnover NUMERIC(10, 6);

ALTER TABLE systematic_equity.backtest_cash_ledger
    ADD COLUMN IF NOT EXISTS gross_executed_turnover NUMERIC(10, 6);

ALTER TABLE systematic_equity.backtest_cash_ledger
    ADD COLUMN IF NOT EXISTS drawdown_brake_active BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE systematic_equity.backtest_cash_ledger
    ADD COLUMN IF NOT EXISTS drawdown_brake_drawdown NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_cash_ledger
    ADD COLUMN IF NOT EXISTS drawdown_brake_fraction NUMERIC(12, 8);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_execution_ledger (
    id                      BIGSERIAL       PRIMARY KEY,
    run_id                  UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    rebalance_date          DATE            NOT NULL,
    execution_date          DATE            NOT NULL,
    symbol                  VARCHAR(50)     NOT NULL,
    target_weight           NUMERIC(12, 8),
    drifted_weight          NUMERIC(12, 8),
    requested_weight        NUMERIC(12, 8),
    executed_weight         NUMERIC(12, 8),
    trade_side              VARCHAR(10),
    requested_buy_weight    NUMERIC(12, 8),
    requested_sell_weight   NUMERIC(12, 8),
    requested_trade_weight  NUMERIC(12, 8),
    executed_buy_weight     NUMERIC(12, 8),
    executed_sell_weight    NUMERIC(12, 8),
    executed_trade_weight   NUMERIC(12, 8),
    unfilled_weight         NUMERIC(12, 8),
    requested_notional      NUMERIC(18, 6),
    executed_notional       NUMERIC(18, 6),
    adv_usd                 NUMERIC(18, 6),
    liquidity_capacity_weight NUMERIC(12, 8),
    liquidity_clipped       BOOLEAN         NOT NULL DEFAULT FALSE,
    had_forward_fill        BOOLEAN         NOT NULL DEFAULT FALSE,
    forward_fill_days       SMALLINT        NOT NULL DEFAULT 0,
    participation_ratio     NUMERIC(12, 8),
    bid_ask_spread_bps      NUMERIC(12, 6),
    gap_return              NUMERIC(12, 8),
    gap_penalty_bps         NUMERIC(12, 6),
    participation_penalty_bps NUMERIC(12, 6),
    slippage_bps            NUMERIC(12, 6),
    fixed_transaction_cost  NUMERIC(18, 8),
    bid_ask_cost            NUMERIC(18, 8),
    slippage_cost           NUMERIC(18, 8),
    total_cost              NUMERIC(18, 8),

    CONSTRAINT uniq_backtest_execution_ledger
        UNIQUE (run_id, rebalance_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_backtest_execution_ledger_run_date
    ON systematic_equity.backtest_execution_ledger (run_id, rebalance_date, execution_date);

ALTER TABLE systematic_equity.backtest_execution_ledger
    ADD COLUMN IF NOT EXISTS had_forward_fill BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE systematic_equity.backtest_execution_ledger
    ADD COLUMN IF NOT EXISTS forward_fill_days SMALLINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_metrics (
    id              BIGSERIAL       PRIMARY KEY,
    run_id          UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    metric_group    VARCHAR(30)     NOT NULL,
    metric_name     VARCHAR(60)     NOT NULL,
    metric_value    NUMERIC(18, 6),
    metric_unit     VARCHAR(20),

    CONSTRAINT uniq_backtest_metric
        UNIQUE (run_id, metric_group, metric_name)
);
