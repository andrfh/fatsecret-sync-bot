import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    Application,
    CommandHandler,
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
    cancel_fatsecret_auth,
    WAITING_VERIFIER
)

from handlers.menu import (
    back_to_main_menu,
    open_photo_screen,
    open_settings_screen
)

load_dotenv()

telegram_api_key = os.getenv("TELEGRAM_API_KEY")

fatsecret_auth_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_fatsecret_auth, pattern=r"^fatsecret_auth_start$")
    ],
    states={
        WAITING_VERIFIER: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                process_fatsecret_verifier,
            )
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_fatsecret_auth)
    ],
    name="fatsecret_auth_conversation"
)

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
            open_photo_screen,
            pattern=r"^menu_photo$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            back_to_main_menu ,
            pattern=r"^menu_back$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            open_settings_screen ,
            pattern=r"^menu_settings$",
        )
    )

    app.add_handler(fatsecret_auth_conv)

    app.run_polling()

if __name__ == "__main__":
    main()