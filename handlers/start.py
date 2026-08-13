from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from repositories.user_repository import create_user, get_user
from handlers.menu import build_main_menu
from handlers.fatsecret_auth import build_fatsecret_connection_screen

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    keyboard = [
        [
            InlineKeyboardButton("RU Русский", callback_data='language_ru'),
            InlineKeyboardButton("EN English", callback_data='language_en'),
        ]
    ]
    
    if user is None:
        create_user(telegram_id)
        user = get_user(telegram_id)
        if user is None:
            await update.effective_message.reply_text("Error while user created. Try again later") 
            return
        
    if user.language is None or user.language == '':   
        await update.effective_message.reply_text(
            'Выберите ваш язык / Choose your language:',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if not user.fatsecret_token or not user.fatsecret_token_secret:
        text, markup = build_fatsecret_connection_screen(user.language)
        await update.message.reply_text(
            text,
            reply_markup=markup,
        )
        return

    text, markup = build_main_menu(user.language)
    await update.effective_message.reply_text(text, reply_markup=markup)
