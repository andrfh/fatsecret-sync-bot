import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ServerError

from models.Meal import MealRecognition
from promtps.Gemini_photo_recognized import create_photo_prompt
from promtps.Gemini_recognition_verify import create_verify_prompt
from promtps.Gemini_take_food import create_food_resolution_prompt

from services.fatsecret_food_service import fatsecret_food_search
from services.fatsecret_food_service import fatsecret_get_food

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

Gemini_model = "gemini-3.1-flash-lite"
_RETRYABLE_STATUS_CODES = {429, 500, 503}
_MAX_RETRIES = 3


def _is_retryable_server_error(error: Exception) -> bool:
    if not isinstance(error, ServerError):
        return False
    code = getattr(error, "code", None)
    if code is None:
        code = getattr(error, "status_code", None)
    return code in _RETRYABLE_STATUS_CODES


def _call_with_retry(func, *args, **kwargs):
    last_error = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except ServerError as error:
            last_error = error
            if not _is_retryable_server_error(error) or attempt == _MAX_RETRIES:
                raise
            delay = min(2 ** (attempt - 1), 8)
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Gemini request failed without an error")


def _generate_meal_recognition(prompt: str, image_bytes: bytes) -> MealRecognition:
    response = _call_with_retry(
        client.models.generate_content,
        model=Gemini_model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MealRecognition,
        ),
    )

    parsed = response.parsed

    if isinstance(parsed, MealRecognition):
        return parsed

    # Fall back to manual validation if the SDK did not populate `.parsed`
    # (e.g. the model was blocked or returned no candidate).
    if not response.text:
        raise ValueError("Gemini returned an empty meal recognition response")

    return MealRecognition.model_validate_json(response.text)


def recognize_image(image_bytes: bytes, description: str, meal_type: str) -> MealRecognition:
    return _generate_meal_recognition(create_photo_prompt(description), image_bytes)


def verify_recognition(image_bytes: bytes, recognition: dict) -> MealRecognition:
    return _generate_meal_recognition(create_verify_prompt(recognition), image_bytes)

def gemini_search_food(recognized_meal: dict, language: str):
    interaction = client.models.generate_content(
        model=Gemini_model,
        contents=create_food_resolution_prompt(recognized_meal, language),
        config=types.GenerateContentConfig(
            tools=[
                fatsecret_food_search,
                fatsecret_get_food,
            ],
        ),
    )
    return interaction.text