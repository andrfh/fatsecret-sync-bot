from dataclasses import dataclass

@dataclass
class User:
    telegram_id: int
    language: str | None = None
    fatsecret_token: str | None = None
    fatsecret_token_secret: str | None = None
    fatsecret_connected_at: str | None = None
