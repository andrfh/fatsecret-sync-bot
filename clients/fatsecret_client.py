from requests_oauthlib import OAuth1Session

from oauthlib.oauth1 import (
    SIGNATURE_HMAC,
    SIGNATURE_TYPE_BODY,
)

REQUEST_TOKEN_URL = (
    "https://authentication.fatsecret.com/oauth/request_token"
)

AUTHORIZATION_URL = (
    "https://authentication.fatsecret.com/oauth/authorize"
)

ACCESS_TOKEN_URL = (
    "https://authentication.fatsecret.com/oauth/access_token"
)

def create_authorization(consumer_key: str, consumer_secret: str) -> tuple[str, str, str]:
    oauth = OAuth1Session(consumer_key, client_secret=consumer_secret, callback_uri="oob", signature_method=SIGNATURE_HMAC, signature_type=SIGNATURE_TYPE_BODY)

    tokens = oauth.fetch_request_token(REQUEST_TOKEN_URL)

    request_token = tokens["oauth_token"]
    request_token_secret = tokens["oauth_token_secret"]
    
    authorization_url = oauth.authorization_url(AUTHORIZATION_URL)

    return authorization_url, request_token, request_token_secret

def exchange_verifier(consumer_key: str, consumer_secret: str, access_token: str, token_secret: str, verifier: int) -> tuple[str, str]:
    oauth = OAuth1Session(
        consumer_key, 
        client_secret=consumer_secret, 
        resource_owner_key = access_token,
        resource_owner_secret = token_secret,
        verifier = verifier,
        callback_uri="oob", 
        signature_method=SIGNATURE_HMAC, 
        signature_type=SIGNATURE_TYPE_BODY
    )

    user_tokens = oauth.fetch_access_token(ACCESS_TOKEN_URL)

    user_token = user_tokens["oauth_token"]
    user_token_secret = user_tokens["oauth_token_secret"]

    return user_token, user_token_secret


