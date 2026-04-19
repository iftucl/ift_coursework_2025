import numpy as np
import pandas as pd
import datetime
import yaml
from pymongo import MongoClient
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


_mongo_client = None


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["mongodb"]


def get_collection(collection_name: str = None):
    global _mongo_client
    config = load_config()
    if _mongo_client is None:
        url = f"mongodb://{config['host']}:{config['port']}/"
        _mongo_client = MongoClient(url)
    db = _mongo_client[config["dbname"]]
    target_collection = collection_name if collection_name else config["collection"]
    return db[target_collection]


def save_trade_log(portfolio_date: str, trades_list: list, collection_name: str = None):
    date_obj = pd.to_datetime(portfolio_date)
    document = {
        "portfolio_date": portfolio_date,
        "year": int(date_obj.year),
        "month": int(date_obj.month),
        "timestamp": datetime.datetime.now(),
        "status": "PENDING",
        "trades": trades_list,
    }
    collection = get_collection(collection_name)
    result = collection.insert_one(document)
    print(f"[{collection.name}] stored trading log. ID: {result.inserted_id}")


def get_pending(collection_name: str = None):
    collection = get_collection(collection_name)
    work_to_do = collection.find_one({"status": "PENDING"})
    if work_to_do:
        return work_to_do
    else:
        print("No pending data found")
        return None


def check_pending(collection_name: str = None):
    collection = get_collection(collection_name)
    pending_count = collection.count_documents({"status": "PENDING"})
    print(f"Pending trade count: {pending_count}")


def update_trade_log(trade_info: dict, collection_name: str = None):
    collection = get_collection(collection_name)
    collection.replace_one({"_id": trade_info["_id"]}, trade_info)


def reset_mongodb():
    config = load_config()
    url = f"mongodb://{config['host']}:{config['port']}/"
    client = MongoClient(url)

    db_name = config["dbname"]

    print(f"Dropping MongoDB database: {db_name}...")
    client.drop_database(db_name)
    print("MongoDB reset complete.")
