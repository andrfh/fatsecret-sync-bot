import sqlite3
from contextlib import closing

from config import DB_PATH

def init_db() -> None:
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        cursor = connection.cursor()
        cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            language TEXT,
            fatsecret_token TEXT,
            fatsecret_token_secret TEXT,
            fatsecret_connected_at TEXT,
            is_premium INTEGER NOT NULL DEFAULT 0,
            daily_usage_count INTEGER NOT NULL DEFAULT 0,
            daily_usage_date TEXT
        )
        """
        )

        existing_columns = {
            row[1] for row in cursor.execute("PRAGMA table_info(users)")
        }
        migrations = {
            "is_premium": "ALTER TABLE users ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0",
            "daily_usage_count": "ALTER TABLE users ADD COLUMN daily_usage_count INTEGER NOT NULL DEFAULT 0",
            "daily_usage_date": "ALTER TABLE users ADD COLUMN daily_usage_date TEXT",
        }
        for column, statement in migrations.items():
            if column not in existing_columns:
                cursor.execute(statement)

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS meal_write_operations (
                operation_id TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                outcome TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_meal_write_operations_user
            ON meal_write_operations (telegram_id, state)
            """
        )

