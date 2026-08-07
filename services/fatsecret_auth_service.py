def start_authorization() -> tuple[str, str, str]:

def complete_authorization(
    telegram_id: int,
    request_token: str,
    request_token_secret: str,
    verifier: str,
) -> None:
