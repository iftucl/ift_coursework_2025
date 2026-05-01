-- CW2 Analysis Schema
-- Derived from completed backtest runs; used for benchmark comparison,
-- regime attribution, and automated scorecards.

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_benchmark_nav (
    id              BIGSERIAL       PRIMARY KEY,
    run_id          UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    execution_date  DATE,
    period_end_date DATE            NOT NULL,
    series_name     VARCHAR(50)     NOT NULL,
    nav             NUMERIC(18, 6)  NOT NULL,
    period_return   NUMERIC(18, 8),
    gross_return    NUMERIC(18, 8),
    risk_free_return NUMERIC(18, 8),
    turnover        NUMERIC(18, 8),
    gross_turnover  NUMERIC(18, 8),
    transaction_cost NUMERIC(18, 8),
    num_holdings    SMALLINT,
    regime          VARCHAR(20),

    CONSTRAINT uniq_backtest_benchmark_nav
        UNIQUE (run_id, period_end_date, series_name)
);

CREATE INDEX IF NOT EXISTS idx_backtest_benchmark_nav_run
    ON systematic_equity.backtest_benchmark_nav (run_id, series_name, period_end_date);

ALTER TABLE systematic_equity.backtest_benchmark_nav
    ADD COLUMN IF NOT EXISTS execution_date DATE;

ALTER TABLE systematic_equity.backtest_benchmark_nav
    ADD COLUMN IF NOT EXISTS risk_free_return NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_benchmark_nav
    ADD COLUMN IF NOT EXISTS gross_return NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_benchmark_nav
    ADD COLUMN IF NOT EXISTS turnover NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_benchmark_nav
    ADD COLUMN IF NOT EXISTS gross_turnover NUMERIC(18, 8);

ALTER TABLE systematic_equity.backtest_benchmark_nav
    ADD COLUMN IF NOT EXISTS transaction_cost NUMERIC(18, 8);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_benchmark_metrics (
    id              BIGSERIAL       PRIMARY KEY,
    run_id          UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    series_name     VARCHAR(50)     NOT NULL,
    metric_name     VARCHAR(60)     NOT NULL,
    metric_value    NUMERIC(18, 6),
    metric_unit     VARCHAR(20),

    CONSTRAINT uniq_backtest_benchmark_metric
        UNIQUE (run_id, series_name, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_backtest_benchmark_metrics_run
    ON systematic_equity.backtest_benchmark_metrics (run_id, series_name, metric_name);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_relative_metrics (
    id              BIGSERIAL       PRIMARY KEY,
    run_id          UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    versus_series   VARCHAR(50)     NOT NULL,
    metric_name     VARCHAR(60)     NOT NULL,
    metric_value    NUMERIC(18, 6),
    metric_unit     VARCHAR(20),

    CONSTRAINT uniq_backtest_relative_metric
        UNIQUE (run_id, versus_series, metric_name)
);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_regime_attribution (
    id                  BIGSERIAL       PRIMARY KEY,
    run_id              UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    regime              VARCHAR(20)     NOT NULL,
    versus_series       VARCHAR(50)     NOT NULL,
    n_periods           SMALLINT,
    strategy_ann_return NUMERIC(18, 6),
    versus_ann_return   NUMERIC(18, 6),
    excess_ann_return   NUMERIC(18, 6),
    strategy_ann_vol    NUMERIC(18, 6),
    versus_ann_vol      NUMERIC(18, 6),
    strategy_sharpe     NUMERIC(18, 6),
    versus_sharpe       NUMERIC(18, 6),
    strategy_max_dd     NUMERIC(18, 6),
    versus_max_dd       NUMERIC(18, 6),
    hit_rate            NUMERIC(10, 6),

    CONSTRAINT uniq_backtest_regime_attribution
        UNIQUE (run_id, regime, versus_series)
);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_factor_attribution (
    id                  BIGSERIAL       PRIMARY KEY,
    run_id              UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    rebalance_date      DATE            NOT NULL,
    period_end_date     DATE            NOT NULL,
    factor_name         VARCHAR(40)     NOT NULL,
    strategy_exposure   NUMERIC(18, 8),
    universe_exposure   NUMERIC(18, 8),
    active_exposure     NUMERIC(18, 8),
    factor_spread_return NUMERIC(18, 8),
    contribution_proxy  NUMERIC(18, 8),
    top_bucket_size     SMALLINT,
    bottom_bucket_size  SMALLINT,
    attribution_method  VARCHAR(80),

    CONSTRAINT uniq_backtest_factor_attribution
        UNIQUE (run_id, rebalance_date, factor_name)
);

CREATE INDEX IF NOT EXISTS idx_backtest_factor_attribution_run
    ON systematic_equity.backtest_factor_attribution (run_id, rebalance_date, factor_name);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_covariance_metrics (
    id                  BIGSERIAL       PRIMARY KEY,
    run_id              UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    rebalance_date      DATE            NOT NULL,
    period_end_date     DATE            NOT NULL,
    series_name         VARCHAR(50)     NOT NULL,
    versus_series       VARCHAR(50)     NOT NULL DEFAULT '',
    metric_name         VARCHAR(60)     NOT NULL,
    metric_value        NUMERIC(18, 6),
    metric_unit         VARCHAR(20),
    covariance_method   VARCHAR(40),
    lookback_days       SMALLINT,

    CONSTRAINT uniq_backtest_covariance_metric
        UNIQUE (run_id, rebalance_date, period_end_date, series_name, versus_series, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_backtest_covariance_metrics_run
    ON systematic_equity.backtest_covariance_metrics (run_id, series_name, rebalance_date);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_covariance_contributions (
    id                              BIGSERIAL       PRIMARY KEY,
    run_id                          UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    rebalance_date                  DATE            NOT NULL,
    period_end_date                 DATE            NOT NULL,
    series_name                     VARCHAR(50)     NOT NULL,
    dimension_type                  VARCHAR(20)     NOT NULL,
    dimension_name                  VARCHAR(100)    NOT NULL,
    portfolio_weight                NUMERIC(12, 8),
    risk_contribution_pct           NUMERIC(18, 8),
    component_volatility_contribution NUMERIC(18, 8),
    covariance_method               VARCHAR(40),
    lookback_days                   SMALLINT,

    CONSTRAINT uniq_backtest_covariance_contribution
        UNIQUE (run_id, rebalance_date, period_end_date, series_name, dimension_type, dimension_name)
);

CREATE INDEX IF NOT EXISTS idx_backtest_covariance_contrib_run
    ON systematic_equity.backtest_covariance_contributions (run_id, series_name, rebalance_date, dimension_type);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_scorecard (
    id              BIGSERIAL       PRIMARY KEY,
    run_id          UUID            NOT NULL
        REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    criterion_id    SMALLINT        NOT NULL,
    criterion_name  VARCHAR(100)    NOT NULL,
    passed          BOOLEAN,
    evidence        JSONB,

    CONSTRAINT uniq_backtest_scorecard
        UNIQUE (run_id, criterion_id)
);
