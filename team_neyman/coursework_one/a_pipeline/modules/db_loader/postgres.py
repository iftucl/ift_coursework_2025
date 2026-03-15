import pandas as pd
import yaml
from pathlib import Path
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


# engine = create_engine(
#    "postgresql+psycopg://postgres:postgres@postgres_db_cw:5432/fift"
# )


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


def add_new_column(
    df: pd.DataFrame,
    column_name: str,
    column_type: str,
    table_name: str,
    schema: str = "systematic_equity",
):
    """
    Dynamically adds a new column to a derived feature table and populates it using a bulk update.

    This function is strictly designed for daily time-series factor tables.
    It utilizes a temporary staging table to perform a rapid database-side
    UPDATE JOIN based on 'symbol' and 'price_date'.

    Args:
        df (pd.DataFrame): The Pandas DataFrame containing the calculated data.
        column_name (str): The name of the new column to add (e.g., 'ma200').
        column_type (str): The PostgreSQL data type for the new column (e.g., 'NUMERIC(10, 4)').
        table_name (str): The name of the target database table.
        schema (str, optional): The database schema name. Defaults to 'systematic_equity'.

    Returns:
        None: Executes database commands directly.
    """

    alter_query = f"""
    ALTER TABLE "{schema}"."{table_name}"
    ADD COLUMN IF NOT EXISTS "{column_name}" {column_type};
    """

    try:
        with engine.begin() as conn:
            conn.execute(text(alter_query))
        print(f"Successfully ensured column '{column_name}' exists.")
    except Exception as e:
        print(f"Database Error during ALTER TABLE: {e}")
        return

    temp_table = f"temp_{table_name}_update"
    upload_df = df[["symbol", "price_date", column_name]]

    try:
        upload_df.to_sql(
            temp_table, engine, schema=schema, if_exists="replace", index=False
        )

        update_query = f"""
        UPDATE "{schema}"."{table_name}" AS main
        SET "{column_name}" = temp."{column_name}"
        FROM "{schema}"."{temp_table}" AS temp
        WHERE main.symbol = temp.symbol
          AND main.price_date = temp.price_date;
        """

        with engine.begin() as conn:
            conn.execute(text(update_query))
            conn.execute(text(f'DROP TABLE "{schema}"."{temp_table}";'))

        print(f"Successfully populated '{column_name}' with data!")

    except Exception as e:
        print(f"Database Error during data upload: {e}")


def del_table(table_name: str, schema: str = "systematic_equity"):
    """
    Permanently deletes a specified table from the database.

    This is a destructive operation that executes a SQL DROP TABLE command.
    It uses the IF EXISTS clause to silently succeed if the table has already
    been removed, preventing pipeline crashes during teardown or reset scripts.

    Args:
        table_name (str): The name of the database table to delete (e.g., 'temp_eps_update').
        schema (str, optional): The database schema name. Defaults to 'systematic_equity'.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = f"""
    DROP TABLE IF EXISTS "{schema}"."{table_name}";
    """

    try:
        with engine.begin() as conn:
            conn.execute(text(query))
        print(f"Successfully permanently deleted table: '{schema}.{table_name}'")
    except Exception as e:
        print(f"Database Error: {e}")


def del_column(column_name: str, table_name: str, schema: str = "systematic_equity"):
    """
    Permanently removes a specified column from a database table.

    This function executes an ALTER TABLE ... DROP COLUMN command. It is highly
    useful in quantitative pipelines for cleaning up deprecated features or
    rolling back unsuccessful factor calculations. The IF EXISTS clause ensures
    automated cleanup scripts do not crash if the target column is already gone.

    Args:
        column_name (str): The name of the column to delete (e.g., 'bad_factor_1m').
        table_name (str): The name of the database table to modify.
        schema (str, optional): The database schema name. Defaults to 'systematic_equity'.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = f"""
    ALTER TABLE "{schema}"."{table_name}"
    DROP COLUMN IF EXISTS "{column_name}";
    """

    try:
        with engine.begin() as conn:
            conn.execute(text(query))
        print(
            f"Successfully deleted column '{column_name}' from '{schema}.{table_name}'."
        )
    except Exception as e:
        print(f"Database Error: {e}")


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


