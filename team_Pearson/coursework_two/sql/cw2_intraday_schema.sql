-- CW2 Intraday / Daily Trigger Overlay Schema

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_intraday_events (
    id                     BIGSERIAL       PRIMARY KEY,
    run_id                 UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    event_date             DATE            NOT NULL,
    event_type             VARCHAR(30)     NOT NULL,
    symbol                 VARCHAR(50)     NOT NULL DEFAULT '',
    action_scope           VARCHAR(20),
    action_family          VARCHAR(30),
    urgency                VARCHAR(20),
    reason_code            VARCHAR(40),
    entry_price            NUMERIC(18, 6),
    open_price             NUMERIC(18, 6),
    high_price             NUMERIC(18, 6),
    low_price              NUMERIC(18, 6),
    execution_price        NUMERIC(18, 6),
    stop_loss_threshold    NUMERIC(10, 6),
    weight_before          NUMERIC(12, 8),
    weight_after           NUMERIC(12, 8),
    regime_before          VARCHAR(20),
    regime_after           VARCHAR(20),
    vix_level              NUMERIC(10, 4),
    vix_daily_return       NUMERIC(10, 6),
    rebalance_scheduled_for DATE,
    transaction_cost       NUMERIC(18, 8),
    expected_turnover      NUMERIC(12, 8),
    expected_cost          NUMERIC(18, 8)
);

CREATE INDEX IF NOT EXISTS idx_intraday_events_run_date
    ON systematic_equity.backtest_intraday_events (run_id, event_date);

CREATE INDEX IF NOT EXISTS idx_intraday_events_type
    ON systematic_equity.backtest_intraday_events (run_id, event_type);

