from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes
)

from repositories.user_repository import get_user, update_language, remove_fatsecret_tokens
from handlers.menu import build_main_menu
from handlers.fatsecret_auth import build_fatsecret_connection_screen
from handlers.start import start

def build_settings_menu(language: str) -> tuple[str, InlineKeyboardMarkup]:
    if language == "ru":
            settings_text = "Меню настроек"
            language_text = "Сменить язык системы"
            loguot_text = "Выйти из аккаунта"
            back_text = "Вернуться в меню"
    elif language == "en":
        settings_text = "Settings menu"
        language_text = "Change system lamguage"
        loguot_text = "Log out from profile"
        back_text = "Back to the menu"

    keyboard = [
        [
            InlineKeyboardButton(language_text, callback_data="settings_language")
        ],
        [
            InlineKeyboardButton(loguot_text, callback_data="settings_logout")
        ],
        [
            InlineKeyboardButton(back_text, callback_data='menu_back')
        ]
    ]

    return settings_text, InlineKeyboardMarkup(keyboard)

async def open_settings_screen(update, context):
    telegram_id = update.effective_user.id
    query = update.callback_query

    await query.answer()

    user = get_user(telegram_id)

    text, markup = build_settings_menu(user.language)

    await query.edit_message_text(
        text,
        reply_markup=markup,
    )

async def cahnge_language(update: Update, context: ContextTypes.DEFAULT_TYPE,) -> None:
    telegram_id = update.effective_user.id
    query = update.callback_query

    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("RU Русский", callback_data='settings_language_ru'),
            InlineKeyboardButton("EN English", callback_data='settings_language_en'),
        ]
    ]

    if query.data == "settings_language":
        await query.edit_message_text(
            'Выберите ваш язык / Choose your language:',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif query.data == "settings_language_ru":
        update_language(telegram_id, "ru")
        menu_text, markup = build_settings_menu("ru")
        await query.edit_message_text(menu_text, reply_markup=markup) 

    elif query.data == "settings_language_en":
        update_language(telegram_id, "en")
        menu_text, markup = build_settings_menu("en")
        await query.edit_message_text(menu_text, reply_markup=markup) 
        
async def settings_fatsecret_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE,) -> None:
    telegram_id = update.effective_user.id
    query = update.callback_query

    language = get_user(telegram_id).language

    await query.answer()

    if language == "ru":
        confirm = "Вы уверены, что хотите выйти из аккаунта? \n"
        confirm_yes = "Да, я хочу выйти из аккаунта"
        confirm_no = "Нет, я хочу остаться в аккаунте"
        error_text = "Что-то пошло не так. Пожалуйста, повторите позже"
        back_text = "Вернуться в меню"
    elif language == "en":
        confirm = "Are you shure you want to log out \n"
        confirm_yes = "Yes, I wabt to log out"
        confirm_no = "No, I want to stay in this profile"
        error_text = "Somethnig went wrong. Please, try again later"
        back_text = "Back to the menu"

    keyboard = [
        [
            InlineKeyboardButton(confirm_yes, callback_data='settings_logout_yes'),
            InlineKeyboardButton(confirm_no, callback_data='settings_logout_no'),
        ]
    ]

    keyboard_back = [
        [
            InlineKeyboardButton(back_text, callback_data='menu_back'),
        ]
    ]

    if query.data == "settings_logout":
        await query.edit_message_text(confirm, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "settings_logout_yes":
        try:
            remove_fatsecret_tokens(telegram_id)
        except Exception as error:
            print(
                f"FatSecret disconnect failed: "
                f"{type(error).__name__}"
            )

            await query.edit_message_text(
                error_text,
                reply_markup=InlineKeyboardMarkup(keyboard_back),
            )
            return

        fatsecret_screen, fatsecret_screen_markup = (build_fatsecret_connection_screen(language))
        await query.edit_message_text(fatsecret_screen, reply_markup=fatsecret_screen_markup)

    elif query.data == "settings_logout_no":
        menu_text, markup = build_settings_menu(language)
        await query.edit_message_text(menu_text, reply_markup=markup) 
