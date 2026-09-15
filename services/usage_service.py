from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from config import DAILY_MEAL_ATTEMPT_LIMIT, DAILY_USAGE_UTC_OFFSET_HOURS
from repositories.user_repository import consume_daily_attempt


@dataclass(frozen=True)
class UsageResult:
    allowed: bool
    is_premium: bool
    remaining: int | None


def consume_meal_attempt(telegram_id: int, *, usage_date: date | None = None) -> UsageResult:
    usage_timezone = timezone(timedelta(hours=DAILY_USAGE_UTC_OFFSET_HOURS))
    current_date = usage_date or datetime.now(usage_timezone).date()
    allowed, is_premium, remaining = consume_daily_attempt(
        telegram_id,
        current_date.isoformat(),
        DAILY_MEAL_ATTEMPT_LIMIT,
    )
    return UsageResult(allowed, is_premium, remaining)
