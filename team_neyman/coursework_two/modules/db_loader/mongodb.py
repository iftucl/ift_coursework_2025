import numpy as np
import pandas as pd
import datetime
import yaml
from pymongo import MongoClient
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["mongodb"]


def get_collection():
    config = load_config()
    url = f"mongodb://{config["host"]}:{config["port"]}/"
    client = MongoClient(url)
    db = client[config["dbname"]]
    collection = db[config["collection"]]
    return collection


def save_trade_log(portfolio_date: str, trades_list: list):
    date_obj = pd.to_datetime(portfolio_date)
    document = {
        "portfolio_date": portfolio_date,
        "year": int(date_obj.year),
        "month": int(date_obj.month),
        "timestamp": datetime.datetime.now(),
        "status": "PENDING",
        "trades": trades_list,
    }
    collection = get_collection()
    result = collection.insert_one(document)
    print(f"Stored rebalance event. ID: {result.inserted_id}")


def get_pending():
    collection = get_collection()
    work_to_do = collection.find_one({"status": "PENDING"})
    if work_to_do:
        return work_to_do
    else:
        print("No pending data found")
        return None


def check_pending():
    collection = get_collection()
    pending_count = collection.count_documents({"status": "PENDING"})
    print(f"Pending trade count: {pending_count}")


def update_trade_log(trade_info: dict):
    collection = get_collection()
    collection.replace_one({"_id": trade_info["_id"]}, trade_info)