CREATE UNIQUE INDEX IF NOT EXISTS uq_intraday_event_key
    ON systematic_equity.backtest_intraday_events (run_id, event_date, event_type, symbol);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_intraday_daily_state (
    id                  BIGSERIAL       PRIMARY KEY,
    run_id              UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    state_date          DATE            NOT NULL,
    symbol              VARCHAR(50)     NOT NULL,
    weight              NUMERIC(12, 8)  NOT NULL,
    entry_price         NUMERIC(18, 6),
    current_price       NUMERIC(18, 6),
    unrealized_return   NUMERIC(12, 8),
    regime              VARCHAR(20),
    is_cash             BOOLEAN         NOT NULL DEFAULT FALSE,

    CONSTRAINT uniq_intraday_daily_state
        UNIQUE (run_id, state_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_intraday_daily_state_run_date
    ON systematic_equity.backtest_intraday_daily_state (run_id, state_date);

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS intraday_stop_loss_count SMALLINT DEFAULT 0;

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS intraday_regime_switch_count SMALLINT DEFAULT 0;

ALTER TABLE systematic_equity.backtest_performance
    ADD COLUMN IF NOT EXISTS intraday_cost NUMERIC(18, 8) DEFAULT 0;

ALTER TABLE systematic_equity.backtest_intraday_events
    ADD COLUMN IF NOT EXISTS action_scope VARCHAR(20);

ALTER TABLE systematic_equity.backtest_intraday_events
    ADD COLUMN IF NOT EXISTS action_family VARCHAR(30);

ALTER TABLE systematic_equity.backtest_intraday_events
    ADD COLUMN IF NOT EXISTS urgency VARCHAR(20);

ALTER TABLE systematic_equity.backtest_intraday_events
    ADD COLUMN IF NOT EXISTS reason_code VARCHAR(40);

ALTER TABLE systematic_equity.backtest_intraday_events
    ADD COLUMN IF NOT EXISTS expected_turnover NUMERIC(12, 8);

ALTER TABLE systematic_equity.backtest_intraday_events
    ADD COLUMN IF NOT EXISTS expected_cost NUMERIC(18, 8);

DROP VIEW IF EXISTS systematic_equity.backtest_trade_blotter;

CREATE VIEW systematic_equity.backtest_trade_blotter AS
SELECT
    COALESCE(NULLIF(TRIM(br.rebalance_freq), ''), 'monthly')
        || ':' || el.run_id::text || ':' || el.execution_date::text || ':' || el.symbol AS blotter_id,
    el.run_id,
    el.execution_date AS trade_date,
    el.execution_date,
    (
        COALESCE(NULLIF(TRIM(br.rebalance_freq), ''), 'monthly') || '_rebalance'
    )::VARCHAR(30) AS source_layer,
    'backtest_execution_ledger'::VARCHAR(40) AS source_table,
    'symbol'::VARCHAR(20) AS record_granularity,
    (
        COALESCE(NULLIF(TRIM(br.rebalance_freq), ''), 'monthly')
        || '_rebalance_execution'
    )::VARCHAR(40) AS action_type,
    'symbol'::VARCHAR(20) AS action_scope,
    'scheduled_rebalance'::VARCHAR(30) AS action_family,
    'scheduled'::VARCHAR(20) AS urgency,
    el.symbol,
    el.trade_side,
    el.drifted_weight AS weight_before,
    el.executed_weight AS weight_after,
    el.target_weight,
    el.drifted_weight,
    el.requested_weight,
    el.executed_weight,
    el.requested_trade_weight,
    el.executed_trade_weight,
    NULL::NUMERIC(18, 6) AS entry_price,
    NULL::NUMERIC(18, 6) AS open_price,
    NULL::NUMERIC(18, 6) AS high_price,
    NULL::NUMERIC(18, 6) AS low_price,
    NULL::NUMERIC(18, 6) AS execution_price,
    NULL::NUMERIC(10, 6) AS stop_loss_threshold,
    el.total_cost AS transaction_cost,
    el.fixed_transaction_cost,
    el.bid_ask_cost,
    el.slippage_cost,
    el.total_cost,
    el.requested_trade_weight AS expected_turnover,
    el.total_cost AS expected_cost,
    el.liquidity_clipped,
    el.had_forward_fill,
    el.forward_fill_days,
    el.participation_ratio,
    CASE
        WHEN el.liquidity_clipped THEN 'liquidity_capacity_clip'
        ELSE 'scheduled_rebalance'
    END::VARCHAR(40) AS reason_code,
    NULL::VARCHAR(20) AS regime_before,
    NULL::VARCHAR(20) AS regime_after
FROM systematic_equity.backtest_execution_ledger AS el
JOIN systematic_equity.backtest_runs AS br
    ON br.run_id = el.run_id

UNION ALL

SELECT
    'intraday:' || ie.run_id::text || ':' || ie.event_date::text || ':' || ie.event_type || ':' || COALESCE(NULLIF(ie.symbol, ''), '_PORTFOLIO') AS blotter_id,
    ie.run_id,
    ie.event_date AS trade_date,
    ie.event_date AS execution_date,
    'intraday_overlay'::VARCHAR(30) AS source_layer,
    'backtest_intraday_events'::VARCHAR(40) AS source_table,
    CASE
        WHEN NULLIF(ie.symbol, '') IS NULL THEN 'portfolio'
        ELSE 'symbol'
    END::VARCHAR(20) AS record_granularity,
    ie.event_type AS action_type,
    ie.action_scope,
    ie.action_family,
    ie.urgency,
    NULLIF(ie.symbol, '') AS symbol,
    CASE
        WHEN ie.weight_after IS NOT NULL AND ie.weight_before IS NOT NULL AND ie.weight_after < ie.weight_before THEN 'sell'
        WHEN ie.weight_after IS NOT NULL AND ie.weight_before IS NOT NULL AND ie.weight_after > ie.weight_before THEN 'buy'
        WHEN ie.action_scope = 'portfolio' THEN 'rebalance'
        ELSE NULL
    END::VARCHAR(10) AS trade_side,
    ie.weight_before,
    ie.weight_after,
    NULL::NUMERIC(12, 8) AS target_weight,
    NULL::NUMERIC(12, 8) AS drifted_weight,
    NULL::NUMERIC(12, 8) AS requested_weight,
    ie.weight_after AS executed_weight,
    ie.expected_turnover AS requested_trade_weight,
    CASE
        WHEN ie.weight_before IS NOT NULL AND ie.weight_after IS NOT NULL
            THEN ABS(ie.weight_after - ie.weight_before)
        ELSE ie.expected_turnover
    END AS executed_trade_weight,
    ie.entry_price,
    ie.open_price,
    ie.high_price,
    ie.low_price,
    ie.execution_price,
    ie.stop_loss_threshold,
    ie.transaction_cost,
    ie.transaction_cost AS fixed_transaction_cost,
    NULL::NUMERIC(18, 8) AS bid_ask_cost,
    NULL::NUMERIC(18, 8) AS slippage_cost,
    ie.transaction_cost AS total_cost,
    ie.expected_turnover,
    ie.expected_cost,
    NULL::BOOLEAN AS liquidity_clipped,
    NULL::BOOLEAN AS had_forward_fill,
    NULL::SMALLINT AS forward_fill_days,
    NULL::NUMERIC(12, 8) AS participation_ratio,
    ie.reason_code,
    ie.regime_before,
    ie.regime_after
FROM systematic_equity.backtest_intraday_events AS ie;
