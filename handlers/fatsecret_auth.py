from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

from datetime import datetime, timezone

from services.fatsecret_auth_service import start_authorization
from repositories.user_repository import get_user, save_fatsecret_credentials

async def start_fatsecret_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("Вызвалось ")
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language

    query = update.callback_query

    auth_data = start_authorization()

    context.user_data["request_token"] = auth_data[1]
    context.user_data["request_token_secret"] = auth_data[2]

    save_fatsecret_credentials(telegram_id, auth_data[1], auth_data[2], datetime.now(timezone.utc).isoformat())

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
    return
    

    

    