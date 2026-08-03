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

    elif query.data == "language_en":
        language = "en"

    else:
        return

    update_language(telegram_id, language)

    user = get_user(telegram_id)

    if user is None:
        await query.edit_message_text("User not found.")
        return

    if not user.fatsecret_token or not user.fatsecret_token_secret:
        if language == "ru":
            await query.edit_message_text("Для продолжения подключите аккаунт FatSecret.")
        elif language == "en":
            await query.edit_message_text("Connect your FatSecret account to continue.")
        return
    elif user.fatsecret_token and user.fatsecret_token_secret:
        await update.message.reply_text("Main menu.") 
        return



    

    
    