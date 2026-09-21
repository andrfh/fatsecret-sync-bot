import asyncio
import json
import math
import logging
import random
import ssl
import httpx
import requests
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from google.genai.errors import APIError

from clients.gemini_client import gemini_search_food
from clients.gemini_client import recognize_image
from clients.gemini_client import new_matching_operation
from services.matching_operation import UnverifiedFoodSelection, MatchingBudgetExceeded


logger = logging.getLogger(__name__)


class GeminiTemporarilyUnavailable(Exception):
    """The read-only Gemini operation could not finish within the retry budget."""


class TransientMatchingRead(Exception):
    """Safe marker for a failed read; diary writes have not started."""


_TRANSIENT_NETWORK_ERRORS = (
    ssl.SSLError,
    TimeoutError,
    ConnectionError,
    httpx.TransportError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def _is_transient_gemini_error(error: Exception) -> bool:
    if isinstance(error, TransientMatchingRead):
        return True
    current = error
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, APIError):
            return current.code in (429, 503)
        if isinstance(current, _TRANSIENT_NETWORK_ERRORS):
            return True
        current = current.__cause__ or current.__context__
    return False


async def _request_with_retry(operation, *args, on_retry=None):
    for attempt in range(1, 4):
        try:
            return await asyncio.to_thread(operation, *args)
        except Exception as error:
            if not _is_transient_gemini_error(error):
                raise
            error_label = error.code if isinstance(error, APIError) else type(error).__name__
            if attempt == 3:
                logger.warning("Gemini %s still returned %s after 3 attempts",
                               operation.__name__, error_label)
                raise GeminiTemporarilyUnavailable() from error
            delay = 2 ** attempt + random.uniform(0, 1)
            response = getattr(error, "response", None)
            headers = getattr(response, "headers", {}) or {}
            try:
                retry_after = float(headers.get("Retry-After", 0))
            except (TypeError, ValueError):
                try:
                    retry_after = (parsedate_to_datetime(headers["Retry-After"])
                                   - datetime.now(timezone.utc)).total_seconds()
                except (KeyError, TypeError, ValueError, OverflowError):
                    retry_after = 0
            # Do not retry earlier than requested, or keep the chat waiting indefinitely.
            if retry_after > 60:
                raise GeminiTemporarilyUnavailable() from error
            if not math.isfinite(retry_after):
                retry_after = 0
            delay = max(delay, retry_after)
            logger.warning("Gemini %s returned %s; retry %s/3 in %.1fs",
                           operation.__name__, error_label, attempt + 1, delay)
            if on_retry is not None:
                await on_retry(attempt + 1, 3)
            await asyncio.sleep(delay)


def _parse_json_object(ai_response: str, response_name: str) -> dict:
    try:
        data = json.loads(ai_response)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"AI returned invalid JSON for {response_name}") from error

    if not isinstance(data, dict):
        raise ValueError(f"AI returned invalid data for {response_name}")

    return data


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_brand(value: object) -> bool:
    return value is None or _is_non_empty_string(value)


def _is_positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _is_positive_number(value: object) -> bool:
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and value > 0
    )


def _is_positive_id(value: object) -> bool:
    if _is_positive_integer(value):
        return True

    return isinstance(value, str) and value.isdigit() and int(value) > 0


async def recognize_meal(
    image_bytes: bytes | None,
    description: str,
    meal_type: str,
    *, on_retry=None,
) -> dict:
    allowed_statuses = {"ok", "not_food", "too_complex", "uncertain"}

    ai_response = await _request_with_retry(
        recognize_image,
        image_bytes,
        description,
        meal_type,
        on_retry=on_retry,
    )

    meal_data = _parse_json_object(ai_response, "meal recognition")
    status = meal_data.get("status")

    if status not in allowed_statuses:
        raise ValueError("AI returned an unsupported meal status")

    if status != "ok":
        return meal_data

    if not _is_non_empty_string(meal_data.get("meal_name")):
        raise ValueError("AI returned an invalid meal name")

    if "brand" not in meal_data or not _is_valid_brand(meal_data["brand"]):
        raise ValueError("AI returned an invalid meal brand")

    items = meal_data.get("items")

    if not isinstance(items, list) or not 1 <= len(items) <= 8:
        raise ValueError("AI returned an invalid meal items list")

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("AI returned an invalid meal item")

        if not _is_non_empty_string(item.get("name")):
            raise ValueError("AI returned an invalid meal item name")

        if "brand" not in item or not _is_valid_brand(item["brand"]):
            raise ValueError("AI returned an invalid meal item brand")

        if not _is_positive_integer(item.get("amount_g")):
            raise ValueError("AI returned an invalid meal item amount")

    return meal_data


async def search_food(recognized_meal: dict, language: str, *, on_retry=None) -> dict:
    operation = new_matching_operation()

    def match():
        ai_response = gemini_search_food(recognized_meal, language, operation)
        try:
            food_data = _parse_json_object(ai_response, "food resolution")
            return operation.resolve(food_data, recognized_meal)
        except MatchingBudgetExceeded:
            raise
        except (ValueError, KeyError):
            if operation.budget_exhausted:
                raise MatchingBudgetExceeded('Matching read budget exhausted') from None
            if operation.has_transient_error:
                raise TransientMatchingRead() from None
            raise UnverifiedFoodSelection('Could not verify food selection') from None

    try:
        return await _request_with_retry(match, on_retry=on_retry)
    finally:
        logger.info(
            "Matching completed gemini_calls=%s fatsecret_calls=%s tool_calls=%s retries=%s cache_hits=%s",
            operation.gemini_calls, operation.fatsecret_calls, operation.tool_calls,
            operation.retries, operation.cache_hits,
        )
