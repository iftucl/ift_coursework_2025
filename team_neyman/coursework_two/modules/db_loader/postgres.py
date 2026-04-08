from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import create_engine, text

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_engine():
    config = load_config()["postgres"]
    url = f"postgresql+psycopg://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{config['dbname']}"
    return create_engine(url)


# Initialize the engine
engine = get_engine()


def check_connection():
    """Returns True if the database is reachable, False otherwise."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            return True
    except Exception:
        return False


def get_table(name: str, columns: list = None, schema: str = "systematic_equity"):
    """
    Retrieves specified columns from a given database table.

    Args:
        name (str): The name of the database table to query.
        columns (list, optional): A list of column names to retrieve. Defaults to None (fetches all columns).
        schema (str, optional): The database schema name. Defaults to 'systematic_equity'.

    Returns:
        pd.DataFrame: A DataFrame containing the requested data, or None if a database error occurs.
    """

    if columns is None or len(columns) == 0:
        col_str = "*"
    else:
        col_str = ", ".join([f'"{col}"' for col in columns])

    query = f'SELECT {col_str} FROM "{schema}"."{name}"'

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None


def get_latest_data(
    table_name: str,
    columns: list = None,
    symbols: list = None,
    periods: list = None,
    as_of_date: str = None,
    date_col: str = "price_date",
    distinct_cols: list = None,
    schema: str = "systematic_equity",
):
    """
    Retrieves the most recent records from a specified database table, grouped by defined unique columns.

    This function utilizes PostgreSQL's 'DISTINCT ON' capability to fetch the latest row
    for each unique group (e.g., symbol), constrained by an optional 'as_of_date'.
    This is critical for point-in-time backtesting to avoid look-ahead bias.

    Args:
        table_name (str): The name of the database table to query.
        columns (list, optional): Specific columns to retrieve. Defaults to None (fetches all columns).
        symbols (list, optional): A list of ticker symbols to filter by. Defaults to None.
        periods (list, optional): A list of fiscal periods (e.g., ["Current Year"]) to filter by. Defaults to None.
        as_of_date (str, optional): The cutoff date (YYYY-MM-DD). Only data on or
                                    BEFORE this date is considered. Defaults to None.
        date_col (str, optional): The date column used to determine the "latest" record. Defaults to 'price_date'.
        distinct_cols (list, optional): The columns to group by for the DISTINCT ON clause. Defaults to ["symbol"].
        schema (str, optional): The database schema name. Defaults to 'systematic_equity'.

    Returns:
        pd.DataFrame: A DataFrame containing the most recent records matching the filters.
                      Returns an empty DataFrame if no data matches, or None if a database error occurs.
    """

    if distinct_cols is None:
        distinct_cols = ["symbol"]

    if columns is None or len(columns) == 0:
        col_str = "*"
    else:
        safe_cols = set(columns)
        safe_cols.update(distinct_cols)
        safe_cols.add(date_col)
        col_str = ", ".join([f'"{col}"' for col in safe_cols])

    distinct_str = ", ".join([f'"{col}"' for col in distinct_cols])

    query = f"""
        SELECT DISTINCT ON ({distinct_str}) {col_str}
        FROM "{schema}"."{table_name}"
    """

    where_clauses = []
    params = {}

    if symbols:
        where_clauses.append("symbol = ANY(:symbols)")
        params["symbols"] = list(symbols)

    if periods:
        where_clauses.append("period = ANY(:periods)")
        params["periods"] = list(periods)

    if as_of_date:
        where_clauses.append(f'"{date_col}" <= :as_of_date')
        params["as_of_date"] = as_of_date

    if where_clauses:
        query += "\nWHERE " + " AND ".join(where_clauses)

    order_by_prefix = ", ".join([f'"{col}" ASC' for col in distinct_cols])
    query += f'\nORDER BY {order_by_prefix}, "{date_col}" DESC;'
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
        if df.empty:
            print(f"Warning: The table '{table_name}' is empty or no symbols matched.")
            return pd.DataFrame()
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None


def get_symbol_data(
    symbol_name: str,
    table_name: str,
    date_col: str = "price_date",
    schema: str = "systematic_equity",
):
    """
    Retrieves chronological time-series data for a specific ticker symbol from a database table.

    This function fetches all available historical records for a single company,
    ensuring the output is strictly sorted by date from oldest to newest. It also
    automatically converts the 'price_date' column into Pandas datetime objects
    for immediate use in time-series analysis or plotting.

    Args:
        symbol_name (str): The ticker symbol to fetch data for (e.g., 'AAPL').
        table_name (str): The name of the database table to query (e.g., 'daily_ohlcv').
        date_col (str, optional): The name of the date column to sort and convert. Defaults to 'price_date'.
        schema (str, optional): The database schema name. Defaults to 'systematic_equity'.

    Returns:
        pd.DataFrame: A time-series DataFrame for the specified symbol.
                      Returns an empty DataFrame if no records are found,
                      or None if a database error occurs.
    """

    query = f"""
        SELECT *
        FROM "{schema}"."{table_name}"
        WHERE symbol = :symbol
        ORDER BY "{date_col}" ASC;
    """

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params={"symbol": symbol_name})
        if df.empty:
            print(
                f"Warning: The table '{table_name}' is empty or symbol '{symbol_name}' not found."
            )
            return pd.DataFrame()
        df[date_col] = pd.to_datetime(df[date_col])
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None


def get_latest_date(table_name: str, schema: str = "systematic_equity"):
    """
    Retrieves the most recent 'price_date' available in a specified database table.

    This function executes a lightweight SQL MAX() aggregation. It is highly optimized
    for finding the last updated date of a table without transferring any actual rows
    into Pandas. It is commonly used to determine the starting date for incremental
    daily data downloads (e.g., fetching only new API data since this date).

    Args:
        table_name (str): The name of the database table to check (e.g., 'daily_ohlcv').
        schema (str, optional): The database schema name. Defaults to 'systematic_equity'.

    Returns:
        datetime.date or None: The maximum date found in the table.
                               Returns None if the table is completely empty
                               or if a database error occurs.
    """

    query = f"""
    SELECT MAX(price_date)
    FROM "{schema}"."{table_name}";
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query)).scalar()
            return result
    except Exception as e:
        print(f"Database Error: {e}")
        return None


