import os
from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from pathlib import Path

import asyncio
from urllib.parse import parse_qs
from requests_oauthlib import OAuth1Session
from oauthlib.oauth1 import SIGNATURE_HMAC, SIGNATURE_TYPE_BODY, SIGNATURE_TYPE_QUERY


PHOTO_DIR = Path("users_photos")
PHOTO_DIR.mkdir(exist_ok=True)

load_dotenv()

telegram_api_key = os.getenv("TELEGRAM_API_KEY")

fatsecret_consumer_key = os.getenv("FATSECRET_CONSUMER_KEY")
fatsecret_consumer_secret = os.getenv("FATSECRET_CONSUMER_SECRET")

# API requests to FatSecret

def create_auth_url(consumer_key: str, consumer_secret: str) -> tuple[str, str, str]:
    if not consumer_key:
        raise RuntimeError("FatSecret consumer key is missing")

    if not consumer_secret:
        raise RuntimeError("FatSecret consumer secret is missing")
    oauth = OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        callback_uri="oob",
        signature_method=SIGNATURE_HMAC,
        signature_type=SIGNATURE_TYPE_BODY,
    )

    request_tokens = oauth.fetch_request_token(
        "https://authentication.fatsecret.com/oauth/request_token"
    )

    request_token = request_tokens["oauth_token"]
    request_token_secret = request_tokens["oauth_token_secret"]

    authorization_url = oauth.authorization_url(
        "https://authentication.fatsecret.com/oauth/authorize"
    )

    return authorization_url, request_token, request_token_secret

def exchange_verifier_for_access_token(consumer_key: str, consumer_secret: str, request_token: str, request_token_secret: str, verifier: str) -> tuple[str, str]:
    oauth = OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=request_token,
        resource_owner_secret=request_token_secret,
        verifier=verifier,
        signature_method=SIGNATURE_HMAC,
        signature_type=SIGNATURE_TYPE_QUERY,
    )

    response = oauth.get("https://authentication.fatsecret.com/oauth/access_token")

    print("FatSecret status:", response.status_code)
    print("FatSecret response:", response.text)

    response.raise_for_status()

    response_data = parse_qs(response.text)

    access_token = response_data.get('oauth_token')[0]
    access_token_secret = response_data.get('oauth_token_secret')[0]

    return access_token, access_token_secret


# Telegram API handlers

