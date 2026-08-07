import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    Application,
    CommandHandler,
    ContextTypes
)

from database.init_db import init_db

from handlers.start import start 
from handlers.language import select_language
from handlers.fatsecret_auth import start_fatsecret_auth

load_dotenv()

telegram_api_key = os.getenv("TELEGRAM_API_KEY")

def main() -> None:
    init_db()
    
    app = Application.builder().token(telegram_api_key).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        CallbackQueryHandler(
            select_language,
            pattern=r"^language_(ru|en)$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            start_fatsecret_auth,
            pattern=r"^fatsecret_auth_start",
        )
    )
    app.run_polling()

if __name__ == "__main__":
    main()