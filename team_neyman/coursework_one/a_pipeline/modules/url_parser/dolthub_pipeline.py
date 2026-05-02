import io
import os
import subprocess
from pathlib import Path

import pandas as pd

from a_pipeline.modules.db_loader import postgres


def update_eps_history_data(repo_path):
    """
    Extracts historical EPS data from Dolt and synchronizes it with PostgreSQL.

    Args:
        repo_path (Path): Absolute path to the local Dolt repository.

    Returns:
        None: Updates the 'systematic_equity.eps_history' table in-place.

    Note:
        Renames 'act_symbol' to 'symbol' and 'reported' to 'reported_eps'
        to match the systematic equity database schema.
    """

    query = """
    SELECT *
    FROM eps_history
    """

    result = subprocess.run(
        ["dolt", "sql", "-q", query, "-r", "csv"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Dolt SQL Error: {result.stderr}")

    if not result.stdout.strip():
        print("Warning: No data returned from Dolt.")

    new_data = pd.read_csv(io.StringIO(result.stdout))

    # Update data to postgreSQL
    rename_map = {
        "act_symbol": "symbol",
        "period_end_date": "period_end_date",
        "reported": "reported_eps",
        "estimate": "estimate_eps",
    }
    new_data = new_data.rename(columns=rename_map)
    new_data["period_end_date"] = pd.to_datetime(new_data["period_end_date"])

    postgres.update_eps_history(new_data)


def update_eps_estimate_data(repo_path):
    """
    Fetches analyst EPS estimates from Dolt and synchronizes them with PostgreSQL.

    Args:
        repo_path (Path): Absolute path to the local Dolt repository.

    Returns:
        None: Executes a bulk upsert to the 'systematic_equity.eps_estimate' table.

    Note:
        Performs a 10-column mapping and converts both 'estimate_date'
        and 'period_end_date' to datetime objects for point-in-time analysis.
    """

    query = """
    SELECT *
    FROM eps_estimate
    """

    result = subprocess.run(
        ["dolt", "sql", "-q", query, "-r", "csv"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Dolt SQL Error: {result.stderr}")

    if not result.stdout.strip():
        print("Warning: No data returned from Dolt.")

    new_data = pd.read_csv(io.StringIO(result.stdout))

    # Update data to postgreSQL
    rename_map = {
        "date": "estimate_date",
        "act_symbol": "symbol",
        "period": "period",
        "period_end_date": "period_end_date",
        "consensus": "consensus_eps",
        "recent": "recent_eps",
        "count": "estimate_count",
        "high": "estimate_high",
        "low": "estimate_low",
        "year_ago": "year_ago_eps",
    }
    new_data = new_data.rename(columns=rename_map)
    new_data["estimate_date"] = pd.to_datetime(new_data["estimate_date"])
    new_data["period_end_date"] = pd.to_datetime(new_data["period_end_date"])

    postgres.update_eps_estimate(new_data)


def rebuild_dolt_database():
    """
    Rebulid the EPS database.

    Args:
        None

    Returns:
        None: Update Dolt data to Postgres.

    Note:
        Used for rebuilding databese when Dolt data exists.
    """
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parents[2]
    data_dir = project_root / "data" / "earnings"
    postgres.create_eps_history_table()
    update_eps_history_data(data_dir)
    postgres.create_eps_estimate_table()
    update_eps_estimate_data(data_dir)


def setup_dolt_database():
    """
    Initializes the local Dolt environment and triggers the EPS ETL pipeline.

    Args:
        None

    Returns:
        None: Manages global Dolt configuration, repository cloning/pulling,
            and database table initialization.

    Note:
        Requires the 'dolt' CLI installed on the system path. Clones data
        into the 'data/earnings' directory relative to the project root.
    """
    # Providing identity to dolthub for fetching data
    print("Configuring Dolt identity for automated pipeline...")
    subprocess.run(
        [
            "dolt",
            "config",
            "--global",
            "--add",
            "user.email",
            "quant_pipeline@example.com",
        ]
    )
    subprocess.run(["dolt", "config", "--global", "--add", "user.name", "Quant Worker"])

    # Get the absolute path of the folder containing THIS specific file (url_parser)
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parents[2]
    data_dir = project_root / "data" / "earnings"

    # Check if the database already exists
    if os.path.exists(os.path.join(data_dir, ".dolt")):
        print(f"Dolt database found at {data_dir}. Running 'dolt pull' ...")
        # Get new data from dolthub
        result = subprocess.run(
            ["dolt", "pull"], cwd=data_dir, capture_output=True, text=True
        )
        if "Everything up-to-date" in result.stdout:
            print("No new data on DoltHub. Skipping database update.")
            return False
        print("New data found and pulled. Updating PostgreSQL tables...")
        postgres.create_eps_history_table()
        update_eps_history_data(data_dir)
        postgres.create_eps_estimate_table()
        update_eps_estimate_data(data_dir)
        return True

    # If it doesn't exist, create the folder and clone it
    print("Initializing Dolt database for the first time. This may take a minute...")
    os.makedirs(data_dir, exist_ok=True)

    subprocess.run(["dolt", "clone", "post-no-preference/earnings", "."], cwd=data_dir)
    print("Dolt database successfully cloned to /data/earnings!")

    postgres.create_eps_history_table()
    update_eps_history_data(data_dir)
    postgres.create_eps_estimate_table()
    update_eps_estimate_data(data_dir)
    return True
