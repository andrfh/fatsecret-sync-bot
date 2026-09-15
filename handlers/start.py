from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from repositories.user_repository import create_user, get_user
from handlers.menu import build_main_menu
from handlers.fatsecret_auth import build_fatsecret_connection_screen
from ui.texts import HELLO, text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    if user is None:
        create_user(telegram_id)
        user = get_user(telegram_id)
        if user is None:
            await update.effective_message.reply_text(text("ru", "user_error"))
            return
    if user.language not in ("ru", "en"):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Русский", callback_data="language_ru"),
            InlineKeyboardButton("English", callback_data="language_en"),
        ]])
        await update.effective_message.reply_text(HELLO, reply_markup=keyboard)
        return
    if not user.fatsecret_token or not user.fatsecret_token_secret:
        setup_text, markup = build_fatsecret_connection_screen(user.language)
        await update.effective_message.reply_text(setup_text, reply_markup=markup)
        return
    menu_text, markup = build_main_menu(user.language)
    await update.effective_message.reply_text(menu_text, reply_markup=markup)