async def connect_fatsecret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    authorization_url, request_token, request_token_secret = (
        await asyncio.to_thread(create_auth_url, fatsecret_consumer_key, fatsecret_consumer_secret)
    )

    context.user_data["fatsecret_request_token"] = request_token
    context.user_data["fatsecret_request_token_secret"] = request_token_secret
    context.user_data["waiting_fatsecret_verifier"] = True

    language = context.user_data.get('language', 'en')

    if language == 'ru':
        text = (
            "Пожалуйста, перейдите по следующей ссылке, чтобы авторизовать бота в FatSecret:\n"
            f"{authorization_url}\n\n"
            "После авторизации вы получите код. Пожалуйста, отправьте этот код в чат."
        )
        btn_text = "Подключить FatSecret"
    else:
        text = (
            "Please visit the following link to authorize the bot with FatSecret:\n"
            f"{authorization_url}\n\n"
            "After authorization, you will receive a verifier code. Please send this code to the chat."
        )
        btn_text = "Connect FatSecret"

    keyboard = [
        [
            InlineKeyboardButton(btn_text, url=authorization_url)
        ]
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_fatsecret_verifier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = context.user_data.get('language', 'en')
    if language == 'ru':
        text_error = "Данные авторизации потеряны. Выполните /connnect еще раз."
        text_error_1 = "Не удалось завершить авторизацию. Проверьте код или выполните /connnect еще раз."
        text_success = "FatSecret успешно подключён!"
    else:
        text_error = "Authorization data lost. Please run /connect again."
        text_error_1 = "Failed to complete authorization. Please check the code or run /connect again."
        text_success = "FatSecret connected successfully!"


    waiting_for_code = context.user_data.get("waiting_fatsecret_verifier", False)

    if not waiting_for_code:
        return
    verifier_code = update.message.text.strip()

    request_token = context.user_data.get("fatsecret_request_token")
    request_token_secret = context.user_data.get("fatsecret_request_token_secret")

    if not request_token or not request_token_secret:
        await update.message.reply_text(text_error)
        return
    
    try:
        access_token, access_token_secret = await asyncio.to_thread(
            exchange_verifier_for_access_token,
            fatsecret_consumer_key,
            fatsecret_consumer_secret,
            request_token,
            request_token_secret,
            verifier_code
        )
    
    except Exception as error:
        print(f"FatSecret authorization error: {error}")

        await update.message.reply_text(text_error_1)
        return
    
     # Только временно для теста
    context.user_data["fatsecret_access_token"] = access_token
    context.user_data["fatsecret_access_token_secret"] = (
        access_token_secret
    )

    context.user_data.pop("fatsecret_request_token", None)
    context.user_data.pop("fatsecret_request_token_secret", None)
    context.user_data.pop("waiting_fatsecret_verifier", None)

    await update.message.reply_text(text_success)
#Telegram bot handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [
            InlineKeyboardButton("RU Русский", callback_data='language_ru'),
            InlineKeyboardButton("EN English", callback_data='language_en'),

        ]
    ]

    await update.message.reply_text(
        'Выберите ваш язык / Choose your language:',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    await query.answer()
    
    if query.data == 'language_ru':
        context.user_data['language'] = 'ru'
        await query.edit_message_text(text="Вы выбрали русский язык.")
        
    elif query.data == 'language_en':
        context.user_data['language'] = 'en'
        await query.edit_message_text(text="You selected English language.")
    
    await show_next_step(update, context)


async def show_next_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = context.user_data.get('language')

    if language == 'ru':
        text = "Пришлите фото вашего блюда в чат. По желанию добавьте описание блюда в подписи к фото. \n Например: Куриная грудка, рис и немного соуса"
    elif language == 'en':
        text = "Please send a photo of your dish in the chat. Optionally, you can add a description of the dish in the photo caption. \n For example: Chicken breast, rice, and a bit of sauce"

    await update.effective_message.reply_text(text)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = context.user_data.get('language', "en")

    photo = update.message.photo[-1]
    caption = update.message.caption or ""

    file_path = PHOTO_DIR / f"{photo.file_unique_id}.jpg"

    telegram_file = await context.bot.get_file(photo.file_id)
    await telegram_file.download_to_drive(file_path)

    context.user_data["pending_photo_path"] = str(file_path)
    context.user_data["pending_photo_caption"] = caption

    await show_photo_confirmation(update, context, file_path, caption)


async def show_photo_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, file_path: Path, caption: str) -> None:
    language = context.user_data.get('language', "en")
    if language == 'ru':
        btn_text_confirm = "Подтвердить"
        btn_text_cancel = "Отменить"
    else:
        btn_text_confirm = "Confirm"
        btn_text_cancel = "Cancel"

    keyboard = [
        [
            InlineKeyboardButton(btn_text_confirm, callback_data='photo_confirm'),
            InlineKeyboardButton(btn_text_cancel, callback_data='photo_reject')
        ]
    ]

    confirmation_text = (
            f"Описание: {caption or 'не указано'}\n\n"
            "Всё верно?"
        )
    
    with file_path.open('rb') as photo_file:
        await update.effective_message.reply_photo(
            photo=photo_file,
            caption=confirmation_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_photo_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await query.answer()

    language = context.user_data.get("language", "en")
    file_path_value = context.user_data.get("pending_photo_path")
    original_caption = context.user_data.get(
        "pending_photo_caption",
        "",
    )

    if language == "ru":
        text_confirm = (
            f"Описание: {original_caption or 'не указано'}\n\n"
            "Подтверждено."
        )
        text_reject = (
            "Фото отклонено. Пожалуйста, отправьте новое фото."
        )
    else:
        text_confirm = (
            f"Description: {original_caption or 'not provided'}\n\n"
            "Confirmed."
        )
        text_reject = (
            "Photo rejected. Please send a new photo."
        )

    if query.data == "photo_confirm":
        await query.edit_message_caption(
            caption=text_confirm,
            reply_markup=None,
        )

    elif query.data == "photo_reject":
        if file_path_value:
            file_path = Path(file_path_value)
            file_path.unlink(missing_ok=True)

        await query.edit_message_caption(
            caption=text_reject,
            reply_markup=None,
        )

    context.user_data.pop("pending_photo_path", None)
    context.user_data.pop("pending_photo_caption", None)

app = Application.builder().token(telegram_api_key).build()

app.add_handler(CommandHandler("start", start))

app.add_handler(
    CallbackQueryHandler(
        select_language,
        pattern=r"^language_(ru|en)$",
    )
)

app.add_handler(
    CallbackQueryHandler(
        handle_photo_confirmation,
        pattern=r"^photo_(confirm|reject)$",
    )
)

app.add_handler(
    MessageHandler(
        filters.PHOTO,
        handle_photo,
    )
)

app.add_handler(
    CommandHandler(
        "connect",
        connect_fatsecret,
    )
)

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_fatsecret_verifier,
    )
)

app.run_polling()

