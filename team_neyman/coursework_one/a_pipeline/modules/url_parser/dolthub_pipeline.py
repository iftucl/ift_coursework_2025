import subprocess
import pandas as pd
import io
import os
from pathlib import Path
from modules.db_loader import postgres

# Get eps_history data from dolthub and update to postgreSQL
def update_eps_history_data(repo_path):
    query = """
    SELECT *
    FROM eps_history 
    """

    result = subprocess.run(
        ["dolt", "sql", "-q", query, "-r", "csv"], 
        cwd=repo_path, 
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"Dolt SQL Error: {result.stderr}")
        
    if not result.stdout.strip():
        print("Warning: No data returned from Dolt.")
    
    new_data = pd.read_csv(io.StringIO(result.stdout))

    # Update data to postgreSQL
    rename_map = {
        'act_symbol': 'symbol',
        'period_end_date': 'period_end_date',       
        'reported': 'reported_eps',    
        'estimate': 'estimate_eps'
    }
    new_data = new_data.rename(columns=rename_map)
    new_data['period_end_date'] = pd.to_datetime(new_data['period_end_date'])
    
    postgres.update_eps_history(new_data)

def update_eps_estimate_data(repo_path):
    query = """
    SELECT *
    FROM eps_estimate 
    """

    result = subprocess.run(
        ["dolt", "sql", "-q", query, "-r", "csv"], 
        cwd=repo_path, 
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"Dolt SQL Error: {result.stderr}")
        
    if not result.stdout.strip():
        print("Warning: No data returned from Dolt.")
    
    new_data = pd.read_csv(io.StringIO(result.stdout))

    # Update data to postgreSQL
    rename_map = {
        'date': 'estimate_date',
        'act_symbol': 'symbol',
        'period': 'period',
        'period_end_date': 'period_end_date',       
        'consensus': 'consensus_eps',    
        'recent': 'recent_eps',
        'count': 'estimate_count',
        'high': 'estimate_high',
        'low': 'estimate_low',
        'year_ago': 'year_ago_eps'
    }
    new_data = new_data.rename(columns=rename_map)
    new_data['estimate_date'] = pd.to_datetime(new_data['estimate_date'])
    new_data['period_end_date'] = pd.to_datetime(new_data['period_end_date'])
    
    postgres.update_eps_estimate(new_data)

# Initiate dolthub
def setup_dolt_database():
    # Providing identity to dolthub for fetching data
    print("Configuring Dolt identity for automated pipeline...")
    subprocess.run(["dolt", "config", "--global", "--add", "user.email", "quant_pipeline@example.com"])
    subprocess.run(["dolt", "config", "--global", "--add", "user.name", "Quant Worker"])

    # Get the absolute path of the folder containing THIS specific file (url_parser)
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parents[2]
    data_dir = project_root / 'data' / 'earnings'
    
    #data_dir_str = str(data_dir)
    
    # Check if the database already exists
    if os.path.exists(os.path.join(data_dir, '.dolt')):
        print(f"Dolt database found at {data_dir}. Running 'dolt pull' ...")
        # Get new data from dolthub
        subprocess.run(["dolt", "pull"], cwd=data_dir)
        postgres.create_eps_history_table()
        update_eps_history_data(data_dir)
        postgres.create_eps_estimate_table()
        update_eps_estimate_data(data_dir)
        return

    # If it doesn't exist, create the folder and clone it
    print("Initializing Dolt database for the first time. This may take a minute...")
    os.makedirs(data_dir, exist_ok=True)
    
    subprocess.run(
        ["dolt", "clone", "post-no-preference/earnings", "."], 
        cwd=data_dir
    )
    print("Dolt database successfully cloned to /data/earnings!")

    postgres.create_eps_history_table()
    update_eps_history_data(data_dir)
    postgres.create_eps_estimate_table()
    update_eps_estimate_data(data_dir)


    