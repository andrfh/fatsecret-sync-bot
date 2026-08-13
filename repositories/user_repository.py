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