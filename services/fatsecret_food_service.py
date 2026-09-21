import os
import logging
import requests
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

from datetime import date

from clients.fatsecret_client import food_search
from clients.fatsecret_client import get_food
from clients.fatsecret_client import create_food_entry
from clients.fatsecret_client import FatSecretAPIError

logger = logging.getLogger(__name__)


def _as_items(value):
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


def _positive_id(value):
    return str(value) if str(value).isascii() and str(value).isdigit() and int(value) > 0 else None


@dataclass
class FoodToolAudit:
    """Successful FatSecret identifiers and safe errors for one Gemini call."""
    searched_food_ids: set[str] = field(default_factory=set)
    inspected_food_ids: set[str] = field(default_factory=set)
    servings_by_food: dict[str, set[str]] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    successful_empty_searches: int = 0

    @property
    def has_transient_error(self):
        return any(error["retryable"] for error in self.errors)

    def record_search(self, response):
        if "error" in response:
            self.errors.append(response["error"])
            return
        foods = response.get("foods", {}) if isinstance(response, dict) else {}
        items = _as_items(foods.get("food")) if isinstance(foods, dict) else []
        ids = {_positive_id(item.get("food_id")) for item in items}
        ids.discard(None)
        self.searched_food_ids.update(ids)
        if not ids:
            self.successful_empty_searches += 1

    def record_food(self, requested_food_id, response):
        if "error" in response:
            self.errors.append(response["error"])
            return
        food = response.get("food") if isinstance(response, dict) else None
        if not isinstance(food, dict):
            return
        requested = _positive_id(requested_food_id)
        returned = _positive_id(food.get("food_id"))
        if returned is None or requested is None or returned != requested:
            return
        food_id = returned
        self.inspected_food_ids.add(food_id)
        servings = food.get("servings", {})
        items = _as_items(servings.get("serving")) if isinstance(servings, dict) else []
        ids = {_positive_id(item.get("serving_id")) for item in items}
        ids.discard(None)
        self.servings_by_food.setdefault(food_id, set()).update(ids)

    def confirms(self, food_id, serving_id):
        food = _positive_id(food_id)
        serving = _positive_id(serving_id)
        return ((food in self.searched_food_ids or food in self.inspected_food_ids)
                and serving in self.servings_by_food.get(food, set()))


def _safe_tool_call(operation, *args):
    # The SDK serializes str(exception) into model context if a tool raises.
    # Successful responses (including empty searches) retain their original shape.
    try:
        return operation(*args)
    except Exception as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        status = status if type(status) is int and 100 <= status <= 599 else None
        retryable = isinstance(error, (requests.exceptions.Timeout,
                                      requests.exceptions.ConnectionError)) or status in (408, 429, 500, 502, 503, 504)
        code = error.code if isinstance(error, FatSecretAPIError) else None
        logger.warning("FatSecret tool failed type=%s status=%s code=%s",
                       type(error).__name__, status, code)
        return {"error": {"type": "temporarily_unavailable" if retryable else "request_failed",
                          "retryable": retryable, "http_status": status, "code": code}}

FATSECRET_CONSUMER_KEY = os.getenv("FATSECRET_CONSUMER_KEY")
FATSECRET_CONSUMER_SECRET = os.getenv("FATSECRET_CONSUMER_SECRET")

def fatsecret_food_search(query: str) -> dict:
    return _safe_tool_call(food_search, query, FATSECRET_CONSUMER_KEY, FATSECRET_CONSUMER_SECRET)

def fatsecret_get_food(food_id: int) -> dict:
    return _safe_tool_call(get_food, food_id, FATSECRET_CONSUMER_KEY, FATSECRET_CONSUMER_SECRET)

def fatsecret_create_entry(
        user_token: str,
        user_token_secret: str, 
        food_id: int | str,
        food_entry_name: str,
        serving_id: int | str,
        number_of_units: float,
        meal: str
    ) -> dict:

    epoch = date(1970, 1, 1)
    today = date.today()

    date_int = (today - epoch).days

    try:
        response = create_food_entry(
            consumer_key = FATSECRET_CONSUMER_KEY,
            consumer_secret = FATSECRET_CONSUMER_SECRET,
            user_token = user_token,
            user_token_secret = user_token_secret,
            food_id = food_id,
            food_entry_name = food_entry_name,
            serving_id = serving_id,
            number_of_units = number_of_units,
            meal = meal,
            date = date_int
        )
        return {"status": "success", "response": response}
    
    except FatSecretAPIError as error:
        # A structured FatSecret error is a confirmed rejection.
        logger.warning("FatSecret entry rejected type=%s code=%s",
                       type(error).__name__, error.code)
        return {"status": "error", "response": None}
    except Exception as error:
        # A transport or unexpected failure may happen after FatSecret accepted
        # the POST. Never retry it automatically: the result is ambiguous.
        status = getattr(getattr(error, "response", None), "status_code", None)
        status = status if type(status) is int and 100 <= status <= 599 else None
        logger.warning("FatSecret entry outcome uncertain type=%s status=%s",
                       type(error).__name__, status)
        return {"status": "uncertain", "response": None}

        


