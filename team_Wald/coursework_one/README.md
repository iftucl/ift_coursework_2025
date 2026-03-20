# Team 07 — Value + News Sentiment Equity Strategy

**UCL Institute of Finance & Technology**
**IFTE0003: Big Data in Quantitative Finance — Coursework 1**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [What This Project Does (Non-Technical Summary)](#2-what-this-project-does-non-technical-summary)
3. [Investment Thesis and Academic Foundation](#3-investment-thesis-and-academic-foundation)
4. [Strategy Design: How It Works](#4-strategy-design-how-it-works)
5. [Architecture Overview](#5-architecture-overview)
6. [Infrastructure Design](#6-infrastructure-design)
7. [Data Sources](#7-data-sources)
8. [Data Dictionary](#8-data-dictionary)
9. [Data Lineage](#9-data-lineage)
10. [Data Quality Standards](#10-data-quality-standards)
11. [Prerequisites](#11-prerequisites)
12. [Installation Guide (Step-by-Step)](#12-installation-guide-step-by-step)
13. [How to Run the Pipeline](#13-how-to-run-the-pipeline)
14. [Configuration Guide](#14-configuration-guide)
15. [Project Structure](#15-project-structure)
16. [Module Reference](#16-module-reference)
17. [Database Schema](#17-database-schema)
18. [Testing](#18-testing)
19. [Code Quality](#19-code-quality)
20. [Technology Choices and Alternatives](#20-technology-choices-and-alternatives)
21. [Troubleshooting](#21-troubleshooting)
22. [References](#22-references)
23. [Verifying Pipeline Results (Step-by-Step)](#23-verifying-pipeline-results-step-by-step)
24. [Accessing Web Interfaces](#24-accessing-web-interfaces)
25. [Shutting Down and Cleaning Up](#25-shutting-down-and-cleaning-up)
26. [Complete End-to-End Walkthrough (From Zero to Results)](#26-complete-end-to-end-walkthrough-from-zero-to-results)

---

## 1. Introduction

This project implements a complete **data extraction, processing, and storage pipeline** for a Value + News Sentiment equity investment strategy. It is the data foundation (Coursework 1) that will feed into portfolio construction and backtesting in Coursework 2.

The pipeline processes **678 real companies** across **8 countries** (USA, UK, France, Germany, Netherlands, Spain, Italy, Canada, Switzerland) from the `systematic_equity.company_static` investable universe. It collects:

- **5 years of daily stock prices** (Open, High, Low, Close, Volume)
- **Financial ratios** (P/E, P/B, EV/EBITDA, Dividend Yield, Debt/Equity)
- **FX exchange rates** for 4 currency pairs (GBP/USD, EUR/USD, CAD/USD, CHF/USD)
- **News articles** from the GDELT global news database and Yahoo Finance
- **Sentiment scores** computed via VADER natural language processing

All data is sourced from **real, live APIs** — no simulated or synthetic data is used anywhere in the pipeline.

---

## 2. What This Project Does (Non-Technical Summary)

Imagine you want to invest in stocks, but you want to be smart about it. This project builds a system that:

1. **Finds cheap stocks**: It looks at 678 companies around the world and checks if their stock price is low compared to how much money the company actually makes (its earnings, its assets, its cash flow). These are called "value" metrics. Think of it like looking for a house that is worth more than its asking price.

2. **Checks the news**: Just because a stock is cheap doesn't mean it's a good buy — it might be cheap because the company is in trouble. So the system reads thousands of recent news articles about each company and uses artificial intelligence (specifically, a tool called VADER) to determine whether the news is positive, negative, or neutral.

3. **Combines both signals**: The system gives each company two scores:
   - A **Value Score** (how cheap/undervalued the company is) — this counts for 60% of the final score
   - A **Sentiment Score** (how positive the news coverage is) — this counts for 40% of the final score

   Companies that are both undervalued AND have positive news are ranked highest.

4. **Filters out risky companies**: Companies with too much debt (Debt/Equity > 2.0) or overwhelmingly negative news are excluded entirely.

5. **Stores everything safely**: All raw data, processed scores, and final rankings are stored in multiple database systems so they can be retrieved later for portfolio construction in Coursework 2.

The end result is a ranked list of companies that the strategy recommends investing in — the **top 20%** are flagged with an "invest" decision.

---

## 3. Investment Thesis and Academic Foundation

### The Core Hypothesis

> "We hypothesise that companies which are undervalued based on fundamental financial ratios (P/E, P/B, EV/EBITDA) AND which have positive recent news sentiment will outperform the broader market over medium to long-term horizons. The sentiment filter removes value traps — companies that appear cheap but face genuine business risks reflected in negative news coverage."

### Why This Works — Academic Evidence

The strategy is grounded in two well-established strands of academic finance:

**1. The Value Premium (Fama & French, 1993)**

Professors Eugene Fama and Kenneth French demonstrated that stocks with low price-to-book ratios and low price-to-earnings ratios systematically outperform more expensive "growth" stocks over long periods. This has been documented across dozens of markets and decades of data. The explanation is that value stocks carry higher risk (they are often companies facing challenges), so investors demand higher returns.

**2. News Sentiment as a Forward Indicator (Tetlock, 2007; Baker & Wurgler, 2006)**

Professor Paul Tetlock showed that the tone of media coverage about companies predicts future stock price movements. When news coverage is unusually negative, stock prices tend to fall further. Baker and Wurgler demonstrated that investor sentiment (the overall mood of the market) affects which stocks are over- or under-priced.

**3. The Combined Logic — "Smart Value"**

- Value investing alone can lead to **"value traps"** — stocks that are cheap because something is genuinely wrong with the company.
- News sentiment acts as a **safety filter** — if the news is overwhelmingly negative, the stock is probably cheap for a reason.
- By requiring BOTH undervaluation AND positive sentiment, we identify companies where the market is beginning to recognise hidden value, while avoiding those in genuine decline.

### Key Indicators

**Value Factor Indicators** (what makes a stock "cheap"):

| Indicator | What It Measures | How We Use It |
|---|---|---|
| P/E Ratio (Price-to-Earnings) | Stock price relative to company earnings | Lower = more undervalued |
| P/B Ratio (Price-to-Book) | Stock price relative to company net assets | Lower = more undervalued |
| EV/EBITDA (Enterprise Value to Operating Profit) | Total company value relative to cash-generating ability | Lower = more undervalued |
| Dividend Yield | Annual cash payments to shareholders as % of price | Higher = more attractive |
| Debt/Equity | How much the company has borrowed relative to its own funds | Used as a **safety filter** — exclude companies with D/E > 2.0 |

**Sentiment Factor Indicators** (what the news says about the company):

| Indicator | What It Measures | How We Use It |
|---|---|---|
| Average Sentiment Score | Overall tone of recent news articles (positive, negative, neutral) | Higher = more positive perception |
| Positive Article Ratio | What percentage of articles are positive | Higher = more consistently positive news |
| Article Volume | How many articles were published about the company | More articles = higher confidence in the score |

---

## 4. Strategy Design: How It Works

### Value Score Calculation (0-100 scale)

1. For each company, we retrieve four financial ratios from Yahoo Finance: P/E, P/B, EV/EBITDA, and Dividend Yield.
2. We rank all 678 companies by each ratio using **percentile ranking** (where 0 = worst, 100 = best).
3. For P/E, P/B, and EV/EBITDA, lower values are better (cheaper), so the rank is inverted.
4. For Dividend Yield, higher values are better, so the rank is kept as-is.
5. The **Value Score** is the average of all available percentile ranks, scaled to 0-100.
6. **Debt/Equity is NOT included in the Value Score** — it is used only as a filter in the composite stage.

**Data quality rules applied:**
- Companies with negative P/E ratios (negative earnings) are excluded from P/E ranking but can still score on other metrics.
- Extreme P/E ratios above 500 are excluded from ranking.
- If a company is missing one or more ratios, the Value Score is the average of whichever ratios ARE available.

### Sentiment Score Calculation (0-100 scale)

1. For each company, we fetch recent news articles from the GDELT API and Yahoo Finance.
2. Duplicate articles (same headline) are **removed before scoring**.
3. Each article's headline AND description are combined and analysed using **VADER sentiment analysis**.
4. VADER produces a compound score from -1 (most negative) to +1 (most positive).
5. Articles are classified: compound >= 0.05 is positive, <= -0.05 is negative, else neutral.
6. The company-level Sentiment Score uses a weighted formula:

```
Sentiment Score = (avg_compound_normalised x 0.5)
                + (positive_ratio_pct x 0.3)
                + (volume_factor x 0.2)

Where:
  avg_compound_normalised = (avg_compound + 1) / 2 x 100    (converts -1..+1 to 0..100)
  positive_ratio_pct      = positive_count / total_count x 100
  volume_factor           = min(article_count / 20, 1.0) x 100  (caps at 20 articles)
```

### Composite Score and Investment Decision

```
Composite Score = (Value Score x 0.6) + (Sentiment Score x 0.4)
```

**Filtering rules** (companies must pass ALL of these):
- Debt/Equity must be < 2.0 (not over-leveraged)
- Average Sentiment must be > 0.0 (net positive news)
- Minimum 3 articles required for reliable sentiment (low-confidence companies are flagged)

After scoring and filtering, companies are **ranked by Composite Score** (highest = best investment candidate). The **top 20% (top quintile)** are flagged with `invest_decision = True` for use in CW2 portfolio construction.

---

## 5. Architecture Overview

The pipeline follows an **Extract-Transform-Load (ETL)** pattern:

```
                        +----------------------------------+
                        |        Main.py (Orchestrator)    |
                        |  CLI: --env_type --frequency     |
                        |       --sources --tickers        |
                        +--------+--------+--------+-------+
                                 |        |        |
              +------------------+   +----+----+   +------------------+
              |                      |         |                      |
    +---------v----------+  +--------v---+  +--v-----------------+
    |    EXTRACTION       |  | FX RATES   |  |   NEWS CASCADE       |
    | Yahoo Finance API   |  | 4 currency |  | Tier 1: YF News      |
    | - Daily prices      |  | pairs from |  | Tier 2: GDELT API    |
    | - Company info      |  | Yahoo Fin  |  | Tier 3: NewsAPI      |
    | - Financial stmts   |  |            |  | (gap-fill pattern)   |
    | + Rate Limiter      |  |            |  | + Circuit Breakers   |
    | + Circuit Breaker   |  |            |  |                      |
    +---------+----------+  +-----+------+  +--+--+---------------+
              |                   |            |  |
    +---------v-------------------v------------v--v---------+
    |                    RAW STORAGE                         |
    | MinIO (S3 data lake)        MongoDB (document store)   |
    | - raw-data/prices/          - raw_news_articles        |
    | - raw-data/financial/       - raw_financial_data        |
    | - raw-data/company_info/    - raw_price_history         |
    | - raw-data/fx/                                          |
    +---+---------------------+---+--------------------------+
        |                     |   |
    +---v---------+    +------v---v--------+    +------------------+
    | DATA        |    | PROCESSING        |    | KAFKA EVENTS     |
    | CLEANING    |    | - Value scoring   |    | - news-articles  |
    | - Validate  |    | - VADER sentiment |    | - value-metrics  |
    | - Convert   |    | - Composite score |    | (Producer +      |
    | - Normalise |    | - Ranking         |    |  Consumer)       |
    +---+---------+    +------+------------+    +------------------+
        |                     |
    +---v---------------------v------------------------------+
    |                    POSTGRESQL                            |
    |  systematic_equity schema (8 tables):                    |
    |  - company_static (678 companies)                        |
    |  - daily_prices (5yr OHLCV)                              |
    |  - value_metrics (P/E, P/B, EV/EBITDA, DY, D/E, score)  |
    |  - sentiment_scores (VADER aggregated)                   |
    |  - composite_rankings (final score + invest decision)    |
    |  - fx_rates (4 currency pairs)                           |
    |  - ingestion_log (audit trail)                           |
    |  - pipeline_metadata (run tracking)                      |
    +----------------------------------------------------------+
```

### Pipeline Execution Flow (Step-by-Step)

When you run `Main.py`, the following happens in order:

1. **Parse CLI arguments** — reads command-line flags like `--frequency weekly`
2. **Load configuration** — reads `config/conf.yaml` and sets environment variables
3. **Connect to databases** — establishes connections to PostgreSQL, MongoDB, MinIO, and Kafka
4. **Load company universe** — reads the 678 companies from the `company_static` table
5. **Detect delisted tickers** — dynamically identifies delisted/acquired companies (73 confirmed) so they are skipped but still counted in the coverage denominator
6. **Extract FX rates + News in parallel** — FX rates (4 pairs) and the 3-tier news cascade (YF News → GDELT → NewsAPI) run concurrently
7. **Extract prices and ratios (batched, parallel)** — downloads daily price history, company info, and financial statements from Yahoo Finance using `ThreadPoolExecutor` with Token Bucket rate limiter (2 req/s, burst 5), Circuit Breaker (threshold 15, 60s recovery), and inter-request jitter. Financial statement ratios are calculated inline via `enhance_company_info()` when pre-computed ratios are missing.
8. **Store raw data** — uploads raw files to MinIO (data lake) and MongoDB (document store) in parallel after each batch
9. **Refetch missing ratios (two-pass)** — Pass 1: recalculate from existing financial statements (no API calls); Pass 2: sequentially re-fetch remaining gaps with proper delays
10. **Publish to Kafka** — sends news articles and value metrics as events to Kafka topics
11. **Load prices to PostgreSQL** — upserts cleaned price data into `daily_prices` table
12. **Compute Value Scores** — calculates percentile-rank value scores and upserts to `value_metrics`
13. **Compute Sentiment Scores** — runs VADER analysis and upserts to `sentiment_scores`
14. **Compute Composite Rankings** — combines value and sentiment, applies filters, ranks companies, upserts to `composite_rankings`
15. **Cleanup** — closes all database connections and writes audit log

Each stage is wrapped in error handling — if one company fails, the pipeline continues with the others.

### Resilience Patterns

The pipeline implements three industry-standard resilience patterns to handle Yahoo Finance API instability:

| Pattern | Module | Purpose | Reference |
|---|---|---|---|
| **Token Bucket Rate Limiter** | `modules/utils/rate_limiter.py` | Controls request frequency (2 req/s, burst 5). Thread-safe. Sleeps outside the lock to avoid blocking other workers. | Turner (1986), "New Directions in Communications" |
| **Circuit Breaker** | `modules/utils/circuit_breaker.py` | 3-state machine (CLOSED → OPEN → HALF_OPEN). Opens after 15 consecutive failures. Prevents cascading failures from 401 errors. | Nygard (2007), *Release It!* |
| **Exponential Backoff with Jitter** | `modules/utils/retry_handler.py` | Per-request retry with randomised backoff (base × 2^attempt + jitter). Prevents thundering herd. | AWS Architecture Blog (2015) |

### Data Coverage Results (vs 678-Company Universe)

| Metric | Coverage | Count | Target | Status |
|---|---|---|---|---|
| P/E Ratio | 82.6% | 560/678 | 80%+ | PASS |
| P/B Ratio | 88.8% | 602/678 | 80%+ | PASS |
| EV/EBITDA | 88.8% | 602/678 | 80%+ | PASS |
| Dividend Yield | 88.9% | 603/678 | 80%+ | PASS |
| Debt/Equity | 88.1% | 597/678 | 80%+ | PASS |
| Value Score | 88.9% | 603/678 | 80%+ | PASS |

The remaining ~11% gap is primarily due to 73 dynamically-detected delisted tickers (10.8%) plus a handful of companies with genuinely missing data (e.g. negative equity, recently IPO'd).

---

## 6. Infrastructure Design

### Database Systems

| System | Role | What It Stores | Why This System |
|---|---|---|---|
| **PostgreSQL 16** | Relational analytics store | Clean, structured data: prices, value metrics, sentiment scores, composite rankings, FX rates, audit logs | Best for structured tabular data with complex queries. Supports upsert (INSERT ... ON CONFLICT) for re-runnable pipeline. Required by assignment. |
| **MongoDB 7.0** | Document store | Raw news articles (variable-format JSON), raw financial statement JSON, raw API responses | Best for variable-format documents like news articles where each article may have different fields. Required by assignment. |
| **MinIO** | S3-compatible data lake | Raw CSV and JSON files organised by type/year/ticker for full data lineage and reproducibility | Provides a data lake pattern with S3-compatible API. Stores the raw "as-received" data for audit trail. Required by assignment. |
| **Apache Kafka** | Event streaming broker | News article events (`news-articles` topic), value metric events (`value-metrics` topic) for decoupled processing | Enables real-time event streaming and decoupled architecture. Consumer can be wired in CW2 for streaming updates. Required by assignment. |

### Docker Services

All infrastructure is containerised — you do not need to install PostgreSQL, MongoDB, Kafka, or MinIO locally. Everything runs inside Docker containers defined in `docker-compose.yml`.

```bash
# Start all services at once
docker compose up -d

# Or start specific services
docker compose up --build postgres-db mongodb miniocw zookeeper kafka postgres-seed mongo-seed minio-seed
```

| Service | Internal Port | External Port | Purpose |
|---|---|---|---|
| `postgres-db` | 5432 | 5439 | PostgreSQL 16 database server with `fift` database and `systematic_equity` schema |
| `mongodb` | 27017 | 27019 | MongoDB 7.0 document database for raw news articles and financial data |
| `miniocw` | 9000 / 9001 | 9000 / 9001 | S3-compatible object storage (API on 9000, web console on 9001) |
| `kafka` | 29092 | 9092 | Apache Kafka event streaming broker |
| `zookeeper` | 2181 | 2181 | Kafka coordination service (required by Kafka) |
| `postgres-seed` | — | — | Initialisation container: creates schema, tables, and seeds 678 companies from CSV |
| `mongo-seed` | — | — | Initialisation container: creates MongoDB indexes |
| `minio-seed` | — | — | Initialisation container: creates MinIO bucket (`iftbigdata`) |

### MinIO Data Lake Folder Structure

```
iftbigdata/                        (bucket)
  raw-data/
    prices/
      {TICKER}/
        {DATE}.csv                 (daily OHLCV prices)
    financial/
      {YEAR}/
        {TICKER}/
          statements.json          (income statement, balance sheet, cash flow)
    company_info/
      {TICKER}/
        info.json                  (financial ratios, sector, market cap)
    fx/
      {PAIR}/
        {DATE}.csv                 (daily FX rates)
    news/
      {DATE}/
        {TICKER}/
          articles.json            (news articles with metadata)
```

---

## 7. Data Sources

All data used in this project comes from **real, publicly available APIs**. No synthetic, simulated, or hardcoded data is used.

### Source 1: PostgreSQL — Company Static Table

| Detail | Value |
|---|---|
| **Database** | `fift` |
| **Schema** | `systematic_equity` |
| **Table** | `company_static` |
| **Access** | Provided via Docker (seeded automatically from `company_static.csv`) |
| **Contains** | 678 companies with symbol, name, GICS sector, GICS industry, country, region |
| **Countries** | USA, UK, France, Germany, Netherlands, Spain, Italy, Canada, Switzerland |
| **Updates** | Managed externally — our pipeline reads from it each run |

### Source 2: Yahoo Finance (yfinance Python Library)

| Detail | Value |
|---|---|
| **Type** | Python library wrapping Yahoo Finance REST API |
| **Access** | Free, no API key needed |
| **Python Package** | `yfinance ^0.2.36` (installed via Poetry) |
| **Data Available** | Financial statements (quarterly), daily price history, company info with pre-computed ratios, dividends, news headlines |
| **History** | 5+ years of quarterly financial data and daily prices |
| **Rate Limits** | Unofficial — pipeline uses Token Bucket rate limiter (2 req/s, burst 5) + Circuit Breaker (threshold 15, 60s recovery) + inter-request jitter (0.3-0.8s) + 2-second batch delays |
| **Reliability** | Good for large-cap companies; occasional missing data for smaller companies. Financial statement-based ratio calculation fills gaps when pre-computed ratios are unavailable. |

### Source 3: GDELT (Global Database of Events, Language, and Tone)

| Detail | Value |
|---|---|
| **Type** | REST API |
| **Access** | Completely free, no API key, no official rate limits |
| **Base URL** | `https://api.gdeltproject.org/api/v2/doc/doc` |
| **Parameters** | `query` (company name), `mode` (artlist), `format` (json), `timespan` (3months), `maxrecords` (50) |
| **Data Available** | News articles globally with headline, URL, source domain, publication date, language, GDELT tone scores |
| **History** | Years of archived articles |
| **Reliability** | Excellent coverage for large companies; less coverage for small-cap and non-English companies |
| **Reference** | Leetaru & Schrodt (2013), "GDELT: Global Data on Events, Location and Tone, 1979-2012" |

### Source 4: FX Rates (via Yahoo Finance)

| Detail | Value |
|---|---|
| **Pairs** | GBPUSD=X, EURUSD=X, CADUSD=X, CHFUSD=X |
| **Purpose** | Normalise company valuations across currencies to a common USD basis |
| **Mapping** | `.L` (London) = GBP, `.PA/.AS/.DE/.MC/.MI` (European) = EUR, `.TO` (Toronto) = CAD, `.SW` (Zurich) = CHF |

---

## 8. Data Dictionary

Every data field in the system is documented below.

### Value Data Fields

| Field Name | Description | Data Type | Source | Frequency | Example |
|---|---|---|---|---|---|
| `company_id` | Unique ticker symbol from company_static | VARCHAR(12) | PostgreSQL | Static | "AAPL" |
| `date` | Date of the data point | DATE | Calculated | Varies | "2025-03-31" |
| `pe_ratio` | Price-to-Earnings ratio (stock price / earnings per share) | NUMERIC(18,4) | Yahoo Finance | Quarterly | 28.50 |
| `pb_ratio` | Price-to-Book ratio (stock price / book value per share) | NUMERIC(18,4) | Yahoo Finance | Quarterly | 4.21 |
| `ev_ebitda` | Enterprise Value to EBITDA (total value / operating cash flow) | NUMERIC(18,4) | Yahoo Finance | Quarterly | 22.10 |
| `dividend_yield` | Annual dividend as fraction of stock price | NUMERIC(18,6) | Yahoo Finance | Quarterly | 0.0065 |
| `debt_equity` | Total debt divided by total shareholder equity | NUMERIC(18,4) | Yahoo Finance | Quarterly | 1.45 |
| `value_score` | Composite percentile-rank score (0-100, higher = more undervalued) | NUMERIC(10,4) | Calculated | Quarterly | 72.50 |

### Sentiment Data Fields

| Field Name | Description | Data Type | Source | Frequency | Example |
|---|---|---|---|---|---|
| `headline` | News article headline text | TEXT | GDELT/Yahoo Finance | Daily | "Apple Reports Record Revenue" |
| `description` | Article summary or body text | TEXT | GDELT/Yahoo Finance | Daily | "Apple Inc reported..." |
| `source_name` | Name of the news publisher | VARCHAR(255) | GDELT/Yahoo Finance | Daily | "reuters.com" |
| `published_at` | Article publication date/time | TIMESTAMP | GDELT/Yahoo Finance | Daily | "2025-10-28T14:30:00Z" |
| `vader_compound` | VADER sentiment compound score (-1 to +1) | DECIMAL | Calculated (VADER) | Daily | 0.7003 |
| `vader_pos` | Positive sentiment proportion (0 to 1) | DECIMAL | Calculated (VADER) | Daily | 0.594 |
| `vader_neg` | Negative sentiment proportion (0 to 1) | DECIMAL | Calculated (VADER) | Daily | 0.000 |
| `vader_neu` | Neutral sentiment proportion (0 to 1) | DECIMAL | Calculated (VADER) | Daily | 0.406 |
| `sentiment_class` | Classification: "positive", "negative", or "neutral" | VARCHAR | Calculated | Daily | "positive" |
| `avg_sentiment` | Average compound score across all articles for a company | NUMERIC(8,4) | Calculated | Weekly/Monthly | 0.35 |
| `positive_count` | Number of positive articles | INTEGER | Calculated | Weekly/Monthly | 18 |
| `negative_count` | Number of negative articles | INTEGER | Calculated | Weekly/Monthly | 4 |
| `neutral_count` | Number of neutral articles | INTEGER | Calculated | Weekly/Monthly | 2 |
| `total_articles` | Total articles analysed | INTEGER | Calculated | Weekly/Monthly | 24 |
| `positive_ratio` | Fraction of articles that are positive | NUMERIC(8,4) | Calculated | Weekly/Monthly | 0.75 |
| `sentiment_score` | Final weighted sentiment score (0-100) | NUMERIC(10,4) | Calculated | Weekly/Monthly | 68.00 |

### Composite Fields

| Field Name | Description | Data Type | Source | Frequency | Example |
|---|---|---|---|---|---|
| `composite_score` | 0.6 x value_score + 0.4 x sentiment_score | NUMERIC(10,4) | Calculated | Weekly/Monthly | 70.70 |
| `rank` | Company rank by composite score (1 = best) | INTEGER | Calculated | Weekly/Monthly | 15 |
| `invest_decision` | TRUE if company passes all filters and is in top 20% | BOOLEAN | Calculated | Weekly/Monthly | TRUE |

### Price Data Fields

| Field Name | Description | Data Type | Source | Frequency | Example |
|---|---|---|---|---|---|
| `symbol` | Ticker symbol | VARCHAR(12) | company_static | Static | "AAPL" |
| `cob_date` | Close-of-business date | DATE | Yahoo Finance | Daily | "2025-01-15" |
| `open_price` | Opening price | NUMERIC(18,6) | Yahoo Finance | Daily | 150.250000 |
| `high_price` | Highest price during the day | NUMERIC(18,6) | Yahoo Finance | Daily | 152.100000 |
| `low_price` | Lowest price during the day | NUMERIC(18,6) | Yahoo Finance | Daily | 149.800000 |
| `close_price` | Closing price | NUMERIC(18,6) | Yahoo Finance | Daily | 151.500000 |
| `adj_close_price` | Adjusted close (accounts for splits and dividends) | NUMERIC(18,6) | Yahoo Finance | Daily | 151.500000 |
| `volume` | Number of shares traded | BIGINT | Yahoo Finance | Daily | 48523100 |
| `currency` | Price currency (USD, GBP, EUR, CAD, CHF) | CHAR(3) | Inferred from ticker suffix | Static | "USD" |

---

## 9. Data Lineage

This section traces how data flows from its original source to its final storage location.

### Stage 1: EXTRACTION (Raw Data Collection)

| Source | What Is Extracted | Destination |
|---|---|---|
| PostgreSQL `company_static` | List of 678 company tickers and names | In-memory DataFrame |
| Yahoo Finance API | Daily OHLCV prices (5 years) | MinIO + PostgreSQL |
| Yahoo Finance API | Company info with financial ratios | MinIO + MongoDB |
| Yahoo Finance API | Quarterly financial statements | MinIO + MongoDB |
| Yahoo Finance API | Recent news headlines | MongoDB + Kafka |
| GDELT REST API | News articles with tone scores | MongoDB + Kafka |
| Yahoo Finance API | FX rates for 4 currency pairs | MinIO + PostgreSQL |

### Stage 2: RAW STORAGE (Preserving Original Data)

| Data | Storage System | Location |
|---|---|---|
| Raw price CSV | MinIO | `raw-data/prices/{TICKER}/{DATE}.csv` |
| Raw financial statements JSON | MinIO + MongoDB | `raw-data/financial/{YEAR}/{TICKER}/statements.json` |
| Raw company info JSON | MinIO + MongoDB | `raw-data/company_info/{TICKER}/info.json` |
| Raw news articles JSON | MongoDB | `raw_news_articles` collection |
| Raw FX rate CSV | MinIO | `raw-data/fx/{PAIR}/{DATE}.csv` |

### Stage 3: PROCESSING (Transformation and Scoring)

| Input | Process | Output |
|---|---|---|
| Raw financial ratios | Percentile ranking across 678 companies | Value Score (0-100) |
| Raw news articles | VADER sentiment analysis + aggregation | Sentiment Score (0-100) |
| Value Score + Sentiment Score | Weighted combination + filtering + ranking | Composite Score + rank + invest_decision |
| Raw price data | Validation, type conversion, currency tagging | Clean price records |
| Raw FX data | Validation, pair identification | Clean FX records |

### Stage 4: CLEAN STORAGE (Analytics-Ready Data)

| Data | Storage | Table |
|---|---|---|
| Clean daily prices | PostgreSQL | `systematic_equity.daily_prices` |
| Value metrics and scores | PostgreSQL | `systematic_equity.value_metrics` |
| Sentiment scores | PostgreSQL | `systematic_equity.sentiment_scores` |
| Composite rankings | PostgreSQL | `systematic_equity.composite_rankings` |
| FX rates | PostgreSQL | `systematic_equity.fx_rates` |
| Pipeline audit trail | PostgreSQL | `systematic_equity.ingestion_log` |
| Run tracking metadata | PostgreSQL | `systematic_equity.pipeline_metadata` |

---

## 10. Data Quality Standards

| Check | Rule | Action if Failed |
|---|---|---|
| Missing P/E ratio | Company has no earnings data | Exclude from P/E ranking; still score on other available ratios |
| Negative P/E ratio | Company has negative earnings (losing money) | Exclude from P/E ranking; log warning; still score on P/B, EV/EBITDA, Dividend Yield |
| Extreme P/E ratio | P/E > 500 (unrealistically high) | Exclude from P/E ranking; log warning |
| Duplicate news articles | Same headline appears more than once | Deduplicate before sentiment scoring (keep first occurrence) |
| Insufficient article coverage | Fewer than 3 articles for a company | Flag as "low confidence"; still include in scoring |
| Empty API response | Yahoo Finance or GDELT returns no data | Retry up to 3 times with exponential backoff; if all retries fail, skip company and log error |
| NaN-filled price data | Yahoo Finance returns DataFrame with all-NaN Close prices (HTTP 401) | Detected via `Close.notna().any()` check; retries with exponential backoff before failing |
| Delisted ticker | Ticker belongs to a company that has been acquired, merged, or delisted | Skipped during extraction (73 confirmed delisted tickers); still counted in coverage denominator |
| Missing financial ratio | One or more ratios unavailable | Average only the available ratios (partial scoring) |
| API rate limiting | HTTP 429/401 response from Yahoo Finance or GDELT | Token Bucket rate limiter (2 req/s) + Circuit Breaker (opens after 15 consecutive failures, 60s recovery) + exponential backoff with jitter. Two-pass refetch for remaining gaps. |
| Stale data | Financial data not updated recently | Re-fetched on each pipeline run; `ingestion_timestamp` tracks freshness |
| Ratio unit conversion | yfinance returns `dividendYield` and `debtToEquity` as percentages (e.g., 2.7 = 2.7%, 102 = 102%) | Both are divided by 100 in `value_scorer.py` before storage — dividend_yield stored as decimal (0.027), debt_equity stored as ratio (1.02) |

---

## 11. Prerequisites

Before you can run this project, you need the following software installed on your computer:

### Required Software

| Software | Version | What It Does | How to Install |
|---|---|---|---|
| **Python** | 3.10 or newer | Runs the pipeline code | Download from [python.org](https://www.python.org/downloads/) or use your system package manager |
| **Docker** | Latest | Runs the databases (PostgreSQL, MongoDB, MinIO, Kafka) in containers | Download [Docker Desktop](https://www.docker.com/products/docker-desktop/) for Mac/Windows, or install Docker Engine on Linux |
| **Docker Compose** | v2+ | Coordinates multiple Docker containers | Included with Docker Desktop; on Linux, install `docker-compose-plugin` |
| **Poetry** | 1.7+ | Manages Python package dependencies | `pip install poetry` or follow [Poetry installation guide](https://python-poetry.org/docs/) |
| **Git** | Latest | Version control and code submission | Usually pre-installed on Mac/Linux; download from [git-scm.com](https://git-scm.com/) for Windows |

### Important: Docker PATH Setup

On **macOS**, Docker Desktop installs its command-line tools in a location that may not be in your system PATH by default. If `docker` commands return `command not found`, you need to add Docker to your PATH.

**Option A — Add Docker to PATH for the current terminal session (temporary):**

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

**Option B — Add Docker to PATH permanently (recommended):**

Add the following line to your shell profile file (`~/.zshrc` for macOS Catalina+, or `~/.bashrc` for Linux/older Mac):

```bash
echo 'export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**On Windows**, Docker Desktop should automatically add `docker` to your PATH during installation. If it doesn't, restart your terminal or add `C:\Program Files\Docker\Docker\resources\bin` to your system PATH through System Properties → Environment Variables.

**On Linux**, if you installed Docker via apt/dnf, it should already be in your PATH. If you installed Docker Desktop for Linux, add the symlinks:

```bash
sudo ln -s /opt/docker-desktop/bin/docker /usr/local/bin/docker
sudo ln -s /opt/docker-desktop/bin/docker-compose /usr/local/bin/docker-compose
```

### Checking Your Installation

```bash
# Check Python version (must be 3.10+)
python3 --version

# Check Docker is running (if this fails, see Docker PATH Setup above)
docker --version
docker compose version

# Check Poetry is installed
poetry --version

# Check Git is installed
git --version
```

**Expected output for each command:**
```
# python3 --version
Python 3.10.x  (or higher, e.g., 3.11.x, 3.12.x, 3.13.x)

# docker --version
Docker version 27.x.x, build xxxxxxx

# docker compose version
Docker Compose version v2.x.x

# poetry --version
Poetry (version 1.7.x or higher)

# git --version
git version 2.x.x
```

If any of these commands fails with `command not found`, install the missing software using the links in the Required Software table above. For Docker specifically, see the **Docker PATH Setup** section above.

---

## 12. Installation Guide (Step-by-Step)

Follow these steps **in order**. Each step includes the exact commands to type and what you should see on screen.

### Step 1: Clone the Repository

Open a terminal (Terminal app on Mac, or Command Prompt / PowerShell on Windows).

```bash
git clone https://github.com/YOUR-USERNAME/ift_coursework_2025.git
cd ift_coursework_2025/team_09/coursework_one
```

**What you should see:** The terminal prompt should now show you are inside the `coursework_one` folder. If you type `ls`, you should see files like `Main.py`, `pyproject.toml`, `docker-compose.yml`, and folders like `modules/`, `test/`, `config/`.

```bash
# Verify you are in the right directory
ls
```

**Expected output:**
```
Main.py          config/          docs/            modules/         static/
README.md        docker-compose.yml  .env.example  pyproject.toml   test/
```

### Step 2: Start the Docker Infrastructure

This step starts all the database systems (PostgreSQL, MongoDB, MinIO, Kafka) inside Docker containers. You do NOT need to install any of these databases on your computer — Docker handles everything.

**First, make sure Docker Desktop is running** (open the Docker Desktop application if it is not already running). You can verify Docker is working:

```bash
docker --version
```

**Expected output** (version numbers may vary):
```
Docker version 27.x.x, build xxxxxxx
```

If you see `command not found`, Docker is not in your PATH. **On macOS**, run this first:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

Or add it permanently to your shell profile (see [Prerequisites — Docker PATH Setup](#important-docker-path-setup) for full instructions on all operating systems). Then try `docker --version` again.

**Now start all services:**

```bash
docker compose up -d
```

**Expected output** (first time will show downloading/pulling messages):
```
[+] Running 8/8
 ✔ Network coursework_one_default  Created
 ✔ Container postgres_db_cw         Started
 ✔ Container mongo_db_cw           Started
 ✔ Container miniocw               Started
 ✔ Container zookeeper             Started
 ✔ Container kafka                 Started
 ✔ Container postgres_seed_cw      Started
 ✔ Container mongo_seed_cw         Started
 ✔ Container minio_seed_cw         Started
```

**Wait 15-20 seconds**, then verify all services are running:

```bash
docker compose ps
```

**Expected output:**
```
NAME              IMAGE                      STATUS
kafka             confluentinc/cp-kafka      Up (healthy)
miniocw           minio/minio                Up (healthy)
minio_seed_cw     minio/mc                   Exited (0)
mongo_seed_cw     mongodb/mongodb-community  Exited (0)
mongo_db_cw       mongodb/mongodb-community  Up (healthy)
postgres_db_cw    postgres:16                Up (healthy)
postgres_seed_cw  postgres:16                Exited (0)
zookeeper         confluentinc/cp-zookeeper  Up (healthy)
```

**Key things to check:**
- `postgres_db_cw`, `mongo_db_cw`, `miniocw`, `kafka`, `zookeeper` should all say **"Up (healthy)"**
- `postgres_seed_cw`, `mongo_seed_cw`, `minio_seed_cw` should say **"Exited (0)"** — this is normal, they run once to initialise the databases and then stop. Exit code 0 means they completed successfully.

**If something shows "Exited (1)" or "Restarting"**, check the logs:

```bash
# Check logs for a specific service (replace SERVICE_NAME)
docker compose logs postgres-db
docker compose logs mongodb
docker compose logs kafka
```

### Step 3: Verify the Database Was Seeded Correctly

Before installing Python dependencies, let's verify the databases were set up correctly.

**Check that 678 companies were loaded into PostgreSQL:**

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c \
  "SELECT COUNT(*) AS total_companies FROM systematic_equity.company_static;"
```

**Expected output:**
```
 total_companies
-----------------
             678
(1 row)
```

**Check the company breakdown by country:**

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c \
  "SELECT country, COUNT(*) AS companies FROM systematic_equity.company_static GROUP BY country ORDER BY companies DESC;"
```

**Expected output** (approximate):
```
 country | companies
---------+-----------
 USA     |       500
 GBR     |        50
 FRA     |        30
 DEU     |        25
 ...     |       ...
```

**Check that all 8 PostgreSQL tables exist:**

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'systematic_equity' ORDER BY table_name;"
```

**Expected output:**
```
     table_name
---------------------
 company_static
 composite_rankings
 daily_prices
 fx_rates
 ingestion_log
 pipeline_metadata
 sentiment_scores
 value_metrics
(8 rows)
```

**Check that the MinIO bucket was created:**

```bash
docker exec miniocw mc ls local/
```

**Expected output** (should show the `iftbigdata` bucket):
```
[2026-xx-xx xx:xx:xx xxx] 0B iftbigdata/
```

### Step 4: Install Python Dependencies

Poetry manages all Python packages. This step installs everything the project needs.

```bash
poetry install
```

**Expected output** (first time will take 1-2 minutes):
```
Installing dependencies from lock file

Package operations: XX installs, 0 updates, 0 removals

  - Installing certifi (20XX.XX.XX)
  - Installing charset-normalizer (X.X.X)
  ...
  - Installing yfinance (0.2.XX)
  - Installing vaderSentiment (3.3.2)
  ...

Installing the current project: coursework_one (1.0.0)
```

**Verify the installation worked:**

```bash
poetry run python -c "import yfinance; import pandas; import vaderSentiment; print('All dependencies installed successfully')"
```

**Expected output:**
```
All dependencies installed successfully
```

### Step 5: Set Up Environment Variables

The `.env.dev` file contains database credentials and connection strings. The example file has default values that match the Docker Compose configuration.

```bash
# Copy the example environment file
cp .env.example .env.dev
```

**Verify the file was created:**

```bash
cat .env.dev
```

**Expected output** (the default values work out of the box):
```
POSTGRES_HOST=localhost
POSTGRES_PORT=5439
POSTGRES_DB=fift
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
MONGO_HOST=localhost
MONGO_PORT=27019
...
```

**You do NOT need to change any values** — the defaults match the Docker Compose setup.

### Step 6: Run the Test Suite

Before running the pipeline, verify everything is correctly configured by running the automated tests. This does NOT require Docker or any external services — all tests use mocked dependencies.

```bash
poetry run pytest ./test/ -v --cov=modules
```

**Expected output** (this runs 582 tests and takes about 3-4 minutes):
```
============================= test session starts ==============================
...
test/test_config_and_args.py::TestArgParser::test_minimal_args PASSED
test/test_config_and_args.py::TestArgParser::test_default_frequency PASSED
...
test/test_value_scorer.py::TestValueScorer::test_percentile_ranking PASSED
test/test_value_scorer.py::TestValueScorer::test_negative_pe_excluded PASSED
...
test/test_sentiment_scorer.py::TestSentimentScorer::test_vader_positive PASSED
test/test_sentiment_scorer.py::TestSentimentScorer::test_deduplication PASSED
...
test/test_composite_scorer.py::TestCompositeScorer::test_invest_decision PASSED
...

---------- coverage: -------- ---------
Name                                            Stmts   Miss  Cover
-----------------------------------------------------------------------------
modules/processing/value_scorer.py                 63      0   100%
modules/processing/sentiment_scorer.py             79      5    94%
modules/processing/composite_scorer.py             45      0   100%
modules/processing/data_cleaner.py                 68      7    90%
modules/utils/config_reader.py                     21      0   100%
...
-----------------------------------------------------------------------------
TOTAL                                            2496    159    94%

========================= 632 passed in 298s ==========================
```

**Key things to check:**
- All 583 tests should say **PASSED** (zero FAILED)
- Overall coverage should be **84%** or higher (target: 80%+)
- No errors or warnings

### Step 7: Run the Pipeline

Now you are ready to run the actual data pipeline, which will download real data from Yahoo Finance and GDELT.

```bash
# Weekly run (most common — recommended for first execution)
poetry run python Main.py --env_type dev --frequency weekly
```

**What happens when you run this** (the pipeline will display detailed output for each stage):

1. A banner showing the pipeline version and run configuration
2. Full configuration dump (database connections, scoring parameters, data sources)
3. Company universe breakdown (678 companies by country and sector)
4. Per-ticker extraction progress with batch tracking
5. FX rate extraction for 4 currency pairs
6. News article extraction from GDELT and Yahoo Finance
7. Price data loading counts
8. Value Score distribution and Top 10 most undervalued companies
9. Sentiment Score distribution and Top 10 most positive companies
10. Composite ranking results and Top 20 investment candidates
11. Final pipeline summary with total records and elapsed time

**Note:** The first full run (weekly or quarterly) processes all 678 companies and may take 30-60 minutes depending on your internet speed and API response times. You can test with a smaller set first:

```bash
# Quick test with just 3 companies (takes ~1 minute)
poetry run python Main.py --env_type dev --frequency weekly --tickers AAPL MSFT GOOGL

# Dry run — validates configuration without downloading any data
poetry run python Main.py --env_type dev --dry_run
```

---

## 13. How to Run the Pipeline

### Full Run Command (Copy-Paste This)

This is the single command to run the entire pipeline end-to-end for all 678 companies with default settings (5-year lookback, all data sources):

```bash
# IMPORTANT: On macOS, ensure Docker is in your PATH first:
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

# Make sure Docker services are running
docker compose up -d

# Run the full pipeline (all 678 companies, all data sources, 5-year history)
poetry run python Main.py --env_type dev --frequency quarterly
```

This will:
1. Load 678 companies from the investable universe
2. Download 5 years of daily stock prices from Yahoo Finance
3. Download financial ratios (P/E, P/B, EV/EBITDA, Dividend Yield, Debt/Equity)
4. Download FX rates for 4 currency pairs (GBPUSD, EURUSD, CADUSD, CHFUSD)
5. Extract news articles from GDELT and Yahoo Finance
6. Compute Value Scores (percentile-rank, 0-100 scale)
7. Compute Sentiment Scores (VADER NLP, 0-100 scale)
8. Compute Composite Rankings (60% Value + 40% Sentiment)
9. Flag top 20% as investment candidates
10. Store everything in PostgreSQL, MongoDB, MinIO, and Kafka

**Expected runtime: 30-60 minutes** (depends on internet speed and API response times).

### Basic Commands

```bash
# Weekly run in development environment (most common usage)
poetry run python Main.py --env_type dev --frequency weekly

# Daily incremental update (only fetches recent data)
poetry run python Main.py --env_type dev --frequency daily

# Monthly full refresh
poetry run python Main.py --env_type dev --frequency monthly

# Quarterly with full 5-year lookback and schema re-creation
poetry run python Main.py --env_type dev --frequency quarterly --init_schema

# Docker environment (use when running from inside a Docker container)
poetry run python Main.py --env_type docker --frequency weekly
```

### Advanced Options

```bash
# Run only specific data sources (skip what you don't need)
poetry run python Main.py --env_type dev --sources prices          # Only stock prices
poetry run python Main.py --env_type dev --sources news            # Only news articles
poetry run python Main.py --env_type dev --sources prices news     # Prices and news
poetry run python Main.py --env_type dev --sources prices news fx  # Everything

# Change the historical data lookback period (default: 5 years)
poetry run python Main.py --env_type dev --frequency quarterly --lookback_years 2   # 2-year history
poetry run python Main.py --env_type dev --frequency quarterly --lookback_years 5   # 5-year history (default)
poetry run python Main.py --env_type dev --frequency quarterly --lookback_years 6   # 6-year history
poetry run python Main.py --env_type dev --frequency quarterly --lookback_years 10  # 10-year history

# Process only specific companies (useful for testing)
poetry run python Main.py --env_type dev --tickers AAPL MSFT GOOGL

# Custom batch size (smaller batches = slower but less likely to hit rate limits)
poetry run python Main.py --env_type dev --batch_size 25

# Validate configuration without actually downloading any data
poetry run python Main.py --env_type dev --dry_run

# Backfill data for a specific date
poetry run python Main.py --env_type dev --run_date 2024-06-15

# Combine multiple options (10-year quarterly refresh for 3 specific tickers)
poetry run python Main.py --env_type dev --frequency quarterly --lookback_years 10 --tickers AAPL MSFT GOOGL
```

### How the Lookback Period Works

The `--lookback_years` argument controls how far back in history the pipeline fetches data. This only affects **quarterly** frequency runs (which do a full historical download). For daily/weekly/monthly runs, shorter incremental windows are used regardless of the lookback setting.

| Lookback | Date Range (if run today) | Best For |
|---|---|---|
| `2` years | 2024-03-01 to 2026-03-01 | Quick testing, recent-data-only analysis |
| `5` years | 2021-03-01 to 2026-03-01 | **Default** — matches assignment specification |
| `6` years | 2020-03-01 to 2026-03-01 | Extended history including COVID-19 period |
| `10` years | 2016-03-01 to 2026-03-01 | Deep historical analysis, long-term backtesting |

### Command-Line Arguments Reference

| Argument | Required | Default | Description |
|---|---|---|---|
| `--env_type` | Yes | — | Environment profile: `dev` (local) or `docker` (containerised) |
| `--frequency` | No | `weekly` | Run frequency: `daily`, `weekly`, `monthly`, `quarterly` |
| `--lookback_years` | No | `5` | Historical data lookback in years: `2`, `5`, `6`, or `10` |
| `--run_date` | No | Today | Specific date to run for (format: YYYY-MM-DD) |
| `--sources` | No | `prices financials news fx` | Which data sources to process |
| `--tickers` | No | All 678 | Specific ticker symbols to process |
| `--batch_size` | No | 50 | Number of companies per batch |
| `--init_schema` | No | False | Re-create database tables before running |
| `--dry_run` | No | False | Validate config and exit without downloading |

---

## 14. Configuration Guide

### config/conf.yaml

The pipeline reads all settings from `config/conf.yaml`. The file contains two environment profiles:

- **`dev`**: For running locally (PostgreSQL on localhost:5439, etc.)
- **`docker`**: For running inside Docker containers (PostgreSQL on postgres_db:5432, etc.)

Key configuration sections:

```yaml
# Database connections
Database:
  Postgres:
    Host: localhost          # Database server address
    Port: 5439               # External port (mapped from Docker's internal 5432)
    Database: fift           # Database name
    Schema: systematic_equity # Schema containing all tables
  MongoDB:
    Host: localhost
    Port: 27019
    Database: ift_cw1_sentiment
  Minio:
    BucketName: iftbigdata
    RawDataPath: raw-data
  Kafka:
    BootstrapServers: localhost:9092

# Pipeline parameters
Pipeline:
  lookback_years: 5          # How many years of historical data to fetch
  batch_size: 50             # Companies per processing batch
  delay_between_batches: 2   # Seconds between batches (rate limiting)
  max_retries: 3             # Retry attempts per API call

# Scoring weights and filters
Scoring:
  value_weight: 0.6          # 60% weight for Value Score
  sentiment_weight: 0.4      # 40% weight for Sentiment Score
  max_debt_equity: 2.0       # Exclude companies with D/E above this
  min_sentiment: 0.0         # Exclude companies with negative average sentiment
  min_articles: 3            # Minimum articles for reliable sentiment

# Data source toggles
DataSources:
  yfinance:
    enabled: true
  gdelt:
    enabled: true
    timespan: 3months        # How far back to search for news
    max_records: 50           # Max articles per company
  newsapi:
    enabled: false            # Optional — requires API key
```

### Environment Variables

The `.env.dev` file contains database credentials and connection strings. The default values match the Docker Compose configuration and require no changes for standard development use.

---

## 15. Project Structure

```
team_07 Wald/
├── CHANGELOG.md                             # Version history and changes
├── coursework_one/
│   ├── main.py                              # Pipeline entry point (orchestrator)
│   ├── pyproject.toml                       # Poetry config + all dependencies
│   ├── poetry.lock                          # Locked dependency versions
│   ├── docker-compose.yml                   # Docker infrastructure (8 services)
│   ├── .env.dev                             # Development environment variables
│   ├── .env.example                         # Template for environment variables
│   ├── .flake8                              # Linting configuration (line length 120)
│   ├── .gitignore                           # Git ignore rules
│   ├── README.md                            # This file
│   │
│   ├── config/
│   │   └── conf.yaml                        # YAML config (dev + docker profiles)
│   │
│   ├── docs/                                # Sphinx documentation
│   │   ├── conf.py                          # Sphinx configuration
│   │   ├── index.rst                        # Documentation root
│   │   └── Makefile                         # Documentation build script
│   │
│   ├── modules/                             # All Python source modules
│   │   ├── __init__.py
│   │   ├── db/                              # Database connection modules
│   │   │   ├── __init__.py
│   │   │   ├── postgres_connection.py       # PostgreSQL via SQLAlchemy + Pydantic
│   │   │   ├── mongo_connection.py          # MongoDB via PyMongo
│   │   │   └── minio_connection.py          # MinIO S3-compatible client
│   │   ├── extraction/                      # Data extraction from external APIs
│   │   │   ├── __init__.py
│   │   │   ├── company_loader.py            # Load 678-company universe from PostgreSQL
│   │   │   ├── yahoo_finance_extractor.py   # Yahoo Finance: prices, info, financials, news
│   │   │   ├── fx_extractor.py              # FX rates for 4 currency pairs
│   │   │   ├── gdelt_extractor.py           # GDELT REST API news extraction
│   │   │   └── newsapi_extractor.py         # NewsAPI.org news extraction (tier 3 gap-fill)
│   │   ├── processing/                      # Data transformation and scoring
│   │   │   ├── __init__.py
│   │   │   ├── data_cleaner.py              # Data validation and type conversion
│   │   │   ├── value_calculator.py          # Raw value metric calculations
│   │   │   ├── value_scorer.py              # Percentile-rank Value Score (0-100)
│   │   │   ├── sentiment_analyzer.py        # Raw NLP sentiment analysis
│   │   │   ├── sentiment_scorer.py          # VADER NLP Sentiment Score (0-100)
│   │   │   └── composite_scorer.py          # Combined ranking + invest decision
│   │   ├── loading/                         # Data persistence to databases
│   │   │   ├── __init__.py
│   │   │   ├── postgres_loader.py           # Upsert operations for all PostgreSQL tables
│   │   │   ├── mongo_loader.py              # MongoDB document insert/query operations
│   │   │   └── minio_uploader.py            # MinIO file upload operations
│   │   ├── kafka/                           # Event streaming
│   │   │   ├── __init__.py
│   │   │   ├── kafka_handler.py             # Kafka Producer + Consumer (combined)
│   │   │   ├── consumer.py                  # Kafka consumer implementation
│   │   │   └── producer.py                  # Kafka producer implementation
│   │   └── utils/                           # Shared utilities
│   │       ├── __init__.py
│   │       ├── logger.py                    # IFTLogger (with stdlib fallback)
│   │       ├── config_reader.py             # CLI argument parser + date range computation
│   │       ├── circuit_breaker.py           # Circuit breaker for fault tolerance
│   │       ├── parallel.py                  # Parallel execution utilities
│   │       ├── progress.py                  # Progress tracking utilities
│   │       ├── rate_limiter.py              # API rate limiting
│   │       └── retry_handler.py             # Retry logic with exponential backoff
│   │
│   ├── static/
│   │   └── schema/
│   │       ├── create_tables.sql            # PostgreSQL DDL for all 8 tables
│   │       ├── company_static.csv           # 678-company investable universe
│   │       └── seed.sh                      # Docker seed script (runs on first startup)
│   │
│   └── test/                                # Comprehensive pytest test suite
│       ├── __init__.py
│       ├── conftest.py                      # Shared test fixtures and configuration
│       ├── test_config_and_args.py          # Configuration and CLI argument tests
│       ├── test_data_cleaner.py             # Data cleaning and validation tests
│       ├── test_value_calculator.py         # Value metric calculation tests
│       ├── test_value_scorer.py             # Value score calculation tests
│       ├── test_sentiment_analyzer.py       # Sentiment analysis tests
│       ├── test_sentiment_scorer.py         # Sentiment scoring tests
│       ├── test_composite_scorer.py         # Composite scoring and ranking tests
│       ├── test_extraction.py               # Extraction module tests (YF, GDELT, FX)
│       ├── test_fx_extractor.py             # FX extractor unit tests
│       ├── test_gdelt.py                    # GDELT extractor unit tests
│       ├── test_newsapi_extractor.py        # NewsAPI extractor unit tests
│       ├── test_yahoo_finance.py            # Yahoo Finance extractor unit tests
│       ├── test_db_and_loading.py           # Database connection and loader tests
│       ├── test_minio_uploader.py           # MinIO uploader unit tests
│       ├── test_postgres_connection.py      # PostgreSQL connection tests
│       ├── test_kafka_and_loaders.py        # Kafka and MinIO/Mongo loader tests
│       ├── test_kafka_modules.py            # Kafka module unit tests
│       ├── test_logger.py                   # Logger utility tests
│       ├── test_parallel.py                 # Parallel utility tests
│       ├── test_progress.py                 # Progress utility tests
│       ├── test_retry_handler.py            # Retry handler tests
│       ├── test_pipeline_e2e.py             # End-to-end pipeline tests
│       └── test_integration.py              # Integration tests (multi-module flows)
```

---

## 16. Module Reference

### Extraction Layer

| Module | Key Functions | Description |
|---|---|---|
| `company_loader` | `load_companies()`, `prepare_ticker()`, `partition_tickers()`, `infer_currency()` | Loads the 678-company universe from PostgreSQL `company_static` table. Partitions into active (603) and delisted (75) tickers. Handles ticker cleaning, Swiss exchange remapping (`.S` → `.SW`), and share class remapping (`.B` → `-B`). |
| `yahoo_finance_extractor` | `fetch_price_history()`, `fetch_company_info()`, `fetch_financial_data()`, `fetch_news()`, `fetch_all_companies()` | Extracts daily OHLCV prices, pre-computed financial ratios, quarterly financial statements, and news headlines from Yahoo Finance via the `yfinance` library. Detects NaN-filled responses (HTTP 401) and retries with exponential backoff. Processes in configurable batches with rate limiting. |
| `fx_extractor` | `fetch_fx_rates()` | Downloads daily FX rates for GBPUSD, EURUSD, CADUSD, CHFUSD pairs from Yahoo Finance to normalise cross-country valuations to USD. |
| `gdelt_extractor` | `fetch_news_gdelt()`, `fetch_all_companies_news()` | Fetches news articles from the GDELT Project REST API v2. Searches by company name (not ticker) for better results. Returns headlines, URLs, sources, dates, and GDELT tone scores. Used as tier 2 gap-fill in the news cascade. |
| `newsapi_extractor` | `fetch_news_newsapi()` | Fetches news articles from the NewsAPI.org `/v2/everything` endpoint. Free tier: 100 req/day, 1-month history. Requires API key (`NEWSAPI_KEY`). Implements retry with exponential backoff, 429 rate limit handling, 401 early exit. Used as tier 3 gap-fill in the news cascade for tickers still with 0 articles after YF and GDELT. |

### Processing Layer

| Module | Key Functions | Description |
|---|---|---|
| `data_cleaner` | `clean_price_dataframe()`, `clean_fx_dataframe()`, `validate_company_info()` | Validates and converts raw API data into clean records suitable for PostgreSQL insertion. Handles missing values, type conversion, and currency tagging. |
| `value_scorer` | `compute_value_scores()` | Computes percentile-rank Value Scores (0-100) for all companies. Ranks on P/E, P/B, EV/EBITDA, Dividend Yield. Excludes negative and extreme P/E. D/E stored but not scored. Converts yfinance percentage-format `dividendYield` and `debtToEquity` to decimals (÷100) before storage. |
| `sentiment_scorer` | `get_analyser()`, `score_text()`, `score_articles()`, `deduplicate_articles()`, `aggregate_sentiment()`, `compute_all_sentiment()` | Runs VADER sentiment analysis on news headlines + descriptions. Deduplicates articles. Computes weighted Sentiment Score using the 3-component formula (avg compound + positive ratio + volume factor). |
| `composite_scorer` | `compute_composite_scores()` | Combines Value and Sentiment scores with configurable weights (default 60/40). Applies D/E and sentiment filters. Ranks companies and flags top quintile for investment. |

### Loading Layer

| Module | Key Functions | Description |
|---|---|---|
| `postgres_loader` | `upsert_daily_prices()`, `upsert_value_metrics()`, `upsert_sentiment_scores()`, `upsert_composite_rankings()`, `upsert_fx_rates()`, `insert_ingestion_log()` | INSERT ... ON CONFLICT DO UPDATE operations for all PostgreSQL tables. Ensures idempotent, re-runnable pipeline execution. Also writes audit trail entries. |
| `mongo_loader` | `store_news_articles()`, `store_articles_for_company()`, `get_company_articles()`, `get_articles_by_date_range()` | Inserts raw news articles into MongoDB `raw_news_articles` collection. Supports querying by company and date range. |
| `minio_uploader` | `upload_price_data()`, `upload_financial_data()`, `upload_news_articles()`, `upload_company_info()` | Uploads raw CSV and JSON files to MinIO data lake with proper folder structure for full data lineage. |

### Kafka Layer

| Module | Key Functions | Description |
|---|---|---|
| `kafka_handler` | `EventProducer` (class), `EventConsumer` (class), `get_event_producer()` | Producer publishes news articles and value metrics as JSON events to Kafka topics. Consumer subscribes to topics and processes messages via callback. Graceful degradation when Kafka is unavailable. |

### Utility Layer

| Module | Key Functions | Description |
|---|---|---|
| `config_reader` | `arg_parse_cmd()`, `compute_date_range()` | Parses CLI arguments (env_type, frequency, run_date, sources, tickers, etc.) and computes appropriate date ranges based on frequency and lookback period. |
| `logger` | `pipeline_logger`, `generate_run_id()` | Provides structured logging via IFTLogger (from ift_global) with automatic fallback to Python standard library logging. Generates unique run IDs for audit trail. |

---

## 17. Database Schema

The PostgreSQL schema consists of **8 tables** in the `systematic_equity` schema within the `fift` database. All tables support **upsert** (INSERT ... ON CONFLICT DO UPDATE) for idempotent pipeline execution.

### Table: `company_static` — Investable Universe
| Column | Type | Description |
|---|---|---|
| symbol | VARCHAR(12) PK | Ticker symbol (e.g., "AAPL", "VOD.L") |
| security | TEXT | Full company name |
| gics_sector | TEXT | GICS sector classification |
| gics_industry | TEXT | GICS industry classification |
| country | CHAR(3) | Country code |
| region | TEXT | Geographic region |

### Table: `daily_prices` — 5-Year OHLCV History
| Column | Type | Description |
|---|---|---|
| symbol | VARCHAR(12) PK | Ticker symbol |
| cob_date | DATE PK | Close-of-business date |
| open_price | NUMERIC(18,6) | Opening price |
| high_price | NUMERIC(18,6) | Day's high |
| low_price | NUMERIC(18,6) | Day's low |
| close_price | NUMERIC(18,6) | Closing price |
| adj_close_price | NUMERIC(18,6) | Split/dividend adjusted close |
| volume | BIGINT | Shares traded |
| currency | CHAR(3) | Price currency |
| ingestion_timestamp | TIMESTAMPTZ | When this record was inserted/updated |

### Table: `value_metrics` — Financial Ratios and Value Score
| Column | Type | Description |
|---|---|---|
| company_id | VARCHAR(12) UNIQUE | Ticker symbol |
| date | DATE UNIQUE | Score date |
| pe_ratio | NUMERIC(18,4) | Price-to-Earnings |
| pb_ratio | NUMERIC(18,4) | Price-to-Book |
| ev_ebitda | NUMERIC(18,4) | EV/EBITDA |
| dividend_yield | NUMERIC(18,6) | Dividend Yield |
| debt_equity | NUMERIC(18,4) | Debt/Equity (filter only) |
| value_score | NUMERIC(10,4) | Composite value score (0-100) |
| ingestion_timestamp | TIMESTAMPTZ | Insert/update time |

### Table: `sentiment_scores` — VADER Sentiment Aggregates
| Column | Type | Description |
|---|---|---|
| company_id | VARCHAR(12) UNIQUE | Ticker symbol |
| date | DATE UNIQUE | Score date |
| avg_sentiment | NUMERIC(8,4) | Average VADER compound (-1 to +1) |
| positive_count | INTEGER | Number of positive articles |
| negative_count | INTEGER | Number of negative articles |
| neutral_count | INTEGER | Number of neutral articles |
| total_articles | INTEGER | Total articles scored |
| positive_ratio | NUMERIC(8,4) | Fraction of positive articles |
| sentiment_score | NUMERIC(10,4) | Weighted sentiment score (0-100) |
| ingestion_timestamp | TIMESTAMPTZ | Insert/update time |

### Table: `composite_rankings` — Final Investment Decision
| Column | Type | Description |
|---|---|---|
| company_id | VARCHAR(12) UNIQUE | Ticker symbol |
| date | DATE UNIQUE | Score date |
| value_score | NUMERIC(10,4) | Value Score |
| sentiment_score | NUMERIC(10,4) | Sentiment Score |
| composite_score | NUMERIC(10,4) | 0.6 x Value + 0.4 x Sentiment |
| rank | INTEGER | Rank (1 = best) |
| invest_decision | BOOLEAN | TRUE if in top quintile and passes filters |
| ingestion_timestamp | TIMESTAMPTZ | Insert/update time |

### Table: `fx_rates` — Daily Exchange Rates
| Column | Type | Description |
|---|---|---|
| currency_pair | VARCHAR(12) PK | Pair identifier (e.g., "GBPUSD=X") |
| cob_date | DATE PK | Date |
| open_rate / high_rate / low_rate / close_rate | NUMERIC(18,8) | OHLC rates |
| ingestion_timestamp | TIMESTAMPTZ | Insert/update time |

### Table: `ingestion_log` — Pipeline Audit Trail
| Column | Type | Description |
|---|---|---|
| log_id | SERIAL PK | Auto-increment ID |
| run_id | VARCHAR(64) | Unique pipeline run UUID |
| run_timestamp | TIMESTAMPTZ | When the event occurred |
| data_source | VARCHAR(32) | Source name (yfinance, gdelt, etc.) |
| symbol | VARCHAR(12) | Ticker (NULL for batch operations) |
| status | VARCHAR(16) | SUCCESS, FAILED, EMPTY, SKIPPED |
| rows_affected | INTEGER | Number of rows processed |
| error_message | TEXT | Error details (if failed) |
| run_frequency | VARCHAR(16) | daily, weekly, monthly, quarterly |
| date_range_start / date_range_end | DATE | Data range processed |

### Table: `pipeline_metadata` — Run Tracking
| Column | Type | Description |
|---|---|---|
| data_source | VARCHAR(32) PK | Source name |
| symbol | VARCHAR(12) PK | Ticker (or '__ALL__') |
| last_success_date | DATE | Last successful data date |
| last_run_timestamp | TIMESTAMPTZ | Last run time |

---

## 18. Testing

The project uses **pytest** as the testing framework with **583 tests** achieving **84% overall code coverage** (target: 80%+). Core modules achieve 94-100%: `value_scorer.py` (100%), `newsapi_extractor.py` (100%), `composite_scorer.py` (100%), `sentiment_scorer.py` (94%), `postgres_loader.py` (100%).

### Running Tests

```bash
# Run the full test suite with verbose output and coverage report
poetry run pytest ./test/ -v --cov=modules --cov-report=term-missing

# Run only unit tests (no Docker required)
poetry run pytest ./test/ -v -m "not integration"

# Run integration tests (requires Docker services running)
poetry run pytest ./test/ -v -m integration

# Generate an HTML coverage report (opens in browser)
poetry run pytest ./test/ --cov=modules --cov-report=html
# Then open htmlcov/index.html in your browser
```

### Test Coverage by Module

| Module | Coverage | Description |
|---|---|---|
| `modules/processing/value_scorer.py` | 100% | All value scoring logic fully tested |
| `modules/processing/sentiment_scorer.py` | 94% | Sentiment scoring, VADER analysis, deduplication |
| `modules/processing/composite_scorer.py` | 100% | Composite scoring, filtering, ranking |
| `modules/processing/data_cleaner.py` | 90% | Data validation and cleaning |
| `modules/processing/value_calculator.py` | 82% | Financial ratio calculation with multi-alias field extraction |
| `modules/utils/config_reader.py` | 100% | CLI parsing and date range computation |
| `modules/utils/circuit_breaker.py` | 100% | Circuit breaker state machine (3-state: CLOSED/OPEN/HALF_OPEN) |
| `modules/utils/rate_limiter.py` | 100% | Token bucket rate limiting (configurable rate + burst) |
| `modules/utils/retry_handler.py` | 98% | Exponential backoff with jitter |
| `modules/extraction/yahoo_finance_extractor.py` | 93% | Yahoo Finance API extraction with financial statement serialisation |
| `modules/extraction/gdelt_extractor.py` | 97% | GDELT API news extraction |
| `modules/extraction/newsapi_extractor.py` | 100% | NewsAPI news extraction (tier 3 gap-fill) |
| `modules/extraction/company_loader.py` | 89% | Company universe loading and delisted partitioning |
| `modules/extraction/fx_extractor.py` | 100% | FX rate extraction |
| `modules/kafka/kafka_handler.py` | 91% | Kafka producer and consumer |
| `modules/loading/postgres_loader.py` | 100% | PostgreSQL upsert operations |
| `modules/loading/mongo_loader.py` | 95% | MongoDB document storage |
| `modules/loading/minio_uploader.py` | 100% | MinIO data lake uploads |
| `modules/db/minio_connection.py` | 96% | MinIO S3-compatible client |
| `modules/db/mongo_connection.py` | 95% | MongoDB client |
| `modules/db/postgres_connection.py` | 99% | PostgreSQL SQLAlchemy client |
| `modules/utils/parallel.py` | 62% | Multi-level ThreadPoolExecutor with Token Bucket + Circuit Breaker + news cascade |

### Test Categories

- **Unit tests**: Test individual functions with mocked dependencies (no external services needed)
- **Integration tests**: Test multi-module flows with mocked databases
- **Edge case tests**: Negative P/E handling, empty data, extreme values, missing fields, API failures, deduplication, rate limiting

---

## 19. Code Quality

All code quality tools are configured in `pyproject.toml` and pass cleanly.

### Linting (flake8)

```bash
poetry run flake8 modules/ Main.py --max-line-length=120
# Result: 0 errors, 0 warnings
```

### Formatting (black)

```bash
poetry run black modules/ Main.py test/ --line-length 120 --check
# Result: All files correctly formatted
```

### Import Sorting (isort)

```bash
poetry run isort modules/ Main.py test/ --profile black --check-only
# Result: All imports correctly sorted
```

### Security Scanning (bandit)

```bash
poetry run bandit -r modules/ -c pyproject.toml
# Result: No high or medium severity issues
```

### Documentation (Sphinx)

All modules, classes, and functions have Sphinx-compatible docstrings using `:param`, `:type`, `:return`, `:rtype` notation.

```bash
# Generate HTML documentation
cd docs/
sphinx-build -b html . _build/html
# Open docs/_build/html/index.html in browser
```

---

## 20. Technology Choices and Alternatives

| Chosen Technology | Alternative(s) | Why We Chose It |
|---|---|---|
| **PostgreSQL** | MySQL, SQLite | Already provided in Docker; relational model fits structured financial ratios; supports complex queries and upsert (ON CONFLICT) |
| **MongoDB** | CouchDB, Elasticsearch | Already provided in Docker; document model fits variable-format news articles; native JSON support |
| **MinIO** | AWS S3, Local filesystem | Already provided in Docker; S3-compatible API for proper data lake pattern; free and self-hosted |
| **Apache Kafka** | RabbitMQ, Redis Streams | Already provided in Docker; industry standard for event streaming; good for decoupled news ingestion |
| **yfinance** | Alpha Vantage, Financial Modeling Prep | Free with no API key; comprehensive data coverage; well-maintained Python library |
| **GDELT** | NewsAPI only, Google News | Completely free with no rate limits; historical archive; built-in tone analysis |
| **VADER** | TextBlob, Transformers (BERT, FinBERT) | Lightweight and fast (no GPU needed); specifically designed for short-form text like news headlines; well-validated for financial sentiment |
| **Poetry** | pip, conda, pipenv | Required by assignment specification; superior dependency resolution and lock file management |
| **pytest** | unittest, nose2 | Required by assignment specification; powerful fixture system and plugin ecosystem |
| **SQLAlchemy** | psycopg2 directly, asyncpg | ORM provides connection pooling, session management, and parameterised queries out of the box |
| **Pydantic** | dataclasses, attrs | Automatic validation of configuration; type-safe settings management; works well with environment variables |

---

## 21. Troubleshooting

### "docker: command not found" (Docker Not in PATH)

This is the most common issue, especially on macOS. Docker Desktop installs its CLI tools in a non-standard location.

**Quick Fix (macOS):**
```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

**Permanent Fix (macOS) — add to your shell profile:**
```bash
echo 'export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Windows:** Restart your terminal, or add `C:\Program Files\Docker\Docker\resources\bin` to your system PATH via System Properties → Environment Variables → Path.

**Linux:** If using Docker Desktop for Linux, create symlinks:
```bash
sudo ln -s /opt/docker-desktop/bin/docker /usr/local/bin/docker
```

After fixing the PATH, verify it works:
```bash
docker --version
docker compose version
```

### Docker Services Won't Start

```bash
# Check if Docker Desktop is running (must be open as an application)
docker info

# Check service status
docker compose ps

# View logs for a specific service
docker compose logs postgres-db
docker compose logs mongodb

# Restart all services
docker compose down && docker compose up -d
```

### PostgreSQL Connection Refused

- Ensure Docker is running: `docker compose ps`
- Check the port: default external port is **5439** (not 5432)
- Verify credentials match `config/conf.yaml`: user=postgres, password=postgres, database=fift

### MongoDB Connection Issues

- Default port: 27019
- Default credentials: user=ift_bigdata, password=mongo_password
- Database name: ift_cw1_sentiment

### Tests Failing

```bash
# Make sure all dependencies are installed
poetry install

# If ift_global is not available, the logger falls back to stdlib — tests still work
# If you see import errors, install missing packages:
poetry add <package-name>
```

### Rate Limiting from Yahoo Finance

The pipeline has built-in defence-in-depth against Yahoo Finance rate limiting:

1. **Token Bucket rate limiter** — limits to 2 requests/second with burst capacity of 5
2. **Circuit Breaker** — opens after 15 consecutive failures, waits 60s before probe, auto-recovers after 2 successes
3. **Inter-request jitter** — random 0.3-0.8s delay between API calls within each ticker
4. **Inter-batch delay** — 2-second pause between batches (configurable)
5. **Two-pass refetch** — recalculates ratios from existing financial statements first (free), then re-fetches remaining gaps sequentially

If you still encounter issues:
- Reduce batch size: `--batch_size 25`
- Wait 15-30 minutes before retrying

### Empty Data for Some Companies

- This is expected — some smaller international companies have limited data on Yahoo Finance
- The pipeline handles this gracefully (logs a warning, continues with other companies)
- Check the `ingestion_log` table for details: `SELECT * FROM systematic_equity.ingestion_log WHERE status = 'EMPTY';`

---

## 22. References

### Academic Papers

- Baker, M. & Wurgler, J. (2006). "Investor Sentiment and the Cross-Section of Stock Returns." *Journal of Finance*, 61(4), 1645-1680.
- Fama, E.F. & French, K.R. (1993). "Common Risk Factors in the Returns on Stocks and Bonds." *Journal of Financial Economics*, 33(1), 3-56.
- Greenblatt, J. (2006). *The Little Book That Beats the Market*. Wiley.
- Hutto, C.J. & Gilbert, E. (2014). "VADER: A Parsimonious Rule-based Model for Sentiment Analysis of Social Media Text." *Proceedings of the AAAI International Conference on Web and Social Media (ICWSM)*.
- Jegadeesh, N. & Titman, S. (1993). "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency." *Journal of Finance*, 48(1), 65-91.
- Leetaru, K. & Schrodt, P. (2013). "GDELT: Global Data on Events, Location and Tone, 1979-2012." *ISA Annual Convention*.
- Tetlock, P.C. (2007). "Giving Content to Investor Sentiment: The Role of Media in the Stock Market." *Journal of Finance*, 62(3), 1139-1168.

### Technical Documentation

- [yfinance Documentation](https://github.com/ranaroussi/yfinance)
- [GDELT API v2 Documentation](https://blog.gdeltproject.org/gdelt-doc-2-0-api-discovering-the-language-of-the-world-wide-web/)
- [VADER Sentiment Analysis](https://github.com/cjhutto/vaderSentiment)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [MongoDB Documentation](https://www.mongodb.com/docs/)
- [MinIO Documentation](https://min.io/docs/minio/linux/index.html)
- [Apache Kafka Documentation](https://kafka.apache.org/documentation/)
- [Poetry Documentation](https://python-poetry.org/docs/)
- [pytest Documentation](https://docs.pytest.org/)
- [Sphinx Documentation](https://www.sphinx-doc.org/)

---

## 23. Verifying Pipeline Results (Step-by-Step)

After the pipeline has finished running, use these commands to verify that all data was correctly extracted, processed, and stored.

### 23.1 Check PostgreSQL Tables

**Connect to PostgreSQL via Docker:**

```bash
docker exec -it postgres_db_cw psql -U postgres -d fift
```

This opens an interactive SQL terminal. Type these queries one at a time and press Enter:

**Check how many price records were loaded:**

```sql
SELECT COUNT(*) AS total_price_rows FROM systematic_equity.daily_prices;
```

**Expected output** (number will vary based on run):
```
 total_price_rows
------------------
          245000
```

**Check prices for a specific company (e.g., Apple):**

```sql
SELECT symbol, cob_date, close_price, volume
FROM systematic_equity.daily_prices
WHERE symbol = 'AAPL'
ORDER BY cob_date DESC
LIMIT 10;
```

**Check value metrics (financial ratios and scores):**

```sql
SELECT company_id, pe_ratio, pb_ratio, ev_ebitda, dividend_yield, debt_equity, value_score
FROM systematic_equity.value_metrics
ORDER BY value_score DESC
LIMIT 20;
```

**Check sentiment scores:**

```sql
SELECT company_id, avg_sentiment, positive_count, negative_count, total_articles, sentiment_score
FROM systematic_equity.sentiment_scores
ORDER BY sentiment_score DESC
LIMIT 20;
```

**Check composite rankings and investment decisions:**

```sql
SELECT company_id, value_score, sentiment_score, composite_score, rank, invest_decision
FROM systematic_equity.composite_rankings
ORDER BY rank ASC
LIMIT 30;
```

**See which companies are flagged for investment (invest_decision = TRUE):**

```sql
SELECT company_id, composite_score, rank
FROM systematic_equity.composite_rankings
WHERE invest_decision = TRUE
ORDER BY rank ASC;
```

**Check how many companies passed all filters:**

```sql
SELECT
  COUNT(*) AS total_ranked,
  SUM(CASE WHEN invest_decision = TRUE THEN 1 ELSE 0 END) AS invest_true,
  SUM(CASE WHEN invest_decision = FALSE THEN 1 ELSE 0 END) AS invest_false
FROM systematic_equity.composite_rankings;
```

**Check FX rates:**

```sql
SELECT currency_pair, COUNT(*) AS days, MIN(cob_date) AS earliest, MAX(cob_date) AS latest
FROM systematic_equity.fx_rates
GROUP BY currency_pair
ORDER BY currency_pair;
```

**Check the pipeline audit trail (ingestion log):**

```sql
SELECT run_id, data_source, status, COUNT(*) AS entries, SUM(rows_affected) AS total_rows
FROM systematic_equity.ingestion_log
GROUP BY run_id, data_source, status
ORDER BY run_id DESC;
```

**Exit PostgreSQL terminal:**

```sql
\q
```

### 23.2 Check MongoDB Documents

**Connect to MongoDB via Docker:**

```bash
docker exec -it mongo_db_cw mongosh --username ift_bigdata --password mongo_password --authenticationDatabase admin ift_cw1_sentiment
```

**Check how many news articles were stored:**

```javascript
db.raw_news_articles.countDocuments()
```

**View a sample news article:**

```javascript
db.raw_news_articles.findOne()
```

**Check articles for a specific company:**

```javascript
db.raw_news_articles.find({company_id: "AAPL"}).limit(5).pretty()
```

**Check raw financial data:**

```javascript
db.raw_financial_data.countDocuments()
db.raw_financial_data.findOne({company_id: "AAPL"})
```

**Exit MongoDB terminal:**

```javascript
exit
```

### 23.3 Check MinIO Data Lake

**List all files in the MinIO bucket:**

```bash
docker exec miniocw mc ls local/iftbigdata/ --recursive | head -30
```

**Check specific data folders:**

```bash
# Check price files
docker exec miniocw mc ls local/iftbigdata/raw-data/prices/ | head -10

# Check financial data files
docker exec miniocw mc ls local/iftbigdata/raw-data/financial/ | head -10

# Check company info files
docker exec miniocw mc ls local/iftbigdata/raw-data/company_info/ | head -10

# Check FX rate files
docker exec miniocw mc ls local/iftbigdata/raw-data/fx/ | head -10
```

### 23.4 Check All 8 PostgreSQL Tables Have Data

Run this single query to see row counts for every table:

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT 'company_static' AS table_name, COUNT(*) AS rows FROM systematic_equity.company_static
UNION ALL SELECT 'daily_prices', COUNT(*) FROM systematic_equity.daily_prices
UNION ALL SELECT 'value_metrics', COUNT(*) FROM systematic_equity.value_metrics
UNION ALL SELECT 'sentiment_scores', COUNT(*) FROM systematic_equity.sentiment_scores
UNION ALL SELECT 'composite_rankings', COUNT(*) FROM systematic_equity.composite_rankings
UNION ALL SELECT 'fx_rates', COUNT(*) FROM systematic_equity.fx_rates
UNION ALL SELECT 'ingestion_log', COUNT(*) FROM systematic_equity.ingestion_log
UNION ALL SELECT 'pipeline_metadata', COUNT(*) FROM systematic_equity.pipeline_metadata
ORDER BY table_name;
"
```

**Expected output** (numbers will vary):
```
     table_name      |  rows
---------------------+--------
 company_static      |    678
 composite_rankings  |    500+
 daily_prices        | 200000+
 fx_rates            |   5000+
 ingestion_log       |   1000+
 pipeline_metadata   |    100+
 sentiment_scores    |    400+
 value_metrics       |    500+
```

---

## 24. Accessing Web Interfaces

### 24.1 MinIO Web Console

MinIO provides a web-based file browser where you can visually inspect all raw data files.

1. Open your web browser
2. Navigate to: **http://localhost:9001**
3. Log in with:
   - **Username:** `minioadmin`
   - **Password:** `minioadmin`
4. Click on the **`iftbigdata`** bucket to browse the data lake
5. Navigate through `raw-data/prices/`, `raw-data/financial/`, etc. to view uploaded files

### 24.2 PostgreSQL (via pgAdmin or DBeaver)

You can connect to PostgreSQL using any SQL client:

| Setting | Value |
|---|---|
| Host | `localhost` |
| Port | `5439` |
| Database | `fift` |
| Username | `postgres` |
| Password | `postgres` |
| Schema | `systematic_equity` |

### 24.3 MongoDB (via MongoDB Compass)

You can connect to MongoDB using MongoDB Compass:

| Setting | Value |
|---|---|
| Connection string | `mongodb://ift_bigdata:mongo_password@localhost:27019/ift_cw1_sentiment?authSource=admin` |

---

## 25. Shutting Down and Cleaning Up

### Stop All Services

```bash
# Stop all Docker containers (preserves data)
docker compose down

# Verify all containers are stopped
docker compose ps
```

**Expected output:**
```
No containers found for project "coursework_one"
```

### Restart Services Later

```bash
# Start services again (all data is preserved in Docker volumes)
docker compose up -d
```

### Complete Reset (Delete All Data)

**Warning:** This deletes ALL data from all databases. Only do this if you want a completely fresh start.

```bash
# Stop containers AND remove all data volumes
docker compose down -v

# Restart with fresh databases (re-seeds 678 companies, recreates schema)
docker compose up -d
```

### Remove Everything (Full Cleanup)

```bash
# Stop containers, remove volumes, remove images
docker compose down -v --rmi all

# Remove any orphaned containers
docker system prune -f
```

---

## 26. Complete End-to-End Walkthrough (From Zero to Results)

This section provides a complete, step-by-step walkthrough for running the entire pipeline from a freshly cloned repository to viewing investment recommendations. Follow each step exactly.

### Phase 1: Setup (One-Time)

```bash
# 1. Navigate to the project
cd team_09/coursework_one

# 2. IMPORTANT: Ensure Docker is in your PATH (macOS users)
#    If "docker" gives "command not found", run this line first:
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

# 3. Start Docker infrastructure (databases + message broker)
docker compose up -d

# 4. Wait 20 seconds for services to initialise
sleep 20

# 5. Verify all services are healthy
docker compose ps

# 6. Verify 678 companies were seeded
docker exec postgres_db_cw psql -U postgres -d fift -c \
  "SELECT COUNT(*) FROM systematic_equity.company_static;"

# 7. Install Python dependencies
poetry install

# 8. Copy environment file
cp .env.example .env.dev

# 9. Run tests to verify everything works
poetry run pytest ./test/ -v --cov=modules
```

**After these 9 steps, you should have:**
- All Docker services running (check with `docker compose ps`)
- 678 companies in the database
- All 583 tests passing with 84% overall coverage (core modules 94-100%)
- Python dependencies installed

### Phase 2: Quick Test Run (3 Companies)

Before running the full 678-company pipeline, test with a small set:

```bash
# Run for just 3 companies to verify the pipeline works end-to-end
poetry run python Main.py --env_type dev --frequency weekly --tickers AAPL MSFT GOOGL
```

**This should take about 1-2 minutes.** You will see:
- Configuration dump
- Price extraction for AAPL, MSFT, GOOGL
- FX rate extraction
- News article extraction from GDELT and Yahoo Finance
- Value Score computation and Top 10 table
- Sentiment Score computation and Top 10 table
- Composite Ranking with investment decisions

**Verify the test data was stored:**

```bash
# Check prices were loaded
docker exec postgres_db_cw psql -U postgres -d fift -c \
  "SELECT symbol, COUNT(*) AS price_rows FROM systematic_equity.daily_prices GROUP BY symbol;"

# Check value scores
docker exec postgres_db_cw psql -U postgres -d fift -c \
  "SELECT * FROM systematic_equity.value_metrics;"

# Check composite rankings
docker exec postgres_db_cw psql -U postgres -d fift -c \
  "SELECT * FROM systematic_equity.composite_rankings;"
```

### Phase 3: Full Pipeline Run (All 678 Companies)

Once the test run succeeds, run the full pipeline:

```bash
# Default: 5-year lookback, weekly frequency, all 678 companies
poetry run python Main.py --env_type dev --frequency weekly

# OR: Full 5-year quarterly refresh (recommended for first complete run)
poetry run python Main.py --env_type dev --frequency quarterly

# OR: 10-year deep historical analysis
poetry run python Main.py --env_type dev --frequency quarterly --lookback_years 10
```

**The full run processes all 678 companies and takes approximately 30-60 minutes.** The terminal will display detailed progress for every company, every batch, and every pipeline stage.

### Phase 4: View Final Results

After the pipeline completes, view the investment recommendations:

```bash
# See the top 30 investment candidates
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT
  cr.company_id,
  cs.security AS company_name,
  cs.gics_sector AS sector,
  cs.country,
  cr.value_score,
  cr.sentiment_score,
  cr.composite_score,
  cr.rank,
  cr.invest_decision
FROM systematic_equity.composite_rankings cr
JOIN systematic_equity.company_static cs ON cr.company_id = cs.symbol
ORDER BY cr.rank ASC
LIMIT 30;
"
```

```bash
# See all companies flagged for investment
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT
  cr.company_id,
  cs.security AS company_name,
  cs.gics_sector AS sector,
  cr.composite_score,
  cr.rank
FROM systematic_equity.composite_rankings cr
JOIN systematic_equity.company_static cs ON cr.company_id = cs.symbol
WHERE cr.invest_decision = TRUE
ORDER BY cr.rank ASC;
"
```

```bash
# View pipeline summary statistics
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT
  'Total companies' AS metric, COUNT(*)::TEXT AS value FROM systematic_equity.company_static
UNION ALL
SELECT 'Price records', COUNT(*)::TEXT FROM systematic_equity.daily_prices
UNION ALL
SELECT 'Value scores', COUNT(*)::TEXT FROM systematic_equity.value_metrics
UNION ALL
SELECT 'Sentiment scores', COUNT(*)::TEXT FROM systematic_equity.sentiment_scores
UNION ALL
SELECT 'Composite rankings', COUNT(*)::TEXT FROM systematic_equity.composite_rankings
UNION ALL
SELECT 'FX rate records', COUNT(*)::TEXT FROM systematic_equity.fx_rates
UNION ALL
SELECT 'Invest=TRUE companies', COUNT(*)::TEXT FROM systematic_equity.composite_rankings WHERE invest_decision = TRUE;
"
```

### Phase 5: Run Code Quality Checks

```bash
# Linting (should show 0 errors)
poetry run flake8 modules/ Main.py --max-line-length=120

# Formatting check (should show "All done!")
poetry run black modules/ Main.py test/ --line-length 120 --check

# Import sorting check
poetry run isort modules/ Main.py test/ --profile black --check-only

# Security scanning
poetry run bandit -r modules/ -c pyproject.toml

# Full test suite with coverage
poetry run pytest ./test/ -v --cov=modules --cov-report=term-missing
```

### Phase 6: Generate Documentation

```bash
# Generate Sphinx HTML documentation
cd docs/
sphinx-build -b html . _build/html
cd ..

# The documentation is now at docs/_build/html/index.html
# Open it in a browser to view the full API reference
```

### Phase 7: Shut Down When Done

```bash
# Stop all services (data is preserved)
docker compose down

# Or if you want a fresh start next time:
# docker compose down -v
```