def get_companies_by_sector(sector_list: list):
    """
    Retrieves company details from the static database filtered by specified GICS sectors.

    This function queries the 'company_static' table using PostgreSQL's efficient
    ANY() array function to handle multiple sectors simultaneously. It also includes
    a critical data-cleaning step that strips hidden whitespace from the 'symbol'
    column, ensuring flawless DataFrame joins downstream in the quantitative pipeline.

    Args:
        sector_list (list): A list of GICS sector names to query
                            (e.g., ['Information Technology', 'Health Care']).

    Returns:
        pd.DataFrame: A DataFrame containing the static information for the matching companies.
                      Returns an empty DataFrame if no matches are found, or None if
                      a database error occurs.
    """

    query = """
    SELECT *
    FROM systematic_equity.company_static
    WHERE gics_sector = ANY(:sectors);
    """
    try:
        params = {"sectors": list(sector_list)}
        df = pd.read_sql(text(query), engine, params=params)
        if df is not None and not df.empty and "symbol" in df.columns:
            df["symbol"] = df["symbol"].str.strip()
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None


def get_companies_by_industry(industry_list: list):
    """
    Retrieves company details from the static database filtered by specified GICS industries.

    This function queries the 'company_static' table using PostgreSQL's efficient
    ANY() array function to handle multiple specific industries (a more granular
    classification than sectors) simultaneously. It includes the same critical
    whitespace stripping on the 'symbol' column to guarantee clean downstream joins.

    Args:
        industry_list (list): A list of specific GICS industry names to query
                              (e.g., ['Semiconductors & Semiconductor Equipment', 'Biotechnology']).

    Returns:
        pd.DataFrame: A DataFrame containing the static information for the matching companies.
                      Returns an empty DataFrame if no matches are found, or None if
                      a database error occurs.
    """

    query = """
    SELECT *
    FROM systematic_equity.company_static
    WHERE gics_industry = ANY(:industries);
    """
    try:
        params = {"industries": list(industry_list)}
        df = pd.read_sql(text(query), engine, params=params)
        if df is not None and not df.empty and "symbol" in df.columns:
            df["symbol"] = df["symbol"].str.strip()
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None


