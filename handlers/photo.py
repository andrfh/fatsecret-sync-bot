from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    ContextTypes
)
from io import BytesIO

from html import escape

import asyncio

from repositories.user_repository import get_user
from handlers.menu import build_main_menu

from services.gemini_service import recognize_meal
from services.gemini_service import search_food
from services.fatsecret_food_service import fatsecret_create_entry

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

def build_confirm_keyboard(language: str) -> InlineKeyboardMarkup:
    if language == "ru":
        confirm_btn_approve = "Готово"
        confirm_btn_update = "Отправить заново"
        confirm_btn_cancel = "Отмена"
        
    elif language == "en":
        confirm_btn_approve = "Done"
        confirm_btn_update = "Resend"
        confirm_btn_cancel = "Cancel"

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

    return InlineKeyboardMarkup(keyboard)

def build_mealtype_screen(language: str) -> tuple[str, InlineKeyboardMarkup]:
    if language == "ru":
        meal_text = "Выберите прием пищи:"
        meal_breakfast = "Завтрак"
        meal_lunch = "Обед"
        meal_dinner = "Ужин"
        meal_other = "Перекус/Другое"
        meal_cancel = "Вернуться в меню"
        
    elif language == "en":
        meal_text = "Select meal:"
        meal_breakfast = "Breakfast" 
        meal_lunch = "Lunch" 
        meal_dinner = "Dinner" 
        meal_other = "Snack/Other"
        meal_cancel = "Back to menu"

    keyboard = [
        [
            InlineKeyboardButton(meal_breakfast, callback_data='meal_type-breakfast'),
            InlineKeyboardButton(meal_lunch, callback_data='meal_type-lunch'),
            InlineKeyboardButton(meal_dinner, callback_data='meal_type-dinner'),     
            InlineKeyboardButton(meal_other, callback_data='meal_type-other')  
        ],
        [
            InlineKeyboardButton(meal_cancel, callback_data='meal_cancel') 
        ]
    ]

    return meal_text, InlineKeyboardMarkup(keyboard)

