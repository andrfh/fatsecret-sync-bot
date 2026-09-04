from requests_oauthlib import OAuth1Session

from oauthlib.oauth1 import (
    SIGNATURE_HMAC,
    SIGNATURE_TYPE_BODY,
    SIGNATURE_TYPE_QUERY
)
from urllib.parse import parse_qs

REQUEST_TOKEN_URL = "https://authentication.fatsecret.com/oauth/request_token"

AUTHORIZATION_URL = "https://authentication.fatsecret.com/oauth/authorize"

ACCESS_TOKEN_URL = "https://authentication.fatsecret.com/oauth/access_token"

FOODS_SEARCH_URL = "https://platform.fatsecret.com/rest/foods/search/v1"

FOOD_GET_URL = "https://platform.fatsecret.com/rest/food/v5"

FOOD_ENTRIES_URL = "https://platform.fatsecret.com/rest/food-entries/v1"

def create_authorization(consumer_key: str, consumer_secret: str) -> tuple[str, str, str]:
    try:
        oauth = OAuth1Session(consumer_key, client_secret=consumer_secret, callback_uri="oob", signature_method=SIGNATURE_HMAC, signature_type=SIGNATURE_TYPE_BODY)

        tokens = oauth.fetch_request_token(REQUEST_TOKEN_URL)

        request_token = tokens["oauth_token"]
        request_token_secret = tokens["oauth_token_secret"]
        
        authorization_url = oauth.authorization_url(AUTHORIZATION_URL)

        return authorization_url, request_token, request_token_secret
    except Exception as error:
            return error
    
def exchange_verifier(consumer_key: str, consumer_secret: str, request_token: str, request_token_secret: str, verifier: str) -> tuple[str, str]:
    try:
        oauth = OAuth1Session(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=request_token,
            resource_owner_secret=request_token_secret,
            verifier=verifier,
            signature_method=SIGNATURE_HMAC,
            signature_type=SIGNATURE_TYPE_QUERY,
        )

        response = oauth.get(ACCESS_TOKEN_URL)
        response.raise_for_status()

        data = parse_qs(response.text)

        user_token = data["oauth_token"][0]
        user_token_secret = data["oauth_token_secret"][0]

        return user_token, user_token_secret
    except Exception as error:
            return error

def food_search(query: str, consumer_key: str, consumer_secret: str) -> dict:
    try:
        oauth = OAuth1Session(
            consumer_key,
            client_secret=consumer_secret,
            signature_method=SIGNATURE_HMAC,
            signature_type=SIGNATURE_TYPE_QUERY,
        )

        response = oauth.get(
            FOODS_SEARCH_URL,
            params={
                "search_expression": query,
                "format": "json",
                "max_results": 10,
            },
        )

        response.raise_for_status()
        return response.json()
    except Exception as error:
        return error

def get_food(food_id: int, consumer_key: str, consumer_secret: str) -> dict:
    try:
        oauth = OAuth1Session(
            consumer_key,
            client_secret=consumer_secret,
            signature_method=SIGNATURE_HMAC,
            signature_type=SIGNATURE_TYPE_QUERY,
        )

        response = oauth.get(
            FOOD_GET_URL,
            params={
                "food_id": food_id,
                "format": "json",
            },
        )

        response.raise_for_status()
        return response.json()
    except Exception as error:
        return error

def create_food_entry(
        consumer_key: str,
        consumer_secret: str,
        user_token: str,
        user_token_secret: str,
        food_id: int | str,
        food_entry_name: str,
        serving_id: int | str,
        number_of_units: float,
        meal: str,
        date: int,
    ) -> dict:
    try:
        oauth = OAuth1Session(
            consumer_key, 
            client_secret=consumer_secret, 
            signature_method=SIGNATURE_HMAC, 
            signature_type=SIGNATURE_TYPE_BODY, 
            resource_owner_key=user_token,
            resource_owner_secret=user_token_secret
            )


        response = oauth.post(
            FOOD_ENTRIES_URL,
            data={
                "food_id": food_id,
                "food_entry_name": food_entry_name,
                "serving_id": serving_id,
                "number_of_units": number_of_units,
                "meal": meal,
                "date": date,
                "format": "json",
            },
        )

        response.raise_for_status()

        return response.json()
    
    except Exception as error:
        return error