import os
from dotenv import load_dotenv

load_dotenv()

from datetime import date

from clients.fatsecret_client import food_search
from clients.fatsecret_client import get_food
from clients.fatsecret_client import create_food_entry

FATSECRET_CONSUMER_KEY = os.getenv("FATSECRET_CONSUMER_KEY")
FATSECRET_CONSUMER_SECRET = os.getenv("FATSECRET_CONSUMER_SECRET")

def fatsecret_food_search(query: str) -> dict:
    food_items = food_search(query, FATSECRET_CONSUMER_KEY, FATSECRET_CONSUMER_SECRET)
    return food_items

def fatsecret_get_food(food_id: int) -> dict:
    food = get_food(food_id, FATSECRET_CONSUMER_KEY, FATSECRET_CONSUMER_SECRET)
    return food

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
    
    except Exception as error:
        return {"status": "error", "response": error}

        


