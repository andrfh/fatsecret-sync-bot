from repositories.user_repository import get_user, update_language
from handlers.menu import build_main_menu
from handlers.fatsecret_auth import build_fatsecret_connection_screen
from ui.texts import text


async def select_language(update, context):
    query = update.callback_query
    await query.answer()
    if query.data not in ("language_ru", "language_en"):
        return
    language = query.data.removeprefix("language_")
    update_language(update.effective_user.id, language)
    user = get_user(update.effective_user.id)
    if user is None:
        await query.edit_message_text(text(language, "user_error"))
        return
    if not user.fatsecret_token or not user.fatsecret_token_secret:
        screen, markup = build_fatsecret_connection_screen(user.language)
    else:
        screen, markup = build_main_menu(user.language)
    await query.edit_message_text(screen, reply_markup=markup, parse_mode="HTML")
