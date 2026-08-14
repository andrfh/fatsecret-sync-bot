from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes
)

from repositories.user_repository import get_user

def build_main_menu(language: str) -> tuple[str, InlineKeyboardMarkup]:
    if language == "ru":
        menu_text = (
            "Добро пожаловать в главное меню.\n\n"
            "Используйте кнопки ниже для управления дневником питания, "
            "добавления новых приемов пищи и изменения параметров приложения."
        )
        photo_text = "Добавить еду по фото"
        settings_text = "Настройки"
    elif language == "en":
        menu_text = (
            "Welcome to the main menu.\n\n"
            "Use the buttons below to manage your food diary, "
            "add new meals, and change application parameters."
        )
        photo_text = "Add meal by photo"
        settings_text = "Settings"

    keyboard = [
        [
            InlineKeyboardButton(photo_text, callback_data='menu_photo')
        ],
        [
            InlineKeyboardButton(settings_text, callback_data='menu_settings')
        ]
    ]

    return menu_text, InlineKeyboardMarkup(keyboard)

async def back_to_main_menu(update, context):
    telegram_id = update.effective_user.id
    query = update.callback_query
    await query.answer()

    language = get_user(telegram_id).language

    menu_text, markup = build_main_menu(language)

    await query.edit_message_text(menu_text, reply_markup=markup) 
