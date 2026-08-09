import os
from dotenv import load_dotenv

load_dotenv()

from datetime import datetime, timezone

from clients.fatsecret_client import create_authorization
from clients.fatsecret_client import exchange_verifier

from repositories.user_repository import save_fatsecret_credentials

FATSECRET_CONSUMER_KEY = os.getenv("FATSECRET_CONSUMER_KEY")
FATSECRET_CONSUMER_SECRET = os.getenv("FATSECRET_CONSUMER_SECRET")

def start_authorization() -> tuple[str, str, str]:
    auth_data = create_authorization(FATSECRET_CONSUMER_KEY, FATSECRET_CONSUMER_SECRET)
    return auth_data

def complete_authorization(
    telegram_id: int,
    request_token: str,
    request_token_secret: str,
    verifier: str,
) -> None:
    user_token, user_token_secret = exchange_verifier(
        FATSECRET_CONSUMER_KEY, 
        FATSECRET_CONSUMER_SECRET, 
        request_token, 
        request_token_secret, 
        verifier
    )

    save_fatsecret_credentials(
        telegram_id, 
        user_token, 
        user_token_secret, 
        datetime.now(timezone.utc).isoformat()
    )
