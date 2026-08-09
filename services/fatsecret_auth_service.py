import os
from dotenv import load_dotenv

load_dotenv()

from clients.fatsecret_client import create_authorization
from clients.fatsecret_client import exchange_verifier

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
) -> tuple[str, str]:
    user_tokens = exchange_verifier(
        FATSECRET_CONSUMER_KEY, 
        FATSECRET_CONSUMER_SECRET, 
        request_token, 
        request_token_secret, 
        verifier
    )
    return user_tokens