def create_ohlcv_table():
    """
    Creates the 'daily_ohlcv' table and its optimized time-series index.

    This function executes a SQL schema definition for storing daily Open, High, Low,
    Close, and Volume (OHLCV) data. It enforces data integrity by utilizing a UNIQUE
    constraint on (symbol, price_date) to prevent duplicate daily records. It also
    builds a composite B-Tree index sorted by descending date to massively accelerate
    time-series retrieval queries.

    Args:
        None

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = """
    CREATE TABLE IF NOT EXISTS systematic_equity.daily_ohlcv (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        price_date DATE NOT NULL,
        open_price NUMERIC(14, 4),
        high_price NUMERIC(14, 4),
        low_price NUMERIC(14, 4),
        close_price NUMERIC(14, 4),
        volume BIGINT,
        UNIQUE (symbol, price_date)
    );

    CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_date
    ON systematic_equity.daily_ohlcv (symbol, price_date DESC);
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()
            print("Table and Index created successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def update_ohlcv_data(data: pd.DataFrame):
    """
    Performs an idempotent bulk upsert of daily price data into the database.

    This function utilizes a temporary staging table to efficiently upload large Pandas
    DataFrames. It executes a PostgreSQL 'INSERT ... ON CONFLICT DO UPDATE' command
    (an upsert). If a row for a specific ticker and date does not exist, it inserts it.
    If the row already exists, it updates the existing prices and volume. This ensures
    the ETL pipeline can be run safely multiple times without creating duplicate records.

    Args:
        data (pd.DataFrame): The DataFrame containing 'symbol', 'price_date', 'open_price',
                             'high_price', 'low_price', 'close_price', and 'volume'.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    temp_table = "temp_ohlcv"
    data.to_sql(
        temp_table, engine, schema="systematic_equity", if_exists="replace", index=False
    )
    query = """
    INSERT INTO systematic_equity.daily_ohlcv (symbol, price_date, open_price, high_price, low_price, close_price, volume)
    SELECT symbol, price_date, open_price, high_price, low_price, close_price, volume
    FROM systematic_equity.temp_ohlcv
    ON CONFLICT (symbol, price_date)
    DO UPDATE SET
        open_price = EXCLUDED.open_price,
        high_price = EXCLUDED.high_price,
        low_price = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price,
        volume = EXCLUDED.volume;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
            conn.execute(text(f"DROP TABLE systematic_equity.{temp_table};"))
        print("OHLCV table updated successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


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


"""
def get_close_price(symbol: str):
    query = """ """
    SELECT price_date, close_price
    FROM systematic_equity.daily_ohlcv
    WHERE symbol = :symbol
    ORDER BY price_date ASC;
    """ """
    try:
        params = {"symbol": symbol}
        df = pd.read_sql(text(query), engine, params = params)
        df['price_date'] = pd.to_datetime(df['price_date'])
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None
"""


def create_liquidity_table():
    """
    Creates the 'liquidity_factors' table and its optimized time-series index.

    This function executes a SQL schema definition designed to store derived liquidity
    metrics (such as volume averages, medians, and Amihud illiquidity). It enforces
    data integrity with a UNIQUE constraint on (symbol, price_date) and builds a
    composite B-Tree index sorted by descending date for rapid time-series querying.

    Args:
        None

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = """
    CREATE TABLE IF NOT EXISTS systematic_equity.liquidity_factors (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        price_date DATE NOT NULL,
        volume BIGINT,
        dollar_volume NUMERIC(18, 2),
        adv_20d BIGINT,
        adv_60d BIGINT,
        mdv_20d BIGINT,
        mdv_60d BIGINT,
        addv_20d NUMERIC(18, 2),
        addv_60d NUMERIC(18, 2),
        mddv_20d NUMERIC(18, 2),
        mddv_60d NUMERIC(18, 2),
        amihud_illiquidity_20d NUMERIC(20, 10),
        amihud_illiquidity_60d NUMERIC(20, 10),
        UNIQUE (symbol, price_date)
    );

    CREATE INDEX IF NOT EXISTS idx_liquidity_symbol_date
    ON systematic_equity.liquidity_factors (symbol, price_date DESC);
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()
            print("Liquidity table and Index created successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def update_liquidity_data(data: pd.DataFrame):
    """
    Performs an idempotent bulk upsert of calculated liquidity factors into the database.

    This function utilizes a temporary staging table to efficiently upload large Pandas
    DataFrames containing derived liquidity metrics (e.g., ADV, MDV, Amihud Illiquidity).
    It executes a PostgreSQL 'INSERT ... ON CONFLICT DO UPDATE' command. If a row for a
    specific ticker and date already exists, it intelligently overwrites the old factor
    values with the newly calculated ones, preventing duplicate primary key crashes.

    Args:
        data (pd.DataFrame): The DataFrame containing 'symbol', 'price_date', and all
                             calculated liquidity factor columns.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    temp_table = "temp_liquidity"
    data.to_sql(
        temp_table, engine, schema="systematic_equity", if_exists="replace", index=False
    )
    query = """
    INSERT INTO systematic_equity.liquidity_factors (symbol, price_date, volume, dollar_volume, adv_20d, adv_60d, mdv_20d, mdv_60d,
    addv_20d, addv_60d, mddv_20d, mddv_60d, amihud_illiquidity_20d, amihud_illiquidity_60d)
    SELECT symbol, price_date, volume, dollar_volume, adv_20d, adv_60d, mdv_20d, mdv_60d,
    addv_20d, addv_60d, mddv_20d, mddv_60d, amihud_illiquidity_20d, amihud_illiquidity_60d
    FROM systematic_equity.temp_liquidity
    ON CONFLICT (symbol, price_date)
    DO UPDATE SET
        volume = EXCLUDED.volume,
        dollar_volume = EXCLUDED.dollar_volume,
        adv_20d = EXCLUDED.adv_20d,
        adv_60d = EXCLUDED.adv_60d,
        mdv_20d = EXCLUDED.mdv_20d,
        mdv_60d = EXCLUDED.mdv_60d,
        addv_20d = EXCLUDED.addv_20d,
        addv_60d = EXCLUDED.addv_60d,
        mddv_20d = EXCLUDED.mddv_20d,
        mddv_60d = EXCLUDED.mddv_60d,
        amihud_illiquidity_20d = EXCLUDED.amihud_illiquidity_20d,
        amihud_illiquidity_60d = EXCLUDED.amihud_illiquidity_60d;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
            conn.execute(text(f"DROP TABLE systematic_equity.{temp_table};"))
        print("Liquidity table updated successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def create_trend_table():
    """
    Creates the 'trend_factors' table and its optimized time-series index.

    This function executes a SQL schema definition designed to store derived trend-following
    metrics. It includes standard moving averages (MA), breakout levels (Donchian Channels),
    and trend strength indicators (ADX). It enforces data integrity with a UNIQUE constraint
    on (symbol, price_date) and builds a composite B-Tree index sorted by descending date
    for rapid time-series querying.

    Args:
        None

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = """
    CREATE TABLE IF NOT EXISTS systematic_equity.trend_factors (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        price_date DATE NOT NULL,
        ma200 NUMERIC(14, 4),
        ma150 NUMERIC(14, 4),
        ma100 NUMERIC(14, 4),
        adx14 NUMERIC(6, 2),
        donchian_high_55 NUMERIC(14, 4),
        donchian_high_120 NUMERIC(14, 4),
        price_to_52w_high NUMERIC(6, 4),
        ma200_20d_roc NUMERIC(10, 6),
        UNIQUE (symbol, price_date)
    );

    CREATE INDEX IF NOT EXISTS idx_trend_symbol_date
    ON systematic_equity.trend_factors (symbol, price_date DESC);
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()
            print("Trend table and Index created successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def update_trend_data(data: pd.DataFrame):
    """
    Performs an idempotent bulk upsert of calculated trend factors into the database.

    This function utilizes a temporary staging table to efficiently upload Pandas
    DataFrames containing derived trend-following metrics (e.g., Moving Averages,
    ADX, Donchian Channels). It executes a PostgreSQL 'INSERT ... ON CONFLICT DO UPDATE'
    command to seamlessly insert new daily records or update existing rows without
    violating primary key constraints.

    Args:
        data (pd.DataFrame): The DataFrame containing 'symbol', 'price_date', and all
                             calculated trend factor columns.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    temp_table = "temp_trend"
    data.to_sql(
        temp_table, engine, schema="systematic_equity", if_exists="replace", index=False
    )
    query = """
    INSERT INTO systematic_equity.trend_factors (symbol, price_date, ma200, ma150, ma100, adx14, donchian_high_55, donchian_high_120,
    price_to_52w_high, ma200_20d_roc)
    SELECT symbol, price_date, ma200, ma150, ma100, adx14, donchian_high_55, donchian_high_120, price_to_52w_high, ma200_20d_roc
    FROM systematic_equity.temp_trend
    ON CONFLICT (symbol, price_date)
    DO UPDATE SET
        ma200 = EXCLUDED.ma200,
        ma150 = EXCLUDED.ma150,
        ma100 = EXCLUDED.ma100,
        adx14 = EXCLUDED.adx14,
        donchian_high_55 = EXCLUDED.donchian_high_55,
        donchian_high_120 = EXCLUDED.donchian_high_120,
        price_to_52w_high = EXCLUDED.price_to_52w_high,
        ma200_20d_roc = EXCLUDED.ma200_20d_roc;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
            conn.execute(text(f"DROP TABLE systematic_equity.{temp_table};"))
        print("Trend table updated successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def create_momentum_table():
    """
    Creates the 'momentum_factors' table and its optimized time-series index.

    This function executes a SQL schema definition to store derived cross-sectional
    and time-series momentum metrics. It includes raw historical returns, risk-adjusted
    momentum scores, and positive return consistency (hit rates). It enforces data
    integrity with a UNIQUE constraint on (symbol, price_date) and builds a composite
    B-Tree index sorted by descending date for highly optimized time-series queries.

    Args:
        None

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = """
    CREATE TABLE IF NOT EXISTS systematic_equity.momentum_factors (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        price_date DATE NOT NULL,
        mom_12m NUMERIC(10, 6),
        mom_6m NUMERIC(10, 6),
        mom_3m NUMERIC(10, 6),
        ret_1m NUMERIC(10, 6),
        ret_3m NUMERIC(10, 6),
        ret_6m NUMERIC(10, 6),
        ret_12m NUMERIC(10, 6),
        risk_adj_mom_12m NUMERIC(14, 6),
        risk_adj_ret_6m NUMERIC(14, 6),
        positive_ret_pct_60d NUMERIC(8, 6),
        positive_ret_prc_120d NUMERIC(8, 6),
        UNIQUE (symbol, price_date)
    );

    CREATE INDEX IF NOT EXISTS idx_momentum_symbol_date
    ON systematic_equity.momentum_factors (symbol, price_date DESC);
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()
            print("Momentum table and Index created successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def update_momentum_data(data: pd.DataFrame):
    """
    Performs an idempotent bulk upsert of calculated momentum factors into the database.

    This function utilizes a temporary staging table to efficiently upload Pandas
    DataFrames containing derived momentum metrics (e.g., trailing returns, risk-adjusted
    momentum, and return consistency). It executes a PostgreSQL 'INSERT ... ON CONFLICT
    DO UPDATE' command to seamlessly insert new daily records or update existing rows
    without violating the (symbol, price_date) primary key constraints.

    Args:
        data (pd.DataFrame): The DataFrame containing 'symbol', 'price_date', and all
                             calculated momentum factor columns.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    temp_table = "temp_momentum"
    data.to_sql(
        temp_table, engine, schema="systematic_equity", if_exists="replace", index=False
    )
    query = """
    INSERT INTO systematic_equity.momentum_factors (symbol, price_date, mom_12m, mom_6m, mom_3m, ret_1m, ret_3m, ret_6m, ret_12m,
    risk_adj_mom_12m, risk_adj_ret_6m, positive_ret_pct_60d, positive_ret_prc_120d)
    SELECT symbol, price_date, mom_12m, mom_6m, mom_3m, ret_1m, ret_3m, ret_6m, ret_12m, risk_adj_mom_12m, risk_adj_ret_6m,
    positive_ret_pct_60d, positive_ret_prc_120d
    FROM systematic_equity.temp_momentum
    ON CONFLICT (symbol, price_date)
    DO UPDATE SET
        mom_12m = EXCLUDED.mom_12m,
        mom_6m = EXCLUDED.mom_6m,
        mom_3m = EXCLUDED.mom_3m,
        ret_1m = EXCLUDED.ret_1m,
        ret_3m = EXCLUDED.ret_3m,
        ret_6m = EXCLUDED.ret_6m,
        ret_12m = EXCLUDED.ret_12m,
        risk_adj_mom_12m = EXCLUDED.risk_adj_mom_12m,
        risk_adj_ret_6m = EXCLUDED.risk_adj_ret_6m,
        positive_ret_pct_60d = EXCLUDED.positive_ret_pct_60d,
        positive_ret_prc_120d = EXCLUDED.positive_ret_prc_120d;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
            conn.execute(text(f"DROP TABLE systematic_equity.{temp_table};"))
        print("Momentum table updated successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def create_risk_table():
    """
    Creates the 'risk_factors' table and its optimized time-series index.

    This function executes a SQL schema definition designed to store derived risk
    and volatility metrics. It includes standard deviation (volatility), downside
    deviation, maximum drawdowns, and tail-risk metrics like Value at Risk (VaR)
    and Conditional VaR (CVaR). It enforces data integrity with a UNIQUE constraint
    on (symbol, price_date) and builds a composite B-Tree index sorted by descending
    date for rapid time-series querying.

    Args:
        None

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = """
    CREATE TABLE IF NOT EXISTS systematic_equity.risk_factors (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        price_date DATE NOT NULL,
        vol_20d NUMERIC(10, 6),
        vol_60d NUMERIC(10, 6),
        vol_120d NUMERIC(10, 6),
        downside_vol_60d NUMERIC(10, 6),
        max_drawdown_6m NUMERIC(10, 6),
        max_drawdown_1y NUMERIC(10, 6),
        historical_var_95_1m NUMERIC(20, 4),
        historical_cvar_95_1m NUMERIC(20, 4),
        worst_day_ret_1y NUMERIC(10, 6),
        worst_week_ret_1y NUMERIC(10, 6),
        UNIQUE (symbol, price_date)
    );

    CREATE INDEX IF NOT EXISTS idx_risk_symbol_date
    ON systematic_equity.risk_factors (symbol, price_date DESC);
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()
            print("Risk table and Index created successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def update_risk_data(data: pd.DataFrame):
    """
    Performs an idempotent bulk upsert of calculated risk factors into the database.

    This function utilizes a temporary staging table to efficiently upload Pandas
    DataFrames containing derived risk metrics (e.g., volatility, drawdowns, VaR).
    It executes a PostgreSQL 'INSERT ... ON CONFLICT DO UPDATE' command to seamlessly
    insert new daily records or intelligently overwrite existing rows without violating
    the (symbol, price_date) primary key constraints.

    Args:
        data (pd.DataFrame): The DataFrame containing 'symbol', 'price_date', and all
                             calculated risk factor columns.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    temp_table = "temp_risk"
    data.to_sql(
        temp_table, engine, schema="systematic_equity", if_exists="replace", index=False
    )
    query = """
    INSERT INTO systematic_equity.risk_factors (symbol, price_date, vol_20d, vol_60d, vol_120d, downside_vol_60d, max_drawdown_6m,
    max_drawdown_1y, historical_var_95_1m, historical_cvar_95_1m, worst_day_ret_1y, worst_week_ret_1y)
    SELECT symbol, price_date, vol_20d, vol_60d, vol_120d, downside_vol_60d, max_drawdown_6m,
    max_drawdown_1y, historical_var_95_1m, historical_cvar_95_1m, worst_day_ret_1y, worst_week_ret_1y
    FROM systematic_equity.temp_risk
    ON CONFLICT (symbol, price_date)
    DO UPDATE SET
        vol_20d = EXCLUDED.vol_20d,
        vol_60d = EXCLUDED.vol_60d,
        vol_120d = EXCLUDED.vol_120d,
        downside_vol_60d = EXCLUDED.downside_vol_60d,
        max_drawdown_6m = EXCLUDED.max_drawdown_6m,
        max_drawdown_1y = EXCLUDED.max_drawdown_1y,
        historical_var_95_1m = EXCLUDED.historical_var_95_1m,
        historical_cvar_95_1m = EXCLUDED.historical_cvar_95_1m,
        worst_day_ret_1y = EXCLUDED.worst_day_ret_1y,
        worst_week_ret_1y = EXCLUDED.worst_week_ret_1y;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
            conn.execute(text(f"DROP TABLE systematic_equity.{temp_table};"))
        print("Risk table updated successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def create_mean_reversion_table():
    """
    Creates the 'mean_reversion_factors' table and its optimized time-series index.

    This function executes a SQL schema definition designed to store short-term
    mean-reversion metrics (such as RSI, Bollinger Band %b, and short-term trailing
    returns). It enforces data integrity with a UNIQUE constraint on (symbol, price_date)
    and builds a composite B-Tree index sorted by descending date for rapid,
    time-series querying.

    Args:
        None

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = """
    CREATE TABLE IF NOT EXISTS systematic_equity.mean_reversion_factors (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        price_date DATE NOT NULL,
        rsi_2d NUMERIC(6, 2),
        rsi_5d NUMERIC(6, 2),
        rsi_14d NUMERIC(6, 2),
        bollinger_pct_20d NUMERIC(10, 6),
        ret_5d NUMERIC(10, 6),
        ret_10d NUMERIC(10, 6),
        UNIQUE (symbol, price_date)
    );

    CREATE INDEX IF NOT EXISTS idx_mean_reversion_symbol_date
    ON systematic_equity.mean_reversion_factors (symbol, price_date DESC);
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()
            print("Mean Reversion table and Index created successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def update_mean_reversion_data(data: pd.DataFrame):
    """
    Performs an idempotent bulk upsert of calculated mean-reversion factors into the database.

    This function utilizes a temporary staging table to efficiently upload Pandas
    DataFrames containing derived short-term mean-reversion metrics (e.g., RSI,
    Bollinger Band %b, short-term trailing returns). It executes a PostgreSQL
    'INSERT ... ON CONFLICT DO UPDATE' command to seamlessly insert new daily
    records or intelligently overwrite existing rows without violating the
    (symbol, price_date) primary key constraints.

    Args:
        data (pd.DataFrame): The DataFrame containing 'symbol', 'price_date', and all
                             calculated mean-reversion factor columns.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    temp_table = "temp_mean_reversion"
    data.to_sql(
        temp_table, engine, schema="systematic_equity", if_exists="replace", index=False
    )
    query = """
    INSERT INTO systematic_equity.mean_reversion_factors (symbol, price_date, rsi_2d, rsi_5d, rsi_14d, bollinger_pct_20d, ret_5d, ret_10d)
    SELECT symbol, price_date, rsi_2d, rsi_5d, rsi_14d, bollinger_pct_20d, ret_5d, ret_10d
    FROM systematic_equity.temp_mean_reversion
    ON CONFLICT (symbol, price_date)
    DO UPDATE SET
        rsi_2d = EXCLUDED.rsi_2d,
        rsi_5d = EXCLUDED.rsi_5d,
        rsi_14d = EXCLUDED.rsi_14d,
        bollinger_pct_20d = EXCLUDED.bollinger_pct_20d,
        ret_5d = EXCLUDED.ret_5d,
        ret_10d = EXCLUDED.ret_10d;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
            conn.execute(text(f"DROP TABLE systematic_equity.{temp_table};"))
        print("Mean reversion table updated successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def create_eps_history_table():
    """
    Creates the 'eps_history' table and its optimized time-series index.

    This function executes a SQL schema definition designed to store raw historical
    Earnings Per Share (EPS) data. It captures both the reported actuals and the
    consensus estimates for specific fiscal periods. It enforces data integrity
    with a UNIQUE constraint on (symbol, period_end_date) and builds a composite
    B-Tree index sorted by descending date for rapid historical querying.

    Args:
        None

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = """
    CREATE TABLE IF NOT EXISTS systematic_equity.eps_history (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        period_end_date DATE NOT NULL,
        reported_eps NUMERIC(16, 2),
        estimate_eps NUMERIC(16, 2),
        UNIQUE (symbol, period_end_date)
    );

    CREATE INDEX IF NOT EXISTS idx_eps_history_symbol_date
    ON systematic_equity.eps_history (symbol, period_end_date DESC);
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()
            print("EPS history table and Index created successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def update_eps_history(data: pd.DataFrame):
    """
    Performs an idempotent bulk upsert of historical EPS data into the database.

    This function utilizes a temporary staging table to efficiently upload Pandas
    DataFrames containing historical earnings actuals and estimates. It executes
    a PostgreSQL 'INSERT ... ON CONFLICT DO UPDATE' command. This is highly critical
    for fundamental data pipelines, as it seamlessly overwrites old records if a
    company restates past earnings or a data vendor corrects historical estimate figures.

    Args:
        data (pd.DataFrame): The DataFrame containing 'symbol', 'period_end_date',
                             'reported_eps', and 'estimate_eps'.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    temp_table = "temp_eps_history"
    data.to_sql(
        temp_table, engine, schema="systematic_equity", if_exists="replace", index=False
    )
    query = """
    INSERT INTO systematic_equity.eps_history (symbol, period_end_date, reported_eps, estimate_eps)
    SELECT symbol, period_end_date, reported_eps, estimate_eps
    FROM systematic_equity.temp_eps_history
    ON CONFLICT (symbol, period_end_date)
    DO UPDATE SET
        reported_eps = EXCLUDED.reported_eps,
        estimate_eps = EXCLUDED.estimate_eps;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
            conn.execute(text(f"DROP TABLE systematic_equity.{temp_table};"))
        print("EPS history table updated successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def create_eps_estimate_table():
    """
    Creates the 'eps_estimate' table and its optimized time-series index.

    This function executes a SQL schema definition designed to store forward-looking
    analyst earnings estimates. Crucially, it utilizes a 3-part UNIQUE constraint
    on (estimate_date, symbol, period_end_date) to allow tracking how consensus
    estimates evolve day-by-day leading up to an earnings report. It also builds a
    composite B-Tree index to rapidly query the most recent estimates.

    Args:
        None

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    query = """
    CREATE TABLE IF NOT EXISTS systematic_equity.eps_estimate (
        id SERIAL PRIMARY KEY,
        estimate_date DATE NOT NULL,
        symbol VARCHAR(10) NOT NULL,
        period VARCHAR(64) NOT NULL,
        period_end_date DATE NOT NULL,
        consensus_eps NUMERIC(7, 2),
        recent_eps NUMERIC(7, 2),
        estimate_count INT,
        estimate_high NUMERIC(7, 2),
        estimate_low NUMERIC(7, 2),
        year_ago_eps NUMERIC(7, 2),
        UNIQUE (estimate_date, symbol, period_end_date)
    );

    CREATE INDEX IF NOT EXISTS idx_eps_estimate_symbol_date
    ON systematic_equity.eps_estimate (estimate_date, symbol, period_end_date DESC);
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(query))
            conn.commit()
            print("EPS estimate table and Index created successfully.")
    except Exception as e:
        print(f"Database Error: {e}")


def update_eps_estimate(data: pd.DataFrame):
    """
    Performs an idempotent bulk upsert of forward-looking EPS estimates into the database.

    This function cleans and uploads raw analyst estimate data. Crucially, it pre-emptively
    deduplicates the Pandas DataFrame using the 3-part composite key (estimate_date,
    symbol, period_end_date) to prevent in-batch SQL transaction failures. It then
    utilizes a temporary staging table to execute a PostgreSQL 'INSERT ... ON CONFLICT
    DO UPDATE' command, ensuring the estimate history is updated cleanly and accurately.

    Args:
        data (pd.DataFrame): The DataFrame containing 'estimate_date', 'symbol', 'period',
                             'period_end_date', 'consensus_eps', and related estimate metrics.

    Returns:
        None: Executes database commands directly. Prints a success or error message.
    """

    clean_data = data.drop_duplicates(
        subset=["estimate_date", "symbol", "period_end_date"], keep="last"
    )
    temp_table = "temp_eps_estimate"
    clean_data.to_sql(
        temp_table, engine, schema="systematic_equity", if_exists="replace", index=False
    )
    query = """
    INSERT INTO systematic_equity.eps_estimate (
        estimate_date, symbol, period, period_end_date, consensus_eps, recent_eps,
        estimate_count, estimate_high, estimate_low, year_ago_eps)
    SELECT
        estimate_date, symbol, period, period_end_date, consensus_eps, recent_eps,
        estimate_count, estimate_high, estimate_low, year_ago_eps
    FROM systematic_equity.temp_eps_estimate
    ON CONFLICT (estimate_date, symbol, period_end_date)
    DO UPDATE SET
        consensus_eps = EXCLUDED.consensus_eps,
        recent_eps = EXCLUDED.recent_eps,
        estimate_count = EXCLUDED.estimate_count,
        estimate_high = EXCLUDED.estimate_high,
        estimate_low = EXCLUDED.estimate_low,
        year_ago_eps = EXCLUDED.year_ago_eps;
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
            conn.execute(text(f"DROP TABLE systematic_equity.{temp_table};"))
        print("EPS estimate table updated successfully.")
    except Exception as e:
        print(f"Database Error: {e}")
