import os
from dotenv import load_dotenv

load_dotenv()

from clients.fatsecret_client import create_authorization

def start_authorization() -> tuple[str, str, str]:
    auth_data = create_authorization(os.getenv("FATSECRET_CONSUMER_KEY"), os.getenv("FATSECRET_CONSUMER_SECRET"))
    return auth_data

def complete_authorization(
    telegram_id: int,
    request_token: str,
    request_token_secret: str,
    verifier: str,
) -> None:
    ...

print(start_authorization())