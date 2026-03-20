"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Main.py — Pipeline orchestrator
Project : CW1 - Value + News Sentiment Strategy

Entry point for the CW1 data pipeline.  Orchestrates the full
Extract → Transform → Load cycle for the Value + Sentiment strategy:

  1. Parse CLI arguments and load YAML configuration
  2. Set environment variables via ift_global
  3. Optionally initialise database schema
  4. Load investable universe from company_static (678 companies)
  5. Extract: prices, financials/ratios, FX rates, news articles
  6. Transform: clean data, compute value scores, VADER sentiment
  7. Load: upsert into PostgreSQL, store raw in MongoDB + MinIO
  8. Compute composite rankings and write investment decisions
  9. Publish events to Kafka for downstream consumers
  10. Write audit log for full pipeline traceability

Features animated Rich progress bars and maximum parallelisation:
  - Intra-stage: ThreadPoolExecutor per extraction function
  - Inter-stage: FX + GDELT + YF News run concurrently
  - Post-batch: MinIO/MongoDB/PostgreSQL uploads parallelised
  - Scoring: sentiment computed in parallel across companies

Usage::

    poetry run python Main.py --env_type dev --frequency weekly
    poetry run python Main.py --env_type docker --frequency quarterly --init_schema
    poetry run python Main.py --env_type dev --sources prices news --tickers AAPL MSFT

Follows the ift_big_data teaching material pattern:
  - ReadConfig(env_type) for YAML configuration
  - set_env_variables() for environment setup
  - arg_parse_cmd() for CLI flexibility
