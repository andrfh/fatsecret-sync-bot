from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.user_repository import get_user
from ui.texts import text
from services.meal_state import clear_meal_data, close_pending_meal_write


def build_main_menu(language: str) -> tuple[str, InlineKeyboardMarkup]:
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text(language, "add"), callback_data="menu_photo")],
        [InlineKeyboardButton(text(language, "settings_button"), callback_data="menu_settings")],
    ])
    return text(language, "menu", connection=text(language, "connected")), keyboard


async def back_to_main_menu(update, context):
    await close_pending_meal_write(context.user_data, update.effective_user.id)
    clear_meal_data(context.user_data)
    query = update.callback_query
    await query.answer()
    language = get_user(update.effective_user.id).language
    menu_text, markup = build_main_menu(language)
    await query.edit_message_text(menu_text, reply_markup=markup, parse_mode="HTML")
