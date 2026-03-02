import subprocess
import pandas as pd
import io
import os
from pathlib import Path
from modules.db_loader import postgres

def update_earnings_data(repo_path):
    subprocess.run(["dolt", "pull"], cwd=repo_path)
    
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

    rename_map = {
        'act_symbol': 'symbol',          #
        'period_end_date': 'period_end_date',       
        'reported': 'reported_eps',    
        'estimate': 'estimate_eps'
    }
    new_data = new_data.rename(columns=rename_map)
    new_data['period_end_date'] = pd.to_datetime(new_data['period_end_date'])
    
    postgres.update_eps_history(new_data)

def setup_dolt_database():
    print("Configuring Dolt identity for automated pipeline...")
    subprocess.run(["dolt", "config", "--global", "--add", "user.email", "quant_pipeline@example.com"])
    subprocess.run(["dolt", "config", "--global", "--add", "user.name", "Quant Worker"])

    # Get the absolute path of the folder containing THIS specific file (url_parser)
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parents[2]
    data_dir = project_root / 'data' / 'earnings'
    
    data_dir_str = str(data_dir)
    
    # Check if the database already exists
    if os.path.exists(os.path.join(data_dir_str, '.dolt')):
        print(f"Dolt database found at {data_dir_str}. Running 'dolt pull' ...")
        postgres.create_eps_history_table()
        update_earnings_data(data_dir_str)
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
    update_earnings_data(data_dir_str)


    