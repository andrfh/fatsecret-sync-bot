from google import genai
from google.genai import types

import os
from dotenv import load_dotenv

import base64

from promtps.Gemini_photo_recognized import create_photo_prompt
from promtps.Gemini_take_food import create_food_resolution_prompt

from services.fatsecret_food_service import fatsecret_food_search
from services.fatsecret_food_service import fatsecret_get_food

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Limit built-in retries; gemini_service manages stage retries and progress.
# In this SDK, Models treats 1 as one attempt, while Interactions permits
# one additional internal retry. The service budget counts SDK calls.
client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(
    retry_options=types.HttpRetryOptions(attempts=1),
))

Gemini_model = "gemini-3.1-flash-lite"

def recognize_image(image_bytes: bytes | None, description: str, meal_type: str) -> str:
    if not image_bytes and not description.strip():
        raise ValueError("A meal photo or description is required")

    input_parts = []
    if image_bytes:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        input_parts.append({
            "type": "image",
            "data": encoded,
            "mime_type": "image/jpeg",
        })
    input_parts.append({
        "type": "text",
        "text": create_photo_prompt(description, has_image=bool(image_bytes)),
    })

    interaction = client.interactions.create(
        model=Gemini_model,
        input=input_parts,
    )

    return interaction.output_text

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