def get_all_sectors():
    """
    Retrieves a unique, alphabetically sorted list of all GICS sectors present in the database.

    This function executes a SQL SELECT DISTINCT query to dynamically fetch all available
    sectors. It intentionally extracts the Pandas column into a native Python list,
    making it ideal for instantly populating UI dropdowns (like Streamlit/Dash) or
    creating iteration loops for sector-neutral backtesting.

    Args:
        None

    Returns:
        list: A list of strings representing the unique GICS sectors.
              Returns an empty list [] if a database error occurs.
    """

    query = """
    SELECT DISTINCT gics_sector
    FROM systematic_equity.company_static
    ORDER BY gics_sector ASC;
    """
    try:
        df = pd.read_sql(text(query), engine)
        return df["gics_sector"].tolist()
    except Exception as e:
        print(f"Database Error: {e}")
        return []


def get_all_industries():
    """
    Retrieves a unique, alphabetically sorted list of all GICS industries present in the database.

    This function executes a SQL SELECT DISTINCT query to dynamically fetch all available
    industries (a more granular classification than sectors). It extracts the Pandas
    column into a native Python list, making it ideal for creating iteration loops
    for industry-neutral backtesting or populating dynamic UI dropdowns.

    Args:
        None

    Returns:
        list: A list of strings representing the unique GICS industries
              (e.g., ['Biotechnology', 'Semiconductors & Semiconductor Equipment']).
              Returns an empty list [] if a database error occurs.
    """

    query = """
    SELECT DISTINCT gics_industry
    FROM systematic_equity.company_static
    ORDER BY gics_industry ASC;
    """
    try:
        df = pd.read_sql(text(query), engine)
        return df["gics_industry"].tolist()
    except Exception as e:
        print(f"Database Error: {e}")
        return []


def get_ohlcv_data(company_list: list, start_date=None):
    """
    Retrieves historical OHLCV time-series data for a specific list of companies.

    This function dynamically constructs a SQL query to fetch pricing data for multiple
    tickers simultaneously. It supports optional chronological filtering to limit memory
    usage, and strictly orders the resulting DataFrame into a classic 'Panel Data'
    format (sorted by symbol, then chronologically by date). It also ensures the
    date column is ready for immediate quantitative analysis.

    Args:
        company_list (list): A list of ticker symbols to retrieve (e.g., ['AAPL', 'MSFT']).
        start_date (str or datetime.date, optional): The earliest date to retrieve data for
                                                     (e.g., '2023-01-01'). Defaults to None.

    Returns:
        pd.DataFrame: A formatted DataFrame containing the requested OHLCV data.
                      Returns an empty DataFrame if the input list is empty or no
                      records are found, and None if a database error occurs.
    """

    if not company_list:
        print("Warning: Empty company_list provided.")
        return pd.DataFrame()

    query = """
    SELECT *
    FROM systematic_equity.daily_ohlcv
    WHERE symbol = ANY(:companies)
    """

    params = {"companies": company_list}

    if start_date is not None:
        query += " AND price_date >= :start_date"
        params["start_date"] = start_date

    query += "\nORDER BY symbol, price_date ASC;"

    try:
        df = pd.read_sql(text(query), engine, params=params)
        df["price_date"] = pd.to_datetime(df["price_date"])
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None
