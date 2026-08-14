from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    ContextTypes
)

import asyncio

from io import BytesIO

from services.fatsecret_auth_service import start_authorization
from services.fatsecret_auth_service import complete_authorization
from repositories.user_repository import get_user
from handlers.menu import build_main_menu

WAITING_PHOTO = 1

async def open_photo_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    if language == "ru":
        screen_text = "Сфотографируйте Ваш прием пищи и загрузите фотографию в чат. \n Для лучшего результата добавьте описание блюда (примерный вес, ингридиенты, размер тарелки)."
        screen_btn = "Отмена"
    elif language == "en":
        screen_text = "Take a photo of your meal and upload it to the chat. \nFor best results, add a description of the dish (approximate weight, ingredients, plate size)." 
        screen_btn = "Cancel"

    keyboard = [
        [
            InlineKeyboardButton(screen_btn, callback_data='photo_cancel')           
        ]
    ]

    await query.edit_message_text(screen_text, reply_markup = InlineKeyboardMarkup(keyboard))

    return WAITING_PHOTO
    
async def process_photo(update, context):
    await update.message.reply_text("Photo received")

    return ConversationHandler.END
    
async def cancel_photo_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    menu_text, markup = build_main_menu(language)
    await query.edit_message_text(menu_text, reply_markup=markup) 
    
    return ConversationHandler.END