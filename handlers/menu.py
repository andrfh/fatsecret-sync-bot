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
        photo_text = "Добавить прием пищи"
        settings_text = "Настройки"
    elif language == "en":
        menu_text = (
            "Welcome to the main menu.\n\n"
            "Use the buttons below to manage your food diary, "
            "add new meals, and change application parameters."
        )
        photo_text = "Add meal"
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


async def open_photo_screen(update, context):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("Здесь будет обработчик фото")

async def open_settings_screen(update, context):
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language

    query = update.callback_query
    await query.answer()

    if language == "ru":
        settings_text = "Меню настроек"
        language_text = "Сменить язык системы"
        back_text = "Вернуться в меню"
        another_language="en"
    elif language == "en":
        settings_text = "Settings menu"
        language_text = "Change system lamguage"
        back_text = "Back to the menu"
        another_language="ru"


    keyboard = [
        [
            InlineKeyboardButton(language_text, callback_data='language_' + another_language)
        ],
        [
            InlineKeyboardButton(back_text, callback_data='settings_back')
        ]
    ]

    await query.edit_message_text(settings_text, reply_markup=InlineKeyboardMarkup(keyboard)) 


    

async def back_to_main_menu(update, context):
    telegram_id = update.effective_user.id
    query = update.callback_query
    await query.answer()

    language = get_user(telegram_id).language


    menu_text, markup  = build_main_menu(language)

    await query.edit_message_text(menu_text, reply_markup=markup) 
