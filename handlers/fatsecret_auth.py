from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    ContextTypes
)

import asyncio

from services.fatsecret_auth_service import start_authorization
from services.fatsecret_auth_service import complete_authorization
from repositories.user_repository import get_user


WAITING_VERIFIER = 1

async def start_fatsecret_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    try:
        auth_data = await asyncio.to_thread(
            start_authorization
        )

    except Exception as error:
        print(f"FatSecret get auth data failed: {type(error).__name__}")
        if language == 'ru':
            await query.edit_message_text('Что-то пошло не так. Пожалуйста, попробуйте позднее.')
        elif language == 'en':
            await query.edit_message_text('Something went wrong. Please, try again later.')
        return ConversationHandler.END

    context.user_data["request_token"] = auth_data[1]
    context.user_data["request_token_secret"] = auth_data[2]

    keyboard_ru = [
        [
            InlineKeyboardButton(
                text="Авторизовать FatSecret", 
                url=auth_data[0]
            )
        ]
    ]
    keyboard_en= [
            [
                InlineKeyboardButton(
                    text="Login FatSecret", 
                    url=auth_data[0]
                )
            ]
        ]
    
    if language == "en":
        await query.edit_message_text(
            'Connect your FatSecret account. Press the button, authorize and send the code to this chat.',
            reply_markup=InlineKeyboardMarkup(keyboard_en)
        )
    elif language == "ru":
        await query.edit_message_text(
            'Подключите Ваш аккаунт FatSecret. Нажмите кнопку, авторизуйтесь и введите в чат полученный на сайте код.',
            reply_markup=InlineKeyboardMarkup(keyboard_ru)
        )

    return WAITING_VERIFIER
    

    
async def process_fatsecret_verifier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    verifier = update.message.text.strip()

    request_token = context.user_data.get("request_token")
    request_token_secret = context.user_data.get("request_token_secret")

    if language == "ru":
        error_text = "Сессия устарела. Начните авторизацию заново." 
        success_text="Аккаунт FatSecret успешно подключен!"
        fail_text = "Ошибка авторизации: Неверный код. Попробуйте еще раз."
    elif language == "en":
        error_text = "Session expired. Please restart auth."
        success_text = "FatSecret account successfully connected!"
        fail_text = "Auth error: Invalid code. Try again."


    if not request_token or not request_token_secret:
        await update.message.reply_text(error_text)
        return ConversationHandler.END

    try: 
        await asyncio.to_thread(
            complete_authorization,
            telegram_id,
            request_token,
            request_token_secret,
            verifier,
        )

        await update.message.reply_text(success_text)

    except Exception as error:
        print(f"FatSecret authorization failed: {type(error).__name__}")
        await update.message.reply_text(fail_text)
        return WAITING_VERIFIER

    context.user_data.pop("request_token", None)
    context.user_data.pop("request_token_secret", None)

    return ConversationHandler.END

async def cancel_fatsecret_auth(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.pop("request_token", None)
    context.user_data.pop("request_token_secret", None)
    
    return ConversationHandler.END
        