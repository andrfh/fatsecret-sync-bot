from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler
import asyncio
import logging

from services.fatsecret_auth_service import start_authorization, complete_authorization
from repositories.user_repository import get_user
from handlers.menu import build_main_menu
from ui.texts import text

WAITING_VERIFIER = 1
logger = logging.getLogger(__name__)


def build_fatsecret_connection_screen(language: str):
    return text(language, "setup"), InlineKeyboardMarkup([[
        InlineKeyboardButton(text(language, "connect"), callback_data="fatsecret_auth_start")
    ]])


async def start_fatsecret_auth(update, context):
    language = get_user(update.effective_user.id).language
    query = update.callback_query
    await query.answer()
    try:
        auth_data = await asyncio.to_thread(start_authorization)
    except Exception as error:
        logger.warning("FatSecret authorization stage=start failed type=%s",
                       type(error).__name__)
        await query.edit_message_text(text(language, "auth_start_error"))
        return ConversationHandler.END
    context.user_data["request_token"] = auth_data[1]
    context.user_data["request_token_secret"] = auth_data[2]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text(language, "open_fatsecret"), url=auth_data[0])],
    ])
    try:
        await query.edit_message_text(text(language, "auth_steps"), reply_markup=keyboard,
                                      parse_mode="HTML")
    except Exception:
        context.user_data.pop("request_token", None)
        context.user_data.pop("request_token_secret", None)
        raise
    return WAITING_VERIFIER


async def process_fatsecret_verifier(update, context):
    language = get_user(update.effective_user.id).language
    request_token = context.user_data.get("request_token")
    request_token_secret = context.user_data.get("request_token_secret")
    if not request_token or not request_token_secret:
        await update.message.reply_text(text(language, "auth_expired"))
        return ConversationHandler.END
    try:
        await asyncio.to_thread(complete_authorization, update.effective_user.id,
                                request_token, request_token_secret, update.message.text.strip())
    except Exception as error:
        logger.warning("FatSecret authorization stage=exchange failed type=%s",
                       type(error).__name__)
        await update.message.reply_text(text(language, "auth_error"))
        return WAITING_VERIFIER
    context.user_data.pop("request_token", None)
    context.user_data.pop("request_token_secret", None)
    user = get_user(update.effective_user.id)
    menu_text, markup = build_main_menu(user.language)
    await update.message.reply_text(text(language, "auth_success"), parse_mode="HTML")
    await update.message.reply_text(menu_text, reply_markup=markup, parse_mode="HTML")
    return ConversationHandler.END


async def verifier_input_reminder(update, context):
    language = get_user(update.effective_user.id).language
    await update.message.reply_text(text(language, "auth_reminder"))
    return WAITING_VERIFIER


async def cancel_fatsecret_auth(update, context):
    context.user_data.pop("request_token", None)
    context.user_data.pop("request_token_secret", None)
    return ConversationHandler.END
