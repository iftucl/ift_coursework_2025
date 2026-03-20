# Changelog - Team Russell

## [0.4.0] - 2026-03-09
### Added
- **8-metric factor model**: Value (B/P 15%, E/Y 35%, CF/Y 35%, DY 15%) + Quality (GPA 33%, WCA 17%, LTDE 33%, ROA 17%)
- **Sector-neutral scoring** (Amundi Section 2.3): winsorise at 5th/95th percentile within GICS sector -> percentile rank -> inverse-normal z-score; sectors with < 5 firms pooled
- **Eligibility filter**: EPS > 0; Financials and Real Estate sectors excluded
- **Quintile ranking**: Q1 (top 20% composite) to Q5 (bottom 20%)
- `composite_percentile` and `quintile` columns in `factor_values`
- 3 new indexes on `factor_values` (by rebalance_date, composite_score, quintile)
- New `financials` columns: `gross_profit`, `free_cash_flow`, `current_assets`, `current_liabilities`, `annual_dividend_rate`
- Per-metric z-score columns in `factor_values`: `z_bp`, `z_ey`, `z_cfy`, `z_dy`, `z_gpa`, `z_wca`, `z_ltde`, `z_roa`
- `scipy` dependency for `norm.ppf` inverse-normal transformation
- 10 new unit tests covering eligibility, raw metrics, sector pooling, weight renormalisation, quintiles (total: 43 tests)

### Changed
- Composite weights: 50% Value + 50% Quality (was 75% / 25%)
- `value_score`, `quality_score`, `composite_score` now hold z-scores (unbounded) instead of 0-1 percentiles
- `run_value_factor` renamed to `run_factor_pipeline`; backward-compatible alias kept
- Removed old `factor_values` columns: `enterprise_value`, `pb`, `pe`, `ev_ebitda`, `roe`, `percentile_pb`, `percentile_pe`, `percentile_ev_ebitda`, `percentile_roe`
- Pipeline A fetches `gross_profit`, `free_cash_flow`, `current_assets`, `current_liabilities`, `annual_dividend_rate` from yfinance
- Pipeline B transformer and postgres_writer updated to store the 5 new financial fields
- `data_loader.py` joins `company_static` to pull `gics_sector` for sector-neutral scoring

## [0.3.0] - 2026-02-25
### Added
- 2025 rebalance date (Dec 31, 2025) with Sep 30, 2025 lag cutoff — 596 companies, 593 composite scores
- 1 new unit test for `_safe_float` NaN handling (total: 35 tests)

### Fixed
- `_safe_float()` in `transformer.py` now returns `None` for `float('nan')` input — previously yfinance NaN values were stored as PostgreSQL NUMERIC NaN rather than NULL, causing `IS NULL` checks to return `False` while pandas still read the value as NaN, silently zeroing out all composite scores for the 2021 rebalance
- Cleaned 1,954 existing PostgreSQL NUMERIC NaN values in `systematic_equity.financials` by replacing with proper NULL using `WHERE column = 'NaN'::numeric`

## [0.2.0] - 2026-02-21
### Added
- **Quality factor component**: ROE (Return on Equity = Net Income / Book Value)
- **Composite score**: `0.75 × Value Score + 0.25 × Quality Score` per spec
- `roe`, `percentile_roe`, `quality_score`, `composite_score`, `run_id` columns in `factor_values`
- `revenue` column in `financials` (fetched from Yahoo Finance income statement)
- `compute_quality_score()` and `compute_composite_score()` functions in `value_factor.py`
- Partial-score handling in composite: falls back to value-only or quality-only if one component is missing
- Pipeline run identifier (`run_id`) stored with every factor output for traceability
- Universe eligibility filter: only companies with ≥ 4 consecutive years of financial data
- 12 new unit tests covering ROE, quality score, composite score, and revenue extraction (total: 32 tests)

### Changed
- Financial fetcher now extracts `Total Debt` (current + long-term) instead of long-term only, improving EV accuracy
- `data_loader.py` switched from exact fiscal-date match to `DISTINCT ON … ORDER BY period_date DESC`, correctly including companies with non-December fiscal year-ends (e.g. Apple Sep 30, Microsoft Jun 30) — improved universe from ~447 to ~596 companies
- `data_loader.py` updated to select `revenue`, apply the minimum-years eligibility filter, and use a 3-month look-ahead bias lag (was 1 month)
- `factor_writer.py` updated with new column set and `run_id` support
- README updated to reflect Value + Quality methodology, new output schema, and results table
- Pipeline C log messages updated to reference composite factor (was: value factor)

### Fixed
- `datetime.utcnow()` deprecation warnings in all three fetcher modules — replaced with `datetime.now(timezone.utc)`

## [0.1.0] - 2026-02-19
### Added
- Initial project structure for Coursework One
- Pipeline A: Data ingestion from Yahoo Finance and Alpha Vantage via Kafka + MinIO
- Pipeline B: Kafka consumer → MongoDB (raw) + PostgreSQL (processed)
- Pipeline C: Value factor computation (P/B, P/E, EV/EBITDA) → PostgreSQL
- Kafka infrastructure overlay (`docker-compose.kafka.yml`)
- SQL schema for `price_history`, `financials`, and `factor_values` tables
- 20 unit tests across all three pipelines (6 + 7 + 7)
