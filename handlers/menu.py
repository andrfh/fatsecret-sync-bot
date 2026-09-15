from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.user_repository import get_user
from ui.texts import text


def build_main_menu(language: str) -> tuple[str, InlineKeyboardMarkup]:
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text(language, "add"), callback_data="menu_photo")],
        [InlineKeyboardButton(text(language, "settings_button"), callback_data="menu_settings")],
    ])
    return text(language, "menu", connection=text(language, "connected")), keyboard


async def back_to_main_menu(update, context):
    query = update.callback_query
    await query.answer()
    language = get_user(update.effective_user.id).language
    menu_text, markup = build_main_menu(language)
    await query.edit_message_text(menu_text, reply_markup=markup)
