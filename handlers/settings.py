from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.user_repository import get_user, update_language, remove_fatsecret_tokens
from handlers.fatsecret_auth import build_fatsecret_connection_screen
from ui.texts import LANGUAGE_PROMPT, text


def build_settings_menu(language: str):
    connection = text(language, "connected")
    keyboard = [
        [InlineKeyboardButton(text(language, "language_button"), callback_data="settings_language")],
        [InlineKeyboardButton(text(language, "disconnect"), callback_data="settings_disconnect")],
        [InlineKeyboardButton(text(language, "menu_button"), callback_data="menu_back")],
    ]
    return text(language, "settings", connection=connection), InlineKeyboardMarkup(keyboard)


async def open_settings_screen(update, context):
    query = update.callback_query
    await query.answer()
    user = get_user(update.effective_user.id)
    screen, markup = build_settings_menu(user.language)
    await query.edit_message_text(screen, reply_markup=markup)


async def change_language(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "settings_language":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Русский", callback_data="settings_language_ru"),
            InlineKeyboardButton("English", callback_data="settings_language_en"),
        ]])
        await query.edit_message_text(LANGUAGE_PROMPT, reply_markup=keyboard)
        return
    language = query.data.removeprefix("settings_language_")
    if language not in ("ru", "en"):
        return
    update_language(update.effective_user.id, language)
    screen, markup = build_settings_menu(language)
    await query.edit_message_text(screen, reply_markup=markup)


async def disconnect_fatsecret(update, context):
    query = update.callback_query
    language = get_user(update.effective_user.id).language
    await query.answer()
    if query.data == "settings_disconnect":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(text(language, "disconnect_yes"), callback_data="settings_disconnect_confirm"),
            InlineKeyboardButton(text(language, "disconnect_no"), callback_data="settings_disconnect_cancel"),
        ]])
        await query.edit_message_text(text(language, "disconnect_confirm"), reply_markup=keyboard)
        return
    if query.data == "settings_disconnect_confirm":
        try:
            remove_fatsecret_tokens(update.effective_user.id)
        except Exception as error:
            print(f"FatSecret disconnect failed: {type(error).__name__}")
            await query.edit_message_text(text(language, "disconnect_error"),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    text(language, "menu_button"), callback_data="menu_back")]]))
            return
        screen, markup = build_fatsecret_connection_screen(language)
        await query.edit_message_text(screen, reply_markup=markup)
    elif query.data == "settings_disconnect_cancel":
        screen, markup = build_settings_menu(language)
        await query.edit_message_text(screen, reply_markup=markup)
