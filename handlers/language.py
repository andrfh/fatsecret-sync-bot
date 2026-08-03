from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

from repositories.user_repository import get_user, update_language

async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE,) -> None:
    telegram_id = update.effective_user.id
    query = update.callback_query

    await query.answer()

    if query.data == "language_ru":
        language = "ru"
        text = (
            "Вы выбрали русский язык.\n\n"
            "Для продолжения подключите аккаунт FatSecret."
        )

    elif query.data == "language_en":
        language = "en"
        text = (
            "You selected English.\n\n"
            "Connect your FatSecret account to continue."
        )

    else:
        return

    update_language(telegram_id, language)

    user = get_user(telegram_id)

    if user is None:
        await query.edit_message_text("User not found.")
        return

    if not user.fatsecret_token or not user.fatsecret_token_secret:
        # показать экран подключения FatSecret
        return

    await query.edit_message_text(text)


    

    
    