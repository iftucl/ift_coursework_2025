import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy import text

engine = create_engine("postgresql+psycopg://postgres:postgres@postgres_db_cw:5432/fift")

# Get data with specific table name and columns
def get_table(name: str, columns: list = None, schema: str = 'systematic_equity'):
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

# Get the dataset with the latest date for each company in a specific table
def get_latest_data(table_name: str, columns: list = None, symbols: list = None, periods: list = None, date_col: str = 'price_date', distinct_cols: list = None, schema: str = 'systematic_equity'):
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

    if where_clauses:
        query += "\nWHERE " + " AND ".join(where_clauses)

    order_by_prefix = ", ".join([f'"{col}" ASC' for col in distinct_cols])
    query += f"\nORDER BY {order_by_prefix}, \"{date_col}\" DESC;"
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

# Get the dataset for specific symbol within a table    
def get_symbol_data(symbol_name: str, table_name: str, schema: str = 'systematic_equity'):
    query = f"""
        SELECT *
        FROM "{schema}"."{table_name}"
        WHERE symbol = :symbol
        ORDER BY price_date ASC;
    """
    
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params={"symbol": symbol_name})
        if df.empty:
            print(f"Warning: The table '{table_name}' is empty.")
            return pd.DataFrame()  
        df['price_date'] = pd.to_datetime(df['price_date'])
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None

# Get the latest data date for a specific table
def get_latest_date(table_name: str, schema: str = 'systematic_equity'):
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

# Adding a new column to existing table 
def add_new_column(df: pd.DataFrame, column_name: str, column_type: str, table_name: str, schema: str = 'systematic_equity'):
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


    temp_table = f"temp_{table_name}_update"
    if table_name == "eps_history":
        upload_df = df[['symbol', 'period_end_date', column_name]]
    else:
        upload_df = df[['symbol', 'price_date', column_name]]
    
    try:
        upload_df.to_sql(temp_table, engine, schema=schema, if_exists='replace', index=False)
        
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

def del_table(table_name: str, schema: str = 'systematic_equity'):
    query = f"""
    DROP TABLE IF EXISTS "{schema}"."{table_name}";
    """
    
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
        print(f"Successfully permanently deleted table: '{schema}.{table_name}'")
    except Exception as e:
        print(f"Database Error: {e}")

def del_column(column_name: str, table_name: str, schema: str = 'systematic_equity'):
    query = f"""
    ALTER TABLE "{schema}"."{table_name}" 
    DROP COLUMN IF EXISTS "{column_name}";
    """
    
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
        print(f"Successfully deleted column '{column_name}' from '{schema}.{table_name}'.")
    except Exception as e:
        print(f"Database Error: {e}")
    
# Get the whole company_static table
def get_company_static():
    query = """
    SELECT * 
    FROM systematic_equity.company_static
    """
    try:
        df = pd.read_sql(text(query), engine)
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None

# Get companies within a specific sector
def get_companies_by_sector(sector_list: list):
    query = """
    SELECT * 
    FROM systematic_equity.company_static
    WHERE gics_sector = ANY(:sectors);
    """
    try:
        params = {"sectors": list(sector_list)}
        df = pd.read_sql(text(query), engine, params = params)
        if df is not None and not df.empty and 'symbol' in df.columns:
            df['symbol'] = df['symbol'].str.strip()
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None

# Get companies within a specific industry    
def get_companies_by_industry(industry_list: list):
    query = """
    SELECT * 
    FROM systematic_equity.company_static
    WHERE gics_industry = ANY(:industries);
    """
    try:
        params = {"industries": list(industry_list)}
        df = pd.read_sql(text(query), engine, params = params)
        if df is not None and not df.empty and 'symbol' in df.columns:
            df['symbol'] = df['symbol'].str.strip()
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None

