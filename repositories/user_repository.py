import sqlite3
from config import DB_PATH

from models.User import User

def create_user(telegram_id: int) -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            """
            INSERT OR IGNORE INTO users (telegram_id)
            VALUES (?)
            """,
            (telegram_id,)
        )
        connection.commit()
    finally:
        connection.close()

def get_user(telegram_id: int) -> User | None:
    connection = sqlite3.connect(DB_PATH)
    try:
        cursor = connection.execute(
            """
            SELECT telegram_id, language, fatsecret_token, fatsecret_token_secret,
                   fatsecret_connected_at, is_premium, daily_usage_count, daily_usage_date
            FROM users
            WHERE telegram_id = ?
            """,
        (telegram_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        values = list(row)
        values[5] = bool(values[5])
        return User(*values)
    finally:
        connection.close()

def update_language(telegram_id: int, language: str) -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        cursor = connection.execute(
            """
            UPDATE users
            SET language = ?
            WHERE telegram_id = ?
            """,
        (language, telegram_id,),
        )
        connection.commit()
    finally:
        connection.close()

def save_fatsecret_credentials(
    telegram_id: int,
    token: str,
    token_secret: str,
    connected_at: str,
) -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        cursor = connection.execute(
            """
            UPDATE users
            SET fatsecret_token = ?,
                fatsecret_token_secret = ?,
                fatsecret_connected_at = ?
            WHERE telegram_id = ?
            """,
        (token, token_secret, connected_at, telegram_id,),
        )
        connection.commit()
    finally:
        connection.close()

def remove_fatsecret_tokens(telegram_id: int) -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        cursor = connection.execute(
            """
            UPDATE users
            SET fatsecret_token = NULL,
                fatsecret_token_secret = NULL,
                fatsecret_connected_at = NULL
            WHERE telegram_id = ?   
            """,
        (telegram_id,),
        )
        connection.commit()
    finally:
        connection.close()


def consume_daily_attempt(telegram_id: int, usage_date: str, limit: int) -> tuple[bool, bool, int | None]:
    """Atomically consume one daily attempt and return allowed, premium, remaining."""
    connection = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT is_premium, daily_usage_count, daily_usage_date
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"User {telegram_id} not found")

        is_premium = bool(row[0])
        if is_premium:
            connection.commit()
            return True, True, None

        count = row[1] if row[2] == usage_date else 0
        if count >= limit:
            connection.commit()
            return False, False, 0

        count += 1
        connection.execute(
            """
            UPDATE users
            SET daily_usage_count = ?, daily_usage_date = ?
            WHERE telegram_id = ?
            """,
            (count, usage_date, telegram_id),
        )
        connection.commit()
        return True, False, limit - count
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
