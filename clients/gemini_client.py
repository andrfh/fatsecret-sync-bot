from google import genai
from google.genai import types

import os
from dotenv import load_dotenv

import base64

from promtps.Gemini_photo_recognized import create_photo_prompt
from promtps.Gemini_take_food import create_food_resolution_prompt

from services.fatsecret_food_service import fatsecret_food_search
from services.fatsecret_food_service import fatsecret_get_food
from services.matching_operation import MatchingOperation, MatchingBudgetExceeded, UnverifiedFoodSelection

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def _build_client():
    # Limit request duration and built-in retries; gemini_service manages stage
    # retries and progress. HttpOptions.timeout is expressed in milliseconds.
    return genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(
        timeout=30_000,
        retry_options=types.HttpRetryOptions(attempts=1),
    ))


client = _build_client()

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
        store=False,
    )

    return interaction.output_text

def new_matching_operation():
    return MatchingOperation(fatsecret_food_search, fatsecret_get_food)


def gemini_search_food(recognized_meal: dict, language: str, operation):
    def search_food_candidates(query: str) -> dict:
        """Find product cards by name and brand; returns local candidate references."""
        return operation.dispatch('search_food_candidates', {'query': query})

    def get_candidate_portions(candidate_ref: str) -> dict:
        """Inspect serving cards of an already discovered local candidate."""
        return operation.dispatch('get_candidate_portions', {'candidate_ref': candidate_ref})

    prompt = create_food_resolution_prompt(recognized_meal, language)
    contents = prompt
    history = [types.Content(role='user', parts=[types.Part.from_text(text=prompt)])]
    config = types.GenerateContentConfig(
        tools=[search_food_candidates, get_candidate_portions],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        candidate_count=1,
    )
    # Manual loop: the budget counts every generate_content request, including
    # failures and all service retries. The SDK cannot run an uncounted AFC loop.
    while True:
        operation.take_gemini_call()
        response = client.models.generate_content(model=Gemini_model, contents=contents, config=config)
        candidates = getattr(response, 'candidates', None)
        content = candidates[0].content if isinstance(candidates, list) and candidates else None
        calls = [part.function_call for part in (content.parts or []) if part.function_call] if content else []
        if not calls:
            if not isinstance(response.text, str):
                raise UnverifiedFoodSelection('No selection response')
            return response.text
        if len(calls) > operation.MAX_TOOL_CALLS - operation.tool_calls:
            raise MatchingBudgetExceeded('Tool call budget exhausted')
        responses = []
        for call in calls:
            result = operation.dispatch(call.name, call.args)
            responses.append(types.Part(function_response=types.FunctionResponse(
                name=call.name, id=call.id, response=result)))
        history.extend([content, types.Content(role='user', parts=responses)])
        contents = list(history)
