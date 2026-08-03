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
            SELECT telegram_id, language, fatsecret_token, fatsecret_token_secret, fatsecret_connected_at
            FROM users
            WHERE telegram_id = ?
            """,
        (telegram_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return User(*row)
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
    