async def start_proccess(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    if "meal_type" in query.data:
        context.user_data["meal_type"] = query.data[10:]
        photo_text, photo_markup = build_photo_screen(language)
        await query.edit_message_text(photo_text, reply_markup = photo_markup)
    
        return WAITING_PHOTO
    
    elif query.data == "meal_cancel":
        menu_text, menu_markup = build_main_menu(language)
        await query.edit_message_text(menu_text, reply_markup=menu_markup) 
        
        return ConversationHandler.END
    else:
        meal_text, meal_markup = build_mealtype_screen(language)
        await query.edit_message_text(meal_text, reply_markup=meal_markup)
        return WAITING_PHOTO
        
    
    
async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language

    if language == "ru":
        no_description_text = "Отсутствует"
    elif language == "en":
        no_description_text = "No description"

    description = update.message.caption or no_description_text
    safe_description = escape(description)

    if language == "ru":
        confirm_text = f"Подтвердите правильность запроса:\nОписание: <i>{safe_description}</i>"
        error_text = "Не удалось загрузить фото, попробуйте ещё раз"
        
    elif language == "en":
        confirm_text = f"Confirm the request is correct:\nDescription: <i>{safe_description}</i>"
        error_text = "Failed to upload photo, try again"
        
    photo = update.message.photo[-1]

    keyboard = build_confirm_keyboard(language)
    
    try:
        telegram_file = await photo.get_file()
        buffer = BytesIO()
        await telegram_file.download_to_memory(buffer)

        image_bytes = buffer.getvalue()

        context.user_data["meal_photo_bytes"] = image_bytes
        context.user_data["meal_photo_file_id"] = photo.file_id
        context.user_data["meal_description"] = description

    except Exception as error:
        await update.message.reply_text(error_text)
        return WAITING_PHOTO    

    await update.message.reply_photo(
        photo=photo.file_id,
        caption=confirm_text,
        reply_markup=keyboard,
        parse_mode="HTML" 
    )

    return WAITING_CONFIRM

async def confirm_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    user = get_user(telegram_id)

    if language == "ru":
        error_text = "Что-то пошло не так. Пожалуйста, попробуйте еще раз"
        error_entry = "Ошибка FatSecret. Блюда не были добавлены. Попробуйте добавить заново"
        error_half = "Ошибка FatSecret. Часть блюда не были добавлены."
        access_error_text = "Доступ к нейросети из Вашего региона недоступен. Попробуйте включить VPN или отключите (настройте) раздельное туннелирование."
        analyze_step1 = "⏳ Анализирую фотографию..."
        analyze_step2 = "✅ Блюдо распознано!\n⏳ Ищу подходящие продукты в FatSecret..."
        analyze_step3 = "✅ Блюдо распознано!\n✅ Продукты найдены! \n⏳ Добавляю блюдо в FatSecret..."
        analyze_ready = "✅ Блюдо успешно добавлено!"
        analyze_not_food = "ИИ не обнаружил на фотографии еду."
        analyze_too_complex = "На фотографии изображено слишком много блюд."
        analyze_uncertain = "Фотография слишком плохого качества."

    elif language == "en":
        error_text = "Something went wrong. Please try again" 
        error_entry = "FatSecret error. Items were not added. Please try adding them again."
        error_half = "FatSecret error. Some items were not added."
        access_error_text = "Access to the neural network from your region is not available. Try enabling VPN or disabling (configuring) split tunneling."
        analyze_step1 = "⏳ Analyzing the photo..."
        analyze_step2 = "✅ Dish recognized!\n⏳ Searching for matching items in FatSecret..."
        analyze_step3 = "✅ Dish recognized!\n✅ Items found! \n⏳ Adding the dish to FatSecret..."
        analyze_ready = "✅ Dish successfully added!"
        analyze_not_food = "The AI ​​did not detect any food in the photo."
        analyze_too_complex = "There are too many dishes in the photo."
        analyze_uncertain = "The photo quality is too poor."

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Назад в меню",
                callback_data="menu_back"
            )
        ]
    ])

    if query.data == "confirm_btn_approve":
        await query.delete_message()
        image_bytes = context.user_data["meal_photo_bytes"]
        description = context.user_data["meal_description"]
        meal_type = context.user_data["meal_type"]

        user_token = user.fatsecret_token
        user_token_secret = user.fatsecret_token_secret

        chat_id = update.effective_chat.id

        status_message = await context.bot.send_message(
            chat_id=chat_id,
            text= analyze_step1
        )
        try:
            recognized_meal = await recognize_meal(image_bytes, description, meal_type)

            print(recognized_meal)

            if recognized_meal["status"] == "not_food":
                await status_message.edit_text(
                    analyze_not_food,
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
        
                return ConversationHandler.END

            elif recognized_meal["status"] == "too_complex":
                await status_message.edit_text(
                    analyze_too_complex,
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
        
                return ConversationHandler.END

            elif recognized_meal["status"] == "uncertain":
                await status_message.edit_text(
                    analyze_uncertain,
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
        
                return ConversationHandler.END


            await status_message.edit_text(analyze_step2)

            fatsecret_meal = await search_food(recognized_meal, language)

            print(fatsecret_meal)

            await status_message.edit_text(analyze_step3)

            entries_resposnes = []

            for food in fatsecret_meal["foods"]:
                response = await asyncio.to_thread(
                    fatsecret_create_entry,
                    user_token = user_token,
                    user_token_secret = user_token_secret,
                    food_id = food["food_id"],
                    food_entry_name=food["food_name"],
                    serving_id = food["serving_id"],
                    number_of_units = food["number_of_units"],
                    meal = meal_type
                )
                entries_resposnes.append(response["status"])
            
            if "error" in entries_resposnes and "success" in entries_resposnes:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=error_half
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)

                return ConversationHandler.END
        
            elif "error" in entries_resposnes:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=error_entry
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)

                return ConversationHandler.END

        except Exception as error:
            print(error)

            await status_message.edit_text(error_text)

            photo = BytesIO(image_bytes)

            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                reply_markup=build_confirm_keyboard(language)
            )

            if "User location is not supported for the API use." in str(error):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=access_error_text
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=error_text
                )
            return WAITING_CONFIRM
    
        await status_message.edit_text(
            analyze_ready,
            reply_markup=keyboard
        )

        context.user_data.pop("meal_photo_bytes", None)
        context.user_data.pop("meal_photo_file_id", None)
        context.user_data.pop("meal_description", None)

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
