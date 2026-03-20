import sys
from pathlib import Path

# Add a_pipeline root to sys.path so tests can import from modules/
sys.path.insert(0, str(Path(__file__).parent))
