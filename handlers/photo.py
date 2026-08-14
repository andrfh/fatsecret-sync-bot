from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    ContextTypes
)
from io import BytesIO

from repositories.user_repository import get_user
from handlers.menu import build_main_menu

WAITING_PHOTO = 1
WAITING_CONFIRM = 2

def build_photo_screen(language: str) -> tuple[str, InlineKeyboardMarkup]:
    if language == "ru":
        screen_text = "Сфотографируйте Ваш прием пищи и загрузите фотографию в чат. \n Для лучшего результата добавьте описание блюда (примерный вес, ингридиенты, размер тарелки)."
        screen_btn = "Отмена"
    elif language == "en":
        screen_text = "Take a photo of your meal and upload it to the chat. \nFor best results, add a description of the dish (approximate weight, ingredients, plate size)." 
        screen_btn = "Cancel"

    keyboard = [
        [
            InlineKeyboardButton(screen_btn, callback_data='photo_cancel')           
        ]
    ]

    return screen_text, InlineKeyboardMarkup(keyboard)

async def open_photo_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    screen_text, markup = build_photo_screen(language)
    await query.edit_message_text(screen_text, reply_markup = markup)

    return WAITING_PHOTO
    
async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query

    if language == "ru":
        confirm_text = f"Подтвердите правильность запроса:\nОписание: <i>{description}</i>"
        error_text = "Не удалось загрузить фото, попробуйте ещё раз"
        confirm_btn_approve = "Готово"
        confirm_btn_update = "Отправить заново"
        confirm_btn_cancel = "Отмена"
    elif language == "en":
        confirm_text = f"Confirm the request is correct:\nDescription: <i>{description}</i>"
        error_text = "Failed to upload photo, try again"
        confirm_btn_approve = "Done"
        confirm_btn_update = "Resend"
        confirm_btn_cancel = "Cancel"

    photo = update.message.photo[-1]
    if update.message.caption:
        description = update.message.caption 
    else:
        if language == "ru":
            description = "Отсутствует"
        elif language == "en":
            description = "No description"

    try:
        telegram_file = await photo.get_file()
        buffer = BytesIO()
        await telegram_file.download_to_memory(buffer)

        image_bytes = buffer.getvalue()

        buffer.seek(0)

        context.user_data["meal_photo_bytes"] = image_bytes
        context.user_data["meal_photo_file_id"] = photo.file_id
        context.user_data["meal_description"] = description
    except:
        await update.message.reply_text(error_text)

    keyboard = [
            [
                InlineKeyboardButton(confirm_btn_approve, callback_data='confirm_btn_approve')           
            ],
            [
                InlineKeyboardButton(confirm_btn_update, callback_data='confirm_btn_update')           
            ],
            [
                InlineKeyboardButton(confirm_btn_cancel, callback_data='confirm_btn_cancel')           
            ]
        ]

    

    await update.message.reply_photo(
        photo=photo.file_id,
        caption=confirm_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML" 
    )

    return WAITING_CONFIRM

async def confirm_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("Назад в меню", callback_data="menu_back")
        ]
    ]

    if query.data == "confirm_btn_approve":
        context.user_data.pop("meal_photo_bytes", None)
        context.user_data.pop("meal_photo_file_id", None)
        context.user_data.pop("meal_description", None)

        await query.delete_message()

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Фото принято. Распознавание будет добавлено на следующем этапе",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return ConversationHandler.END
    elif query.data == "confirm_btn_update":
        await query.delete_message()

        context.user_data.pop("meal_photo_bytes", None)
        context.user_data.pop("meal_photo_file_id", None)
        context.user_data.pop("meal_description", None)
        
        menu_text, markup = build_photo_screen(language)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=menu_text,
            reply_markup=markup,
        )

        return WAITING_PHOTO
    elif query.data == "confirm_btn_cancel":
        await query.delete_message()

        context.user_data.pop("meal_photo_bytes", None)
        context.user_data.pop("meal_photo_file_id", None)
        context.user_data.pop("meal_description", None)

        menu_text, markup = build_main_menu(language)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=menu_text,
            reply_markup=markup,
        )

        return ConversationHandler.END
    
async def photo_exception(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    if language == "ru":
        text = "Пожалуйста, отправьте фотографию."
    elif language == "en":
        text = "Please, send the photo."
    await update.message.reply_text(text)
    return WAITING_PHOTO

async def cancel_photo_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    menu_text, markup = build_main_menu(language)
    await query.edit_message_text(menu_text, reply_markup=markup) 
    
    return ConversationHandler.END