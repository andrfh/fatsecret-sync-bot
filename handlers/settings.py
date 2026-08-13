from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes
)

from repositories.user_repository import get_user, update_language, remove_fatsecret_tokens
from handlers.fatsecret_auth import build_fatsecret_connection_screen

def build_settings_menu(language: str) -> tuple[str, InlineKeyboardMarkup]:
    if language == "ru":
        settings_text = "Меню настроек"
        language_text = "Сменить язык системы"
        disconnect_text = "Отключить FatSecret"
        back_text = "Вернуться в меню"
    elif language == "en":
        settings_text = "Settings menu"
        language_text = "Change system lamguage"
        disconnect_text = "Disconnect FatSecret"
        back_text = "Back to the menu"

    keyboard = [
        [
            InlineKeyboardButton(language_text, callback_data="settings_language")
        ],
        [
            InlineKeyboardButton(disconnect_text, callback_data="settings_disconnect")
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

async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE,) -> None:
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
        
async def disconnect_fatsecret(update: Update, context: ContextTypes.DEFAULT_TYPE,) -> None:
    telegram_id = update.effective_user.id
    query = update.callback_query

    language = get_user(telegram_id).language

    await query.answer()

    if language == "ru":
        confirm = "Вы уверены, что хотите отключить FatSecret? \n"
        confirm_yes = "Да, отключить"
        confirm_no = "Отмена"
        error_text = "Что-то пошло не так. Пожалуйста, повторите позже"
        back_text = "Вернуться в меню"
    elif language == "en":
        confirm = "Are you sure you want to disconnect FatSecret? \n"
        confirm_yes = "Yes, disconnect"
        confirm_no = "Cancel"
        error_text = "Somethnig went wrong. Please, try again later"
        back_text = "Back to the menu"

    keyboard = [
        [
            InlineKeyboardButton(confirm_yes, callback_data='settings_disconnect_confirm'),
            InlineKeyboardButton(confirm_no, callback_data='settings_disconnect_cancel'),
        ]
    ]

    keyboard_back = [
        [
            InlineKeyboardButton(back_text, callback_data='menu_back'),
        ]
    ]

    if query.data == "settings_disconnect":
        await query.edit_message_text(confirm, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "settings_disconnect_confirm":
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

    elif query.data == "settings_disconnect_cancel":
        menu_text, markup = build_settings_menu(language)
        await query.edit_message_text(menu_text, reply_markup=markup) 
