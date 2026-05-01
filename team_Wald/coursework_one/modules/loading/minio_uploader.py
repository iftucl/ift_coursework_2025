"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : MinIO uploader for raw data lake storage
Project : CW1 - Value + News Sentiment Strategy

Takes raw data from extractors and uploads to MinIO with the
folder structure specified in the role instructions::

    raw-data/
    ├── financial/{year}/{ticker}/
    │   ├── income_statement.json
    │   ├── balance_sheet.json
    │   └── cash_flow.json
    ├── prices/{year}/{ticker}/daily_prices.csv
    ├── news/{date}/{ticker}/articles.json
    └── company_info/{ticker}/info.json
"""

from datetime import date

import pandas as pd

from modules.db.minio_connection import MinioClient
from modules.utils.logger import pipeline_logger


def upload_financial_data(
    minio: MinioClient,
    ticker: str,
    financial_data: dict,
    year: str = None,
) -> int:
    """Upload raw financial statements (income, balance, cash flow) to MinIO.

    :param minio: Active MinIO client
    :type minio: MinioClient
    :param ticker: Company ticker symbol
    :type ticker: str
    :param financial_data: Dict with keys income_statement, balance_sheet, cash_flow
    :type financial_data: dict
    :param year: Year subfolder (default: current year)
    :type year: str or None
    :return: Number of files uploaded
    :rtype: int

    Example::

        >>> count = upload_financial_data(minio, 'AAPL', {'income_statement': {...}})
        >>> count
        3
    """
    year = year or str(date.today().year)
    count = 0
    for statement_type in ["income_statement", "balance_sheet", "cash_flow"]:
        data = financial_data.get(statement_type)
        if data:
            minio.upload_json(
                data_dict=data,
                category=f"financial/{year}",
                identifier=ticker,
                filename=f"{statement_type}.json",
            )
            count += 1
    if count > 0:
        pipeline_logger.info("Uploaded %d financial files for %s/%s", count, ticker, year)
    return count


def upload_price_data(
    minio: MinioClient,
    ticker: str,
    price_df: pd.DataFrame,
    year: str = None,
):
    """Upload daily price CSV to MinIO.

    :param minio: Active MinIO client
    :type minio: MinioClient
    :param ticker: Company ticker symbol
    :type ticker: str
    :param price_df: Price DataFrame with OHLCV data
    :type price_df: pd.DataFrame
    :param year: Year subfolder (default: current year)
    :type year: str or None
    """
    if price_df is None or price_df.empty:
        return
    year = year or str(date.today().year)
    minio.upload_csv(
        df=price_df,
        category=f"prices/{year}",
        identifier=ticker,
        filename="daily_prices.csv",
    )


def upload_news_articles(
    minio: MinioClient,
    ticker: str,
    articles: list[dict],
    date_str: str = None,
):
    """Upload news articles JSON to MinIO.

    :param minio: Active MinIO client
    :type minio: MinioClient
    :param ticker: Company ticker symbol
    :type ticker: str
    :param articles: List of article dicts
    :type articles: list[dict]
    :param date_str: Date subfolder (default: today)
    :type date_str: str or None
    """
    if not articles:
        return
    date_str = date_str or date.today().strftime("%Y-%m-%d")
    minio.upload_json(
        data_dict={"articles": articles, "count": len(articles)},
        category=f"news/{date_str}",
        identifier=ticker,
        filename="articles.json",
    )


def upload_company_info(minio: MinioClient, ticker: str, info: dict):
    """Upload company info JSON to MinIO.

    :param minio: Active MinIO client
    :type minio: MinioClient
    :param ticker: Company ticker symbol
    :type ticker: str
    :param info: Company info dict from yfinance
    :type info: dict
    """
    if not info:
        return
    minio.upload_json(
        data_dict=info,
        category="company_info",
        identifier=ticker,
        filename="info.json",
    )


def upload_all_raw_data(
    minio: MinioClient,
    ticker: str,
    ticker_data: dict,
):
    """Upload all raw data for a single ticker to MinIO.

    Convenience function that dispatches to the appropriate uploader
    based on the data types present in ticker_data.

    :param minio: Active MinIO client
    :type minio: MinioClient
    :param ticker: Company ticker symbol
    :type ticker: str
    :param ticker_data: Dict with keys: prices, info, financials, news
    :type ticker_data: dict
    """
    if "financials" in ticker_data and ticker_data["financials"]:
        upload_financial_data(minio, ticker, ticker_data["financials"])
    if "prices" in ticker_data and isinstance(ticker_data["prices"], pd.DataFrame):
        upload_price_data(minio, ticker, ticker_data["prices"])
    if "news" in ticker_data and ticker_data["news"]:
        upload_news_articles(minio, ticker, ticker_data["news"])
    if "info" in ticker_data and ticker_data["info"]:
        upload_company_info(minio, ticker, ticker_data["info"])
