import asyncio
import json

from clients.gemini_client import recognize_image
from clients.gemini_client import gemini_search_food

async def recognize_meal(image_bytes: bytes, description: str, meal_type: str):
    allowed_statuses = ["ok", "not_food", "too_complex", "uncertain"]

    ai_response = await asyncio.to_thread(
        recognize_image,
        image_bytes,
        description,
        meal_type
    )

    meal_data = json.loads(ai_response)

    if meal_data["status"] in allowed_statuses:
        return meal_data
    
    else:
        return {
            "status": "Error", 
            "message": "AI return not allowed status"
        }

async def search_food(recognized_meal: dict, language: str):
    allowed_resolution = ["components", "whole_meal"]

    ai_response = await asyncio.to_thread(
        gemini_search_food,
        recognized_meal,
        language
    )

    food_data = json.loads(ai_response)

    if food_data["resolution"] in allowed_resolution:
        return food_data
    
    else:
        return {
            "status": "Error", 
            "message": "AI return not allowed resolution"
        }
    