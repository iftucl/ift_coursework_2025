import datetime
from pathlib import Path

import pandas as pd
import yaml
from pymongo import MongoClient

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


_mongo_client = None


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["mongodb"]


def get_collection(collection_name: str = None):
    """
    Retrieves a MongoDB collection using a singleton client pattern.

    Initializes the persistent connection if inactive and resolves the target collection
    based on provided arguments or central configuration.

    Args:
        collection_name (str, optional): Target collection identifier. Defaults to config.

    Returns:
        Collection: A PyMongo collection instance.
    """

    global _mongo_client
    config = load_config()
    if _mongo_client is None:
        url = f"mongodb://{config['host']}:{config['port']}/"
        _mongo_client = MongoClient(url)
    db = _mongo_client[config["dbname"]]
    target_collection = collection_name if collection_name else config["collection"]
    return db[target_collection]


def save_trade_log(
    portfolio_date: str, capital: float, trades_list: list, collection_name: str = None
):
    """
    Archives a daily trading log and portfolio snapshot to MongoDB.

    Stores a structured document containing rebalance metadata, capital levels, and the detailed trade list. It extracts the year and month for optimized querying and initializes the record with a 'PENDING' status for downstream verification.

    Args:
        portfolio_date (str): The logical date for the trade log (YYYY-MM-DD).
        capital (float): Total net capital at the time of log generation.
        trades_list (list): List of dictionaries representing individual trade orders.
        collection_name (str, optional): Target MongoDB collection.

    Returns:
        None: Inserts record and prints the unique MongoDB ObjectId.
    """

    date_obj = pd.to_datetime(portfolio_date)
    document = {
        "portfolio_date": portfolio_date,
        "year": int(date_obj.year),
        "month": int(date_obj.month),
        "timestamp": datetime.datetime.now(),
        "status": "PENDING",
        "capital": capital,
        "trades": trades_list,
    }
    collection = get_collection(collection_name)
    result = collection.insert_one(document)
    print(f"[{collection.name}] stored trading log. ID: {result.inserted_id}")


def get_pending(collection_name: str = None):
    """
    Retrieves the next trade log awaiting execution from the MongoDB queue.

    Queries the collection for a single document with a 'PENDING' status. This serves as the primary data trigger for the order execution engine or downstream processing logic.

    Args:
        collection_name (str, optional): Target MongoDB collection identifier.

    Returns:
        dict: The first pending trade document found, or None if the queue is empty.
    """

    collection = get_collection(collection_name)
    work_to_do = collection.find_one({"status": "PENDING"})
    if work_to_do:
        return work_to_do
    else:
        print("No pending data found")
        return None


def check_pending(collection_name: str = None):
    """
    Monitors the volume of unexecuted trade logs in the MongoDB queue.

    Provides a real-time count of documents with a 'PENDING' status, serving as a health check for the trade execution pipeline.

    Args:
        collection_name (str, optional): Target MongoDB collection identifier.

    Returns:
        None: Prints the current pending count to the console.
    """

    collection = get_collection(collection_name)
    pending_count = collection.count_documents({"status": "PENDING"})
    print(f"Pending trade count: {pending_count}")


def update_trade_log(trade_info: dict, collection_name: str = None):
    """
    Updates a specific trade log document in MongoDB via full replacement.

    Matches the record by its unique '_id' and overwrites it with the provided dictionary. Commonly used to transition log statuses from 'PENDING' to 'EXECUTED'.

    Args:
        trade_info (dict): The updated document containing the original '_id'.
        collection_name (str, optional): Target MongoDB collection.

    Returns:
        None: Confirms completion via console output.
    """

    collection = get_collection(collection_name)
    collection.replace_one({"_id": trade_info["_id"]}, trade_info)
    print("Trading complete!")


def get_sector_weights(year: str, month: str, collection_name: str):
    """
    Calculates the portfolio's sector allocation for the final record of a given month.

    Uses a regex pattern to find all logs within a specific 'YYYY-MM' range, retrieves the most recent entry, and aggregates the total weighting per GICS sector.

    Args:
        year (str): Target year (YYYY).
        month (str): Target month (M or MM).
        collection_name (str): The MongoDB collection to query.

    Returns:
        pd.Series: Sector names indexed to their total percentage weights, sorted descending.
    """

    collection = get_collection(collection_name)
    date_pattern = f"^{year}-{month.zfill(2)}"
    cursor = (
        collection.find({"portfolio_date": {"$regex": date_pattern}})
        .sort("portfolio_date", -1)
        .limit(1)
    )
    latest_portfolio = next(cursor, None)

    if not latest_portfolio:
        print(f"No portfolio data found for {year}-{month}")
        return pd.Series(dtype=float)

    trades_df = pd.DataFrame(latest_portfolio["trades"])

    if trades_df.empty or "gics_sector" not in trades_df.columns:
        return pd.Series(dtype=float)

    sector_weights = trades_df.groupby("gics_sector")["weight"].sum()
    sector_weights = sector_weights.sort_values(ascending=False)

    return sector_weights


def get_initial_date(collection_name: str):
    """
    Retrieves the earliest recorded portfolio date from a MongoDB collection.

    Queries the collection using field projection for performance, sorts chronologically
    by 'portfolio_date', and returns the first available timestamp.

    Args:
        collection_name (str): The MongoDB collection to query.

    Returns:
        str: The earliest 'YYYY-MM-DD' date string, or None if the collection is empty.
    """

    collection = get_collection(collection_name)
    result = (
        collection.find({}, {"portfolio_date": 1, "_id": 0})
        .sort("portfolio_date", 1)
        .limit(1)
    )
    doc = next(result, None)
    return doc["portfolio_date"] if doc else None


def get_latest_date(collection_name: str):
    """
    Retrieves the most recent portfolio date recorded in a MongoDB collection.

    Efficiently identifies the terminal date of a backtest or production log by
    sorting documents in descending chronological order.

    Args:
        collection_name (str): The MongoDB collection to query.

    Returns:
        str: The latest 'YYYY-MM-DD' date string, or None if the collection is empty.
    """

    collection = get_collection(collection_name)
    result = (
        collection.find({}, {"portfolio_date": 1, "_id": 0})
        .sort("portfolio_date", -1)
        .limit(1)
    )
    doc = next(result, None)
    return doc["portfolio_date"] if doc else None


def del_collection(collection_name: str):
    """
    Surgically removes a specific collection from the MongoDB database.

    Checks the database for existence before dropping the collection to prevent
    unhandled exceptions and ensure a clean state.

    Args:
        collection_name (str): The name of the collection to be deleted.

    Returns:
        None
    """

    try:
        config = load_config()
        url = f"mongodb://{config['host']}:{config['port']}/"
        client = MongoClient(url)
        db = client[config["dbname"]]

        if collection_name in db.list_collection_names():
            db.drop_collection(collection_name)
            print(f"Collection '{collection_name}' successfully deleted.")
        else:
            print(f"Warning: Collection '{collection_name}' does not exist.")

        client.close()
    except Exception as e:
        print(f"Error deleting collection: {e}")


def reset_mongodb():
    """
    Drops the MongoDB database defined in the local configuration.

    Permanently removes all collections and data within the specified database.
    Used to wipe trade logs and clear state for new simulation cycles.

    Returns:
        None: Completion status is printed to the console.
    """

    config = load_config()
    url = f"mongodb://{config['host']}:{config['port']}/"
    client = MongoClient(url)

    db_name = config["dbname"]

    print(f"Dropping MongoDB database: {db_name}...")
    client.drop_database(db_name)
    print("MongoDB reset complete.")
