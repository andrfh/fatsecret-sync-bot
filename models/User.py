from dataclasses import dataclass

@dataclass
class User:
    telegram_id: int
    language: str | None = None
    fatsecret_token: str | None = None
    fatsecret_token_secret: str | None = None
    fatsecret_connected_at: str | None = None
    is_premium: bool = False
    daily_usage_count: int = 0
    daily_usage_date: str | None = None
