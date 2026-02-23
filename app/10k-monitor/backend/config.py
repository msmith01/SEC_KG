from pathlib import Path

# SEC project root (4 levels up: backend/ → 10k-monitor/ → app/ → SEC/)
SEC_ROOT = Path(__file__).resolve().parent.parent.parent.parent

PREPROCESSED_DIR = SEC_ROOT / "python" / "data" / "preprocessed"
RISK_FACTORS_DIR = PREPROCESSED_DIR / "risk_factors"

# SQLite index lives inside the backend/data/ directory
DB_PATH = Path(__file__).resolve().parent / "data" / "monitor.db"

CORS_ORIGINS = ["http://localhost:3000"]

# How many companies to return by default on the dashboard
DEFAULT_COMPANY_LIMIT = 300
