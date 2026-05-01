-- Migration 002: Benchmark price table for configurable market indices.
--
-- Kept separate from factor_observations to make clear this is NOT a factor —
-- it is reference/benchmark data used for:
--   1. Beta computation: Cov(stock, benchmark) / Var(benchmark), rolling 252 days
--   2. Portfolio performance attribution in CW2
--   3. Benchmark return series for Sharpe/Information ratio

CREATE TABLE IF NOT EXISTS systematic_equity.benchmark_prices (
    id          BIGSERIAL PRIMARY KEY,
    ticker      VARCHAR(20)     NOT NULL,
    price_date  DATE            NOT NULL,
    close_price NUMERIC(18, 6)  NOT NULL,
    daily_return NUMERIC(18, 8),
    source      VARCHAR(50)     NOT NULL DEFAULT 'yfinance',
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_benchmark_price UNIQUE (ticker, price_date)
);

COMMENT ON TABLE systematic_equity.benchmark_prices
    IS 'Daily closing prices for benchmark series (e.g. SPY). '
       'Used for beta calculation and portfolio performance attribution.';

COMMENT ON COLUMN systematic_equity.benchmark_prices.ticker
    IS 'Yahoo Finance ticker for the benchmark series (e.g. SPY).';

COMMENT ON COLUMN systematic_equity.benchmark_prices.daily_return
    IS 'Log return: ln(close_t / close_{t-1}). NULL for first row.';

CREATE INDEX IF NOT EXISTS idx_benchmark_prices_ticker_date
    ON systematic_equity.benchmark_prices (ticker, price_date DESC);
