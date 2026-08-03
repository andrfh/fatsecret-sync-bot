from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

from repositories.user_repository import create_user, get_user

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
            await update.message.reply_text("Error while user created. Try again later") 
            return
        
    if user.language is None or user.language == '':   
        await update.message.reply_text(
            'Выберите ваш язык / Choose your language:',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if not user.fatsecret_token or not user.fatsecret_token_secret:
        if user.language == "en":
            await update.message.reply_text("Connect your FatSecret account to continue.") 
        elif user.language == "ru":
            await update.message.reply_text("Для продолжения подключите аккаунт FatSecret.")
        return

    await update.message.reply_text("Main menu") 

    

    