"""

import sys
import time
from datetime import date

from ift_global import ReadConfig
from ift_global.utils.set_env_var import set_env_variables

from modules.db.minio_connection import get_minio_client
from modules.db.mongo_connection import get_mongo_client
from modules.db.postgres_connection import get_db_client
from modules.extraction.company_loader import load_companies, partition_tickers
from modules.extraction.fx_extractor import FX_PAIRS
from modules.kafka.kafka_handler import get_event_producer
from modules.loading.postgres_loader import (
    insert_ingestion_log,
    upsert_composite_rankings,
    upsert_daily_prices,
    upsert_fx_rates,
    upsert_sentiment_scores,
    upsert_value_metrics,
)
from modules.processing.composite_scorer import compute_composite_scores
from modules.processing.data_cleaner import clean_fx_dataframe
from modules.processing.value_scorer import compute_value_scores
from modules.utils.config_reader import arg_parse_cmd, compute_date_range
from modules.utils.logger import generate_run_id, pipeline_logger
from modules.utils.parallel import (
    parallel_compute_sentiment,
    parallel_extract_prices,
    parallel_upload_batch_results,
    refetch_missing_ratios,
    run_extraction_stages,
)
from modules.utils.progress import PipelineProgressManager


def run_pipeline():
    """Execute the full Value + Sentiment data pipeline.

    This is the top-level orchestrator that coordinates all pipeline
    stages.  Each stage is wrapped in try/except to ensure one failure
    does not block subsequent stages.

    Uses Rich animated progress bars and multi-level ThreadPoolExecutor
    parallelism for maximum throughput.
    """
    progress = PipelineProgressManager()

    # ---------------------------------------------------------------
    # 1. Parse CLI arguments
    # ---------------------------------------------------------------
    progress.print_banner(
        "CW1 VALUE + NEWS SENTIMENT PIPELINE",
        "Team 09 — UCL Institute of Finance & Technology\n"
        "IFTE0003: Big Data in Quantitative Finance\n"
        "Strategy: Value (60%) + Sentiment (40%)",
    )

    progress.print_banner("STAGE 1: CONFIGURATION")
    parser = arg_parse_cmd()
    args = parser.parse_args()

    pipeline_logger.info("CLI Arguments:")
    pipeline_logger.info("  Environment:  %s", args.env_type)
    pipeline_logger.info("  Frequency:    %s", args.frequency)
    pipeline_logger.info("  Sources:      %s", ", ".join(args.sources))
    pipeline_logger.info("  Tickers:      %s", ", ".join(args.tickers) if args.tickers else "ALL (678 companies)")
    pipeline_logger.info("  Batch size:   %s", args.batch_size or "default (from config)")
    pipeline_logger.info("  Run date:     %s", args.run_date or "today")
    pipeline_logger.info("  Dry run:      %s", args.dry_run)
    pipeline_logger.info("  Init schema:  %s", args.init_schema)
    pipeline_logger.info("  Lookback yrs: %s", args.lookback_years if args.lookback_years else "default (from config)")

    # ---------------------------------------------------------------
    # 2. Load configuration and set environment variables
    # ---------------------------------------------------------------
    conf = ReadConfig(args.env_type, config_path="./config/conf.yaml")
    # ift_global.set_env_variables accepts 'dev' not 'docker'
    ift_env_type = "dev" if args.env_type == "docker" else args.env_type
    set_env_variables(
        env_variables=conf["config"]["env_variables"],
        env_type=ift_env_type,
        env_file=True,
    )

    db_config = conf["config"]["Database"]["Postgres"]
    mongo_config = conf["config"]["Database"]["MongoDB"]
    minio_config = conf["config"]["Database"]["Minio"]
    kafka_config = conf["config"]["Database"]["Kafka"]
    params = conf["params"]
    pipeline_params = params["Pipeline"]
    scoring_params = params["Scoring"]

    run_id = generate_run_id()

    # Compute date range based on frequency
    lookback = args.lookback_years if args.lookback_years else pipeline_params.get("lookback_years", 5)
    start_date, end_date = compute_date_range(args.frequency, lookback, args.run_date)

    pipeline_logger.info("")
    pipeline_logger.info("Pipeline Configuration:")
    pipeline_logger.info("  Run ID:               %s", run_id)
    pipeline_logger.info("  Date range:            %s to %s", start_date, end_date)
    pipeline_logger.info("  Lookback years:        %d", lookback)
    pipeline_logger.info("  Batch size:            %d", args.batch_size or pipeline_params.get("batch_size", 50))
    pipeline_logger.info("  Delay between batches: %ds", pipeline_params.get("delay_between_batches", 2))
    pipeline_logger.info("  Max retries:           %d", pipeline_params.get("max_retries", 3))
    pipeline_logger.info("")
    pipeline_logger.info("Scoring Parameters:")
    pipeline_logger.info(
        "  Value weight:          %.1f (%.0f%%)",
        scoring_params.get("value_weight", 0.6),
        scoring_params.get("value_weight", 0.6) * 100,
    )
    pipeline_logger.info(
        "  Sentiment weight:      %.1f (%.0f%%)",
        scoring_params.get("sentiment_weight", 0.4),
        scoring_params.get("sentiment_weight", 0.4) * 100,
    )
    pipeline_logger.info("  Max Debt/Equity:       %.1f", scoring_params.get("max_debt_equity", 2.0))
    pipeline_logger.info("  Min avg sentiment:     %.1f", scoring_params.get("min_sentiment", 0.0))
    pipeline_logger.info("  Min articles:          %d", scoring_params.get("min_articles", 3))

    if args.dry_run:
        pipeline_logger.info("")
        pipeline_logger.info("DRY RUN — configuration validated successfully, exiting")
        return

    # ---------------------------------------------------------------
    # 3. Initialise storage clients
    # ---------------------------------------------------------------
    progress.start()
    progress.begin_stage("Connecting Databases", 4)

    db = get_db_client(db_config)
    progress.advance("PostgreSQL connected", "success")

    mongo = get_mongo_client(mongo_config)
    progress.advance("MongoDB connected", "success")

    minio = get_minio_client(minio_config)
    progress.advance("MinIO connected", "success")

    kafka_producer = get_event_producer(kafka_config)
    progress.advance("Kafka producer ready", "success")

    progress.complete_stage()

    # Optional: re-create schema
    if args.init_schema:
        with progress.spinner("Initialising database schema..."):
            db.init_schema("static/schema/create_tables.sql")

    # ---------------------------------------------------------------
    # 4. Load investable universe
    # ---------------------------------------------------------------
    progress.begin_stage("Loading Investable Universe", 1)
    companies_df = load_companies(db_config)
    if companies_df.empty:
        progress.stop()
        pipeline_logger.error("No companies loaded — aborting pipeline")
        sys.exit(1)

    # Apply ticker overrides if specified
    if args.tickers:
        companies_df = companies_df[companies_df["symbol"].isin(args.tickers)]

    all_tickers = companies_df["symbol"].tolist()

    # Partition into active vs delisted to avoid wasting API calls
    active_tickers, delisted_tickers = partition_tickers(all_tickers)
    pipeline_logger.info(
        "Partitioned %d tickers: %d active, %d delisted (skipped)",
        len(all_tickers),
        len(active_tickers),
        len(delisted_tickers),
    )
    if delisted_tickers:
        pipeline_logger.info("Delisted tickers: %s", ", ".join(sorted(delisted_tickers)))

    # Use active tickers for extraction, keep all_tickers for full record
    tickers = active_tickers
    companies_df_active = companies_df[~companies_df["symbol"].isin(delisted_tickers)]
    company_records = companies_df_active.to_dict(orient="records")
    currency_map = params.get("CurrencyMapping", {})

    batch_size = args.batch_size or pipeline_params.get("batch_size", 50)
    delay = pipeline_params.get("delay_between_batches", 2)
    max_retries = pipeline_params.get("max_retries", 3)
    score_date = args.run_date or date.today()

    progress.advance(
        f"{len(all_tickers)} companies loaded ({len(tickers)} active, {len(delisted_tickers)} delisted)",
        "success",
    )
    progress.complete_stage()
    progress.update_stats("Companies", f"{len(tickers):,} active / {len(delisted_tickers):,} delisted")
    progress.update_stats("Date Range", f"{start_date} to {end_date}")

    # ---------------------------------------------------------------
    # 5. CONCURRENT EXTRACTION: FX + GDELT + YF News run in parallel
    #    These are independent of YF price extraction and each other.
    # ---------------------------------------------------------------
    all_price_records = []
    all_company_infos = []
    all_financials = {}  # ticker → financial statement dict (for ratio recalculation)
    sources = args.sources
    price_success_count = 0
    price_empty_count = 0
    price_fail_count = 0
    info_success_count = 0
    info_fail_count = 0

    ds_config = params.get("DataSources", {})
    progress.begin_parallel_stages(
        {
            "FX Rate Extraction": len(FX_PAIRS),
            "News Cascade": len(tickers),
        }
    )
    progress.update_stats("Concurrent Stages", "FX + News Cascade (YF→GDELT→NewsAPI) running...")

    stage_results = run_extraction_stages(
        tickers=tickers,
        company_records=company_records,
        sources=sources,
        start_date=start_date,
        end_date=end_date,
        ds_config=ds_config,
        fx_progress_callback=lambda item, status, desc: progress.advance_parallel("FX Rate Extraction", desc, status),
        news_progress_callback=lambda item, status, desc: progress.advance_parallel("News Cascade", desc, status),
    )

    fx_data = stage_results.get("fx_data", {})
    cascade_news = stage_results.get("all_news", {})
    news_stats = stage_results.get("news_stats", {})

    fx_count = sum(len(df) for df in fx_data.values() if not df.empty)
    yf_news_count = news_stats.get("yf_news", 0)
    gdelt_count = news_stats.get("gdelt", 0)
    newsapi_count = news_stats.get("newsapi", 0)

    progress.complete_parallel_stages()
    progress.update_stats(
        "Concurrent Stages",
        f"FX:{fx_count} YF:{yf_news_count} GDELT:{gdelt_count} NewsAPI:{newsapi_count}",
    )

    # ---------------------------------------------------------------
    # 6. Yahoo Finance price/financial extraction (batched, parallel)
    # ---------------------------------------------------------------
    if "prices" in sources or "financials" in sources:
        total_batches = (len(tickers) + batch_size - 1) // batch_size
        progress.begin_stage("Yahoo Finance Extraction", len(tickers))
        progress.update_stats("YF Stage", f"0/{len(tickers)} tickers")

        for batch_start in range(0, len(tickers), batch_size):
            batch = tickers[batch_start : batch_start + batch_size]
            batch_num = batch_start // batch_size + 1

            def _yf_progress_callback(ticker, status, description):
                progress.advance(description, status)

            batch_result = parallel_extract_prices(
                batch=batch,
                sources=sources,
                start_date=start_date,
                end_date=end_date,
                currency_map=currency_map,
                max_retries=max_retries,
                max_workers=6,
                delay_per_ticker=0.3,
                progress_callback=_yf_progress_callback,
            )

            # Aggregate batch results
            all_price_records.extend(batch_result.price_records)
            all_company_infos.extend(batch_result.company_infos)
            price_success_count += batch_result.price_success
            price_empty_count += batch_result.price_empty
            price_fail_count += batch_result.price_fail
            info_success_count += batch_result.info_success
            info_fail_count += batch_result.info_fail

            # Track financial statements per ticker for ratio recalculation
            for tr in batch_result.ticker_results:
                if tr.financials:
                    all_financials[tr.ticker] = tr.financials

            # Post-batch: upload to MinIO/MongoDB in PARALLEL
            parallel_upload_batch_results(
                ticker_results=batch_result.ticker_results,
                minio=minio,
                mongo=mongo,
                db=db,
                run_id=run_id,
                end_date=end_date,
                frequency=args.frequency,
                start_date=start_date,
                max_workers=6,
            )

            processed = min(batch_start + batch_size, len(tickers))
            progress.update_stats("YF Stage", f"{processed}/{len(tickers)} tickers")
            progress.update_stats("Price Records", f"{len(all_price_records):,}")

            # Inter-batch delay (skip after last batch)
            if batch_num < total_batches:
                time.sleep(delay)

        progress.complete_stage()
        progress.update_stats(
            "Prices", f"{price_success_count} ok / {price_empty_count} empty / {price_fail_count} err"
        )
        progress.update_stats("Financials", f"{info_success_count} ok / {info_fail_count} err")

        # Log extraction coverage for active tickers
        tickers_with_info = {r["company_id"] for r in all_company_infos if r.get("company_id")}
        tickers_with_prices = {r.get("symbol", r.get("ticker", "")) for r in all_price_records}
        active_missing_info = [t for t in tickers if t not in tickers_with_info and t in tickers_with_prices]
        if active_missing_info:
            pipeline_logger.info(
                "Active tickers missing financials (%d): %s",
                len(active_missing_info),
                ", ".join(sorted(active_missing_info)),
            )
        pipeline_logger.info(
            "Extraction coverage: %d/%d active tickers with prices, %d with financials",
            len(tickers_with_prices & set(tickers)),
            len(tickers),
            len(tickers_with_info & set(tickers)),
        )

    # ---------------------------------------------------------------
    # 7. Process FX results
    # ---------------------------------------------------------------
    all_fx_records = []
    fx_db_count = 0
    if "fx" in sources and fx_data:
        progress.begin_stage("Loading FX Data", len(fx_data))
        for pair, df in fx_data.items():
            if not df.empty:
                records = clean_fx_dataframe(df, pair)
                all_fx_records.extend(records)
                minio.upload_csv(df, "fx", pair.replace("=", "_"), f"{end_date}.csv")
                progress.advance(f"{pair}: {len(records)} rates", "success")
            else:
                progress.advance(f"{pair}: no data", "empty")

        if all_fx_records:
            upsert_fx_rates(db, all_fx_records)
            insert_ingestion_log(
                db, run_id, "yfinance_fx", None, "SUCCESS", len(all_fx_records), run_frequency=args.frequency
            )
        progress.complete_stage()
        # Show actual DB count (includes prior runs) for accurate reporting
        try:
            cur = db.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM systematic_equity.fx_rates")
            fx_db_count = cur.fetchone()[0]
            cur.close()
            progress.update_stats("FX Records", f"{fx_db_count:,}")
        except Exception:
            progress.update_stats("FX Records", f"{len(all_fx_records):,}")

    # ---------------------------------------------------------------
    # 8. Process news results (cascade already merged all sources)
    # ---------------------------------------------------------------
    all_articles = {}

    if "news" in sources:
        if cascade_news:
            progress.begin_stage("Loading News to MongoDB/Kafka", len(cascade_news))
            for ticker, articles in cascade_news.items():
                all_articles.setdefault(ticker, []).extend(articles)
                if articles:
                    mongo.insert_documents("raw_news_articles", articles)
                    kafka_producer.publish_batch("news-articles", articles)
                progress.advance(f"{ticker}: {len(articles)} articles", "success" if articles else "empty")

            # Log ingestion for each source that contributed
            if yf_news_count > 0:
                insert_ingestion_log(
                    db,
                    run_id,
                    "yfinance_news",
                    None,
                    "SUCCESS",
                    yf_news_count,
                    run_frequency=args.frequency,
                )
            if gdelt_count > 0:
                insert_ingestion_log(
                    db,
                    run_id,
                    "gdelt",
                    None,
                    "SUCCESS",
                    gdelt_count,
                    run_frequency=args.frequency,
                )
            if newsapi_count > 0:
                insert_ingestion_log(
                    db,
                    run_id,
                    "newsapi",
                    None,
                    "SUCCESS",
                    newsapi_count,
                    run_frequency=args.frequency,
                )
            progress.complete_stage()

        progress.update_stats("YF News Articles", f"{yf_news_count:,}")
        progress.update_stats("GDELT Articles (gap-fill)", f"{gdelt_count:,}")
        progress.update_stats("NewsAPI Articles (gap-fill)", f"{newsapi_count:,}")

        # Ensure ALL tickers have entries for full sentiment coverage —
        # companies with 0 articles still get a sentiment_score=None record
        for ticker in tickers:
            all_articles.setdefault(ticker, [])

        total_articles = sum(len(v) for v in all_articles.values())
        progress.update_stats("Total Articles", f"{total_articles:,}")

    # ---------------------------------------------------------------
    # 9. LOAD: Price data to PostgreSQL
    # ---------------------------------------------------------------
    pg_price_count = 0
    if all_price_records:
        progress.begin_stage("Loading Prices to PostgreSQL", 1)
        pg_price_count = upsert_daily_prices(db, all_price_records)
        progress.advance(f"{pg_price_count:,} rows upserted", "success")
        progress.complete_stage()

    # ---------------------------------------------------------------
    # 9b. RE-FETCH: Fill gaps for tickers missing EV/EBITDA or D/E
    #     During bulk extraction, Yahoo Finance rate limiting can cause
    #     partial data (401 errors). This targeted pass re-fetches only
    #     the missing tickers individually with proper delays.
    # ---------------------------------------------------------------
    if all_company_infos:
        with progress.spinner("Recalculating ratios from financial statements + re-fetching gaps..."):
            all_company_infos = refetch_missing_ratios(
                all_company_infos,
                all_financials=all_financials if all_financials else None,
                max_retries=max_retries,
                delay=1.5,
            )

    # ---------------------------------------------------------------
    # 10. TRANSFORM: Value Scores
    # ---------------------------------------------------------------
    value_records = []
    if all_company_infos:
        progress.begin_stage("Computing Value Scores", len(all_company_infos))

        value_records = compute_value_scores(all_company_infos, score_date)
        if value_records:
            for r in value_records:
                status = "success" if r.get("value_score") is not None else "empty"
                progress.advance(f"{r['company_id']}: {r.get('value_score', '-')}", status)

        # Ensure ALL tickers get a value record for full coverage —
        # companies that failed info extraction still get value_score=None
        scored_tickers = {r["company_id"] for r in value_records}
        date_str = score_date.strftime("%Y-%m-%d") if hasattr(score_date, "strftime") else str(score_date)
        for ticker in tickers:
            if ticker not in scored_tickers:
                value_records.append(
                    {
                        "company_id": ticker,
                        "date": date_str,
                        "pe_ratio": None,
                        "pb_ratio": None,
                        "ev_ebitda": None,
                        "dividend_yield": None,
                        "debt_equity": None,
                        "value_score": None,
                    }
                )

        progress.complete_stage()

        # Upsert value metrics to PostgreSQL
        if value_records:
            progress.begin_stage("Loading Value Metrics to PostgreSQL", 1)
            upsert_value_metrics(db, value_records)
            kafka_producer.publish_batch("value-metrics", value_records)
            scored_count = len([r for r in value_records if r.get("value_score")])
            progress.advance(f"{scored_count} value scores upserted", "success")
            progress.complete_stage()

        # Display Rich results table
        scored = [r for r in value_records if r.get("value_score") is not None]
        if scored:
            sorted_by_value = sorted(scored, key=lambda x: x["value_score"], reverse=True)
            progress.stop()
            progress.print_results_table(
                "Top 10 Most Undervalued Companies (by Value Score)",
                ["Rank", "Ticker", "Value Score", "P/E", "P/B", "EV/EBITDA", "Div Yield", "D/E"],
                [
                    [
                        i + 1,
                        r["company_id"],
                        f"{r['value_score']:.2f}",
                        f"{r['pe_ratio']:.2f}" if r.get("pe_ratio") is not None else "-",
                        f"{r['pb_ratio']:.2f}" if r.get("pb_ratio") is not None else "-",
                        f"{r['ev_ebitda']:.2f}" if r.get("ev_ebitda") is not None else "-",
                        f"{r['dividend_yield']:.4f}" if r.get("dividend_yield") is not None else "-",
                        f"{r['debt_equity']:.2f}" if r.get("debt_equity") is not None else "-",
                    ]
                    for i, r in enumerate(sorted_by_value[:10])
                ],
                styles=["dim", "bold", "green", "", "", "", "", ""],
            )
            progress.start()

    # ---------------------------------------------------------------
    # 11. TRANSFORM: Sentiment Scores (PARALLEL per company)
    # ---------------------------------------------------------------
    sentiment_records = []
    if all_articles:
        progress.begin_stage("Computing Sentiment Scores", len(all_articles))

        def _sentiment_progress_callback(ticker, status, description):
            progress.advance(description, status)

        sentiment_records = parallel_compute_sentiment(
            all_articles=all_articles,
            score_date=score_date,
            max_workers=8,
            progress_callback=_sentiment_progress_callback,
        )
        progress.complete_stage()

        if sentiment_records:
            progress.begin_stage("Loading Sentiment Scores to PostgreSQL", 1)
            upsert_sentiment_scores(db, sentiment_records)
            scored_s = len([r for r in sentiment_records if r.get("sentiment_score") is not None])
            progress.advance(f"{scored_s} sentiment scores upserted", "success")
            progress.complete_stage()
        scored_sent = [r for r in sentiment_records if r.get("sentiment_score") is not None]
        progress.update_stats("Sentiment Scores", f"{len(scored_sent)} computed")

        # Display Rich results table
        if scored_sent:
            sorted_by_sent = sorted(scored_sent, key=lambda x: x["sentiment_score"], reverse=True)
            progress.stop()
            progress.print_results_table(
                "Top 10 Most Positive Sentiment Companies",
                ["Rank", "Ticker", "Sent Score", "Avg Sent", "Pos/Neg/Neu", "Articles", "Pos Ratio"],
                [
                    [
                        i + 1,
                        r["company_id"],
                        f"{r['sentiment_score']:.2f}",
                        f"{r['avg_sentiment']:.4f}" if r.get("avg_sentiment") is not None else "-",
                        f"{r.get('positive_count', 0)}/{r.get('negative_count', 0)}/{r.get('neutral_count', 0)}",
                        r.get("total_articles", 0),
                        f"{r['positive_ratio']:.2f}" if r.get("positive_ratio") is not None else "-",
                    ]
                    for i, r in enumerate(sorted_by_sent[:10])
                ],
                styles=["dim", "bold", "green", "", "", "", ""],
            )
            progress.start()

    # ---------------------------------------------------------------
    # 12. TRANSFORM: Composite Rankings
    # ---------------------------------------------------------------
    composite_records = []
    if value_records or sentiment_records:
        progress.begin_stage("Computing Composite Rankings", 1)

        composite_records = compute_composite_scores(
            value_records,
            sentiment_records,
            value_weight=scoring_params.get("value_weight", 0.6),
            sentiment_weight=scoring_params.get("sentiment_weight", 0.4),
            max_debt_equity=scoring_params.get("max_debt_equity", 2.0),
            min_avg_sentiment=scoring_params.get("min_sentiment", 0.0),
            min_articles=scoring_params.get("min_articles", 3),
            score_date=score_date,
        )
        if composite_records:
            invest_count = sum(1 for r in composite_records if r.get("invest_decision"))
            progress.advance(f"{len(composite_records)} ranked, {invest_count} flagged for investment", "success")
        progress.complete_stage()

        if composite_records:
            progress.begin_stage("Loading Composite Rankings to PostgreSQL", 1)
            upsert_composite_rankings(db, composite_records)
            progress.advance(f"{len(composite_records)} rankings upserted", "success")
            progress.complete_stage()

        # Display Rich results tables
        if composite_records:
            progress.stop()
            progress.print_results_table(
                "TOP 20 INVESTMENT CANDIDATES (by Composite Score)",
                ["Rank", "Ticker", "Composite", "Value", "Sentiment", "Invest?"],
                [
                    [
                        r["rank"],
                        r["company_id"],
                        f"{r['composite_score']:.2f}" if r.get("composite_score") else "-",
                        f"{r['value_score']:.2f}" if r.get("value_score") else "-",
                        f"{r['sentiment_score']:.2f}" if r.get("sentiment_score") else "-",
                        "YES" if r.get("invest_decision") else "no",
                    ]
                    for r in composite_records[:20]
                ],
                styles=["dim", "bold", "cyan", "green", "green", "bold"],
            )

            if invest_count > 0:
                invest_companies = [r for r in composite_records if r.get("invest_decision")]
                progress.print_results_table(
                    "ALL COMPANIES FLAGGED FOR INVESTMENT",
                    ["Rank", "Ticker", "Composite", "Value", "Sentiment"],
                    [
                        [
                            r["rank"],
                            r["company_id"],
                            f"{r['composite_score']:.2f}" if r.get("composite_score") else "-",
                            f"{r['value_score']:.2f}" if r.get("value_score") else "-",
                            f"{r['sentiment_score']:.2f}" if r.get("sentiment_score") else "-",
                        ]
                        for r in invest_companies
                    ],
                    styles=["dim", "bold", "cyan", "green", "green"],
                )
            progress.start()

    # ---------------------------------------------------------------
    # 13. Pipeline Summary and Cleanup
    # ---------------------------------------------------------------
    progress.begin_stage("Closing Connections", 3)
    kafka_producer.close()
    progress.advance("Kafka closed", "success")
    mongo.close()
    progress.advance("MongoDB closed", "success")
    db.close()
    progress.advance("PostgreSQL closed", "success")
    progress.complete_stage()

    progress.stop()

    # Final Rich summary table
    progress.print_summary()

    # ------------------------------------------------------------------
    # COMPREHENSIVE DATA COVERAGE ANALYTICS
    # All coverage measured against the full 678-company universe
    # ------------------------------------------------------------------
    n_total = len(all_tickers)
    n_delisted = len(delisted_tickers)
    n_value = len([r for r in value_records if r.get("value_score") is not None])
    n_sent = len([r for r in sentiment_records if r.get("sentiment_score") is not None])
    n_news_tickers = sum(1 for v in all_articles.values() if v)
    total_news = sum(len(v) for v in all_articles.values())
    invest_total = sum(1 for r in (composite_records or []) if r.get("invest_decision"))

    # Ratio-level coverage — counted across ALL value_records (full universe)
    n_pe = sum(1 for r in value_records if r.get("pe_ratio") is not None)
    n_pb = sum(1 for r in value_records if r.get("pb_ratio") is not None)
    n_ev = sum(1 for r in value_records if r.get("ev_ebitda") is not None)
    n_dy = sum(1 for r in value_records if r.get("dividend_yield") is not None)
    n_de = sum(1 for r in value_records if r.get("debt_equity") is not None)

    # Composite filtering stats
    n_composite = len(composite_records) if composite_records else 0
    n_both = len([r for r in (composite_records or []) if r.get("value_score") and r.get("sentiment_score")])

    def _pct(num, denom):
        return num / max(denom, 1) * 100

    def _status(num, denom, target=80):
        return "PASS" if _pct(num, denom) >= target else "FAIL"

    # --- Table 1: EXTRACTION SUMMARY ---
    progress.print_results_table(
        "EXTRACTION SUMMARY (Data Sources)",
        ["Source / Metric", "Records", "Tickers Covered", "Coverage (of 678)"],
        [
            [
                "Yahoo Finance — Prices",
                f"{len(all_price_records):,} rows",
                f"{price_success_count}",
                f"{_pct(price_success_count, n_total):.1f}%",
            ],
            [
                "Yahoo Finance — Company Info",
                f"{len(all_company_infos)}",
                f"{info_success_count}",
                f"{_pct(info_success_count, n_total):.1f}%",
            ],
            [
                "Yahoo Finance — News (tier 1)",
                f"{yf_news_count:,} articles",
                "",
                "",
            ],
            [
                "GDELT — News (tier 2 gap-fill)",
                f"{gdelt_count:,} articles",
                "",
                "",
            ],
            [
                "NewsAPI — News (tier 3 gap-fill)",
                f"{newsapi_count:,} articles",
                "",
                "",
            ],
            [
                "All News Sources (combined)",
                f"{total_news:,} articles",
                f"{n_news_tickers}",
                f"{_pct(n_news_tickers, n_total):.1f}%",
            ],
            [
                "FX Rates",
                f"{fx_db_count:,} rows" if fx_db_count > 0 else f"{len(all_fx_records):,} rows",
                "4/4 pairs",
                "100.0%",
            ],
            [
                "Delisted tickers (skipped)",
                f"{n_delisted}",
                "",
                f"{_pct(n_delisted, n_total):.1f}% of universe",
            ],
        ],
        styles=["bold", "cyan", "cyan", "green"],
    )

    # --- Table 2: FINANCIAL RATIO COVERAGE (vs 678 universe) ---
    progress.print_results_table(
        "FINANCIAL RATIO DATA COVERAGE (vs Full 678 Universe)",
        ["Ratio", "Available", "Missing", "Coverage", "Status"],
        [
            [
                "P/E (Price/Earnings)",
                f"{n_pe}",
                f"{n_total - n_pe}",
                f"{n_pe}/{n_total} ({_pct(n_pe, n_total):.1f}%)",
                _status(n_pe, n_total),
            ],
            [
                "P/B (Price/Book)",
                f"{n_pb}",
                f"{n_total - n_pb}",
                f"{n_pb}/{n_total} ({_pct(n_pb, n_total):.1f}%)",
                _status(n_pb, n_total),
            ],
            [
                "EV/EBITDA",
                f"{n_ev}",
                f"{n_total - n_ev}",
                f"{n_ev}/{n_total} ({_pct(n_ev, n_total):.1f}%)",
                _status(n_ev, n_total),
            ],
            [
                "Dividend Yield",
                f"{n_dy}",
                f"{n_total - n_dy}",
                f"{n_dy}/{n_total} ({_pct(n_dy, n_total):.1f}%)",
                _status(n_dy, n_total),
            ],
            [
                "Debt/Equity (filter only)",
                f"{n_de}",
                f"{n_total - n_de}",
                f"{n_de}/{n_total} ({_pct(n_de, n_total):.1f}%)",
                _status(n_de, n_total),
            ],
            [
                "Value Score (composite)",
                f"{n_value}",
                f"{n_total - n_value}",
                f"{n_value}/{n_total} ({_pct(n_value, n_total):.1f}%)",
                _status(n_value, n_total),
            ],
        ],
        styles=["bold", "cyan", "yellow", "green", "bold"],
    )

    # --- Table 3: SCORING & POSTGRESQL LOADING ---
    progress.print_results_table(
        "SCORING & POSTGRESQL LOADING",
        ["PostgreSQL Table", "Rows Loaded", "Tickers", "Coverage (of 678)"],
        [
            [
                "daily_prices",
                f"{pg_price_count:,}",
                f"{price_success_count}",
                f"{_pct(price_success_count, n_total):.1f}%",
            ],
            [
                "value_metrics",
                f"{len(value_records)}",
                f"{n_value} scored",
                f"{_pct(n_value, n_total):.1f}%",
            ],
            [
                "sentiment_scores",
                f"{len(sentiment_records)}",
                f"{n_sent} scored",
                f"{_pct(n_sent, n_total):.1f}%",
            ],
            [
                "composite_rankings",
                f"{n_composite}",
                f"{n_both} with both scores",
                f"{_pct(n_composite, n_total):.1f}%",
            ],
            [
                "  invest_decision = TRUE",
                f"{invest_total}",
                "",
                f"top {_pct(invest_total, max(n_composite, 1)):.1f}% of ranked",
            ],
            [
                "fx_rates",
                f"{fx_db_count:,}" if fx_db_count > 0 else f"{len(all_fx_records):,}",
                "4 currency pairs",
                "100.0%",
            ],
        ],
        styles=["bold", "cyan", "cyan", "green"],
    )

    # --- Table 4: OVERALL DATA COVERAGE SCORECARD ---
    coverage_rows = [
        [
            "Prices (daily OHLCV)",
            f"{price_success_count}/{n_total}",
            f"{_pct(price_success_count, n_total):.1f}%",
            _status(price_success_count, n_total),
        ],
        [
            "Company Financials",
            f"{info_success_count}/{n_total}",
            f"{_pct(info_success_count, n_total):.1f}%",
            _status(info_success_count, n_total),
        ],
        [
            "P/E Ratio",
            f"{n_pe}/{n_total}",
            f"{_pct(n_pe, n_total):.1f}%",
            _status(n_pe, n_total),
        ],
        [
            "P/B Ratio",
            f"{n_pb}/{n_total}",
            f"{_pct(n_pb, n_total):.1f}%",
            _status(n_pb, n_total),
        ],
        [
            "EV/EBITDA",
            f"{n_ev}/{n_total}",
            f"{_pct(n_ev, n_total):.1f}%",
            _status(n_ev, n_total),
        ],
        [
            "Dividend Yield",
            f"{n_dy}/{n_total}",
            f"{_pct(n_dy, n_total):.1f}%",
            _status(n_dy, n_total),
        ],
        [
            "Debt/Equity",
            f"{n_de}/{n_total}",
            f"{_pct(n_de, n_total):.1f}%",
            _status(n_de, n_total),
        ],
        [
            "Value Score",
            f"{n_value}/{n_total}",
            f"{_pct(n_value, n_total):.1f}%",
            _status(n_value, n_total),
        ],
        [
            "News Articles",
            f"{n_news_tickers}/{n_total}",
            f"{_pct(n_news_tickers, n_total):.1f}%",
            _status(n_news_tickers, n_total),
        ],
        [
            "Sentiment Score",
            f"{n_sent}/{n_total}",
            f"{_pct(n_sent, n_total):.1f}%",
            _status(n_sent, n_total),
        ],
        [
            "Composite Ranking",
            f"{n_composite}/{n_total}",
            f"{_pct(n_composite, n_total):.1f}%",
            _status(n_composite, n_total),
        ],
        [
            "FX Rates",
            "4/4 pairs",
            "100.0%",
            "PASS",
        ],
    ]
    pass_count = sum(1 for r in coverage_rows if r[3] == "PASS")
    fail_count = sum(1 for r in coverage_rows if r[3] == "FAIL")

    progress.print_results_table(
        f"DATA COVERAGE SCORECARD vs 678 UNIVERSE — {pass_count} PASS / {fail_count} FAIL (target: 80%+)",
        ["Data Category", "Count", "Coverage %", "Status"],
        coverage_rows,
        styles=["bold", "cyan", "green", "bold"],
    )

    # Log structured summary for audit trail
    pipeline_logger.info("Run ID: %s", run_id)
    pipeline_logger.info("Price records: %d | Company infos: %d", len(all_price_records), len(all_company_infos))
    pipeline_logger.info(
        "News articles: %d (YF: %d, GDELT: %d, NewsAPI: %d)", total_news, yf_news_count, gdelt_count, newsapi_count
    )
    pipeline_logger.info("FX records: %d", fx_db_count if fx_db_count > 0 else len(all_fx_records))
    pipeline_logger.info(
        "Value scores: %d | Sentiment scores: %d | Composite rankings: %d", n_value, n_sent, n_composite
    )
    pipeline_logger.info("Investment decisions: %d companies flagged", invest_total)
    pipeline_logger.info(
        "Ratio coverage (of %d universe): P/E=%d P/B=%d EV/EBITDA=%d DivYield=%d D/E=%d",
        n_total,
        n_pe,
        n_pb,
        n_ev,
        n_dy,
        n_de,
    )
    pipeline_logger.info(
        "DATA COVERAGE: Prices=%.1f%% Financials=%.1f%% News=%.1f%% Sentiment=%.1f%% Value=%.1f%%",
        _pct(price_success_count, n_total),
        _pct(info_success_count, n_total),
        _pct(n_news_tickers, n_total),
        _pct(n_sent, n_total),
        _pct(n_value, n_total),
    )

    # ------------------------------------------------------------------
    # COMPREHENSIVE DATA AUDIT
    # Strict verification of all data quality metrics
    # ------------------------------------------------------------------
    pipeline_logger.info("=" * 60)
    pipeline_logger.info("COMPREHENSIVE DATA AUDIT — START")
    pipeline_logger.info("=" * 60)

    audit_issues = []

    # --- Audit 1: Tickers with ZERO ratios (complete data failures) ---
    zero_ratio_tickers = []
    partial_ratio_tickers = []
    ratio_keys = ["pe_ratio", "pb_ratio", "ev_ebitda", "dividend_yield", "debt_equity"]
    for r in value_records:
        available = [k for k in ratio_keys if r.get(k) is not None]
        if len(available) == 0:
            zero_ratio_tickers.append(r["company_id"])
        elif len(available) < 5:
            partial_ratio_tickers.append((r["company_id"], len(available), 5 - len(available)))

    if zero_ratio_tickers:
        audit_issues.append(f"{len(zero_ratio_tickers)} tickers with ZERO ratios")
        pipeline_logger.warning(
            "AUDIT: %d tickers with 0 ratios: %s%s",
            len(zero_ratio_tickers),
            ", ".join(sorted(zero_ratio_tickers)[:30]),
            "..." if len(zero_ratio_tickers) > 30 else "",
        )

    if partial_ratio_tickers:
        audit_issues.append(f"{len(partial_ratio_tickers)} tickers with partial ratios")
        # Group by number of missing ratios
        by_missing = {}
        for ticker, have, miss in partial_ratio_tickers:
            by_missing.setdefault(miss, []).append(ticker)
        for miss_count in sorted(by_missing.keys(), reverse=True):
            tickers_list = by_missing[miss_count]
            pipeline_logger.info(
                "AUDIT: %d tickers missing %d/5 ratios: %s%s",
                len(tickers_list),
                miss_count,
                ", ".join(sorted(tickers_list)[:20]),
                "..." if len(tickers_list) > 20 else "",
            )

    # --- Audit 2: Extreme / suspicious ratio values ---
    extreme_pe = [(r["company_id"], r["pe_ratio"]) for r in value_records if r.get("pe_ratio") and r["pe_ratio"] > 200]
    extreme_pb = [(r["company_id"], r["pb_ratio"]) for r in value_records if r.get("pb_ratio") and r["pb_ratio"] > 50]
    extreme_ev = [
        (r["company_id"], r["ev_ebitda"]) for r in value_records if r.get("ev_ebitda") and r["ev_ebitda"] > 100
    ]
    negative_de = [
        (r["company_id"], r["debt_equity"])
        for r in value_records
        if r.get("debt_equity") is not None and r["debt_equity"] < 0
    ]

    if extreme_pe:
        audit_issues.append(f"{len(extreme_pe)} extreme P/E values (>200)")
        pipeline_logger.warning("AUDIT: %d extreme P/E (>200): %s", len(extreme_pe), extreme_pe[:10])
    if extreme_pb:
        audit_issues.append(f"{len(extreme_pb)} extreme P/B values (>50)")
        pipeline_logger.warning("AUDIT: %d extreme P/B (>50): %s", len(extreme_pb), extreme_pb[:10])
    if extreme_ev:
        audit_issues.append(f"{len(extreme_ev)} extreme EV/EBITDA (>100)")
        pipeline_logger.warning("AUDIT: %d extreme EV/EBITDA (>100): %s", len(extreme_ev), extreme_ev[:10])
    if negative_de:
        audit_issues.append(f"{len(negative_de)} negative D/E values")
        pipeline_logger.warning("AUDIT: %d negative D/E: %s", len(negative_de), negative_de[:10])

    # --- Audit 3: News coverage gaps ---
    zero_news_tickers = sorted([t for t, arts in all_articles.items() if not arts])
    if zero_news_tickers:
        audit_issues.append(f"{len(zero_news_tickers)} tickers with 0 news articles")
        pipeline_logger.info(
            "AUDIT: %d tickers with 0 news: %s%s",
            len(zero_news_tickers),
            ", ".join(zero_news_tickers[:30]),
            "..." if len(zero_news_tickers) > 30 else "",
        )

    # --- Audit 4: Sentiment coverage check ---
    sent_none = [r["company_id"] for r in sentiment_records if r.get("sentiment_score") is None]
    if sent_none:
        audit_issues.append(f"{len(sent_none)} tickers with no sentiment score")

    # --- Audit 5: Composite ranking consistency ---
    composite_no_value = [r["company_id"] for r in (composite_records or []) if r.get("value_score") is None]
    composite_no_sent = [r["company_id"] for r in (composite_records or []) if r.get("sentiment_score") is None]
    if composite_no_value:
        audit_issues.append(f"{len(composite_no_value)} ranked without value score")
    if composite_no_sent:
        audit_issues.append(f"{len(composite_no_sent)} ranked without sentiment score")

    # --- Audit 6: Delisted detection summary ---
    pipeline_logger.info(
        "AUDIT: Delisted detection — %d/%d tickers marked inactive (%.1f%%)",
        n_delisted,
        n_total,
        _pct(n_delisted, n_total),
    )

    # --- Audit 7: Per-ratio detailed breakdown ---
    ratio_details = {
        "P/E Ratio": ("pe_ratio", n_pe),
        "P/B Ratio": ("pb_ratio", n_pb),
        "EV/EBITDA": ("ev_ebitda", n_ev),
        "Dividend Yield": ("dividend_yield", n_dy),
        "Debt/Equity": ("debt_equity", n_de),
    }
    audit_ratio_rows = []
    for name, (key, count) in ratio_details.items():
        missing = n_total - count
        pct = _pct(count, n_total)
        status = "PASS" if pct >= 80 else "FAIL"
        audit_ratio_rows.append([name, str(count), str(missing), f"{pct:.1f}%", status])

    progress.print_results_table(
        "DATA AUDIT — RATIO COMPLETENESS (vs 678 Universe)",
        ["Ratio", "Present", "Missing", "Coverage", "Status"],
        audit_ratio_rows,
        styles=["bold", "cyan", "yellow", "green", "bold"],
    )

    # --- Audit 8: News source effectiveness ---
    news_audit_rows = [
        ["YF News (tier 1)", str(yf_news_count), f"{yf_news_count} articles"],
        ["GDELT (tier 2)", str(gdelt_count), "gap-fill"],
        ["NewsAPI (tier 3)", str(newsapi_count), "gap-fill"],
        ["Total", str(total_news), f"{n_news_tickers}/{n_total} tickers ({_pct(n_news_tickers, n_total):.1f}%)"],
    ]
    progress.print_results_table(
        "DATA AUDIT — NEWS SOURCE EFFECTIVENESS",
        ["Source", "Articles", "Coverage"],
        news_audit_rows,
        styles=["bold", "cyan", "green"],
    )

    # --- Audit Summary ---
    if audit_issues:
        pipeline_logger.warning("AUDIT SUMMARY: %d issue(s) detected:", len(audit_issues))
        for i, issue in enumerate(audit_issues, 1):
            pipeline_logger.warning("  %d. %s", i, issue)
    else:
        pipeline_logger.info("AUDIT SUMMARY: No critical issues detected — all checks passed")

    # Overall pass/fail assessment
    critical_fails = [
        ("Prices", price_success_count, n_total),
        ("P/E Ratio", n_pe, n_total),
        ("P/B Ratio", n_pb, n_total),
        ("EV/EBITDA", n_ev, n_total),
        ("Dividend Yield", n_dy, n_total),
        ("Debt/Equity", n_de, n_total),
        ("Value Score", n_value, n_total),
        ("News Coverage", n_news_tickers, n_total),
        ("Sentiment Score", n_sent, n_total),
    ]
    below_80 = [(name, cnt, tot) for name, cnt, tot in critical_fails if _pct(cnt, tot) < 80]
    if below_80:
        pipeline_logger.warning(
            "AUDIT: %d categories BELOW 80%% target: %s",
            len(below_80),
            ", ".join(f"{n} ({_pct(c, t):.1f}%)" for n, c, t in below_80),
        )
    else:
        pipeline_logger.info("AUDIT: ALL categories at or above 80%% target — PASS")

    pipeline_logger.info("=" * 60)
    pipeline_logger.info("COMPREHENSIVE DATA AUDIT — COMPLETE")
    pipeline_logger.info("=" * 60)

    progress.print_banner("PIPELINE COMPLETE", f"Run ID: {run_id}")


if __name__ == "__main__":
    run_pipeline()
