import sqlite3

from config import DB_PATH

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            language TEXT,
            fatsecret_token TEXT,
            fatsecret_token_secret TEXT,
            fatsecret_connected_at TEXT
        )
        """
        )