# Check the sectors included in company_static table    
def get_all_sectors():
    query = """
    SELECT DISTINCT gics_sector
    FROM systematic_equity.company_static
    ORDER BY gics_sector ASC;
    """
    try:
        df = pd.read_sql(text(query), engine)
        return df['gics_sector'].tolist()
    except Exception as e:
        print(f"Database Error: {e}")
        return []

# Check the industries included in company_static table    
def get_all_industries():
    query = """
    SELECT DISTINCT gics_industry
    FROM systematic_equity.company_static
    ORDER BY gics_industry ASC;
    """
    try:
        df = pd.read_sql(text(query), engine)
        return df['gics_industry'].tolist()
    except Exception as e:
        print(f"Database Error: {e}")
        return []

# Creat daily_ohlcv table if there isn't one
def create_ohlcv_table():
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

# Update data to daily_ohlcv table
# If there's data with same symbol and price_date it will update to the new data
def update_ohlcv_data(data: pd.DataFrame):
    temp_table = 'temp_ohlcv'
    data.to_sql(temp_table, engine, schema='systematic_equity', if_exists='replace', index=False)
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

# Get OHLCV data for a specific companies list from a target date
def get_ohlcv_data(company_list: list, start_date=None):
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
        df = pd.read_sql(text(query), engine, params = params)
        df['price_date'] = pd.to_datetime(df['price_date'])
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None

# Get price_date and close_price for a specific company
def get_close_price(symbol: str):
    query = """
    SELECT price_date, close_price
    FROM systematic_equity.daily_ohlcv
    WHERE symbol = :symbol
    ORDER BY price_date ASC;
    """
    try:
        params = {"symbol": symbol}
        df = pd.read_sql(text(query), engine, params = params)
        df['price_date'] = pd.to_datetime(df['price_date'])
        return df
    except Exception as e:
        print(f"Database Error: {e}")
        return None 
    
# Create liquidity_factors table if there isn't one
def create_liquidity_table():
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

# Update new data to liquidity_factors table
def update_liquidity_data(data: pd.DataFrame):
    temp_table = 'temp_liquidity'
    data.to_sql(temp_table, engine, schema='systematic_equity', if_exists='replace', index=False)
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

# Create trend_factors table if there isn't one
def create_trend_table():
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

# Update new data to trend_factors table
def update_trend_data(data: pd.DataFrame):
    temp_table = 'temp_trend'
    data.to_sql(temp_table, engine, schema='systematic_equity', if_exists='replace', index=False)
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

# Create momentum_factors table if there isn't one
def create_momentum_table():
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

# Update new data to momentum_factors table
def update_momentum_data(data: pd.DataFrame):
    temp_table = 'temp_momentum'
    data.to_sql(temp_table, engine, schema='systematic_equity', if_exists='replace', index=False)
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

# Create risk_factors table if there isn't one
def create_risk_table():
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

# Update new data to risk_factors table
def update_risk_data(data: pd.DataFrame):
    temp_table = 'temp_risk'
    data.to_sql(temp_table, engine, schema='systematic_equity', if_exists='replace', index=False)
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

# Create mean_reversion_factors table if there isn't one
def create_mean_reversion_table():
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

# Update new data to mean_reversion_factors table
def update_mean_reversion_data(data: pd.DataFrame):
    temp_table = 'temp_mean_reversion'
    data.to_sql(temp_table, engine, schema='systematic_equity', if_exists='replace', index=False)
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

# Create eps_history table if there isn't one
def create_eps_history_table():
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

# Update new data to eps_history table
def update_eps_history(data: pd.DataFrame):
    temp_table = 'temp_eps_history'
    data.to_sql(temp_table, engine, schema='systematic_equity', if_exists='replace', index=False)
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

# Update new data to eps_estimate table
def update_eps_estimate(data: pd.DataFrame):
    clean_data = data.drop_duplicates(
        subset=['estimate_date', 'symbol', 'period_end_date'], 
        keep='last'
    )
    temp_table = 'temp_eps_estimate'
    clean_data.to_sql(temp_table, engine, schema='systematic_equity', if_exists='replace', index=False)
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