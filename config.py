from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"

DAILY_MEAL_ATTEMPT_LIMIT = 5
DAILY_USAGE_UTC_OFFSET_HOURS = 3

DATA_DIR.mkdir(parents=True, exist_ok=True)
