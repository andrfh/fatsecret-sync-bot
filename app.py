import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    Application,
    CommandHandler,
    PicklePersistence,
    ConversationHandler,
    MessageHandler, 
    filters
)

from database.init_db import init_db

from handlers.start import start 
from handlers.language import select_language
from handlers.fatsecret_auth import (
    start_fatsecret_auth,
    process_fatsecret_verifier,
    IS_WAITING_VERIFIER
)

load_dotenv()

telegram_api_key = os.getenv("TELEGRAM_API_KEY")

fatsecret_auth_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_fatsecret_auth, pattern=r"^fatsecret_auth_start$")
    ],
    states={
        IS_WAITING_VERIFIER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_fatsecret_verifier)
        ]
    },
    fallbacks=[
        CommandHandler("cancel", lambda u, c: ConversationHandler.END) 
    ],
    name="fatsecret_auth_conversation"
)

def main() -> None:
    init_db()

    my_persistence = PicklePersistence(filepath="bot_data.pickle")

    app = Application.builder().token(telegram_api_key).persistence(my_persistence) .build()

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
            pattern=r"^fatsecret_auth_start$",
        )
    )

    app.add_handler(fatsecret_auth_conv)

    app.run_polling()

if __name__ == "__main__":
    main()