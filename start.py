from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes
)

from repositories.user_repository import create_user, get_user

from handlers.menu import build_main_menu

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    keyboard = [
        [
            InlineKeyboardButton("RU Русский", callback_data='language_ru'),
            InlineKeyboardButton("EN English", callback_data='language_en'),
        ]
    ]

    auth_button_ru = [
        [
            InlineKeyboardButton("Подключить FatSecret!", callback_data='fatsecret_auth_start')
        ]
    ]

    auth_button_en = [
            [
                InlineKeyboardButton("Connect FatSecret!", callback_data='fatsecret_auth_start')
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
            await update.message.reply_text("Connect your FatSecret account to continue.",
            reply_markup=InlineKeyboardMarkup(auth_button_en)) 
        elif user.language == "ru":
            await update.message.reply_text("Для продолжения подключите аккаунт FatSecret.",
            reply_markup=InlineKeyboardMarkup(auth_button_ru))
        return

    text, markup = build_main_menu(user.language)

    await update.message.reply_text(text, reply_markup=markup) 

    

    