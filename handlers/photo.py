from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import MessageLimit
from telegram.error import NetworkError, BadRequest
from telegram.ext import (
    ConversationHandler,
    ContextTypes
)
from io import BytesIO

from html import escape

import asyncio
import logging

from repositories.user_repository import get_user
from handlers.menu import build_main_menu
from handlers.start import start
from ui.texts import text

from services.gemini_service import recognize_meal
from services.gemini_service import search_food
from services.gemini_service import GeminiTemporarilyUnavailable
from services.fatsecret_food_service import fatsecret_create_entry
from services.usage_service import consume_meal_attempt

WAITING_PHOTO = 1
WAITING_CONFIRM = 2
WAITING_MEAL_TYPE = 3
logger = logging.getLogger(__name__)


async def answer_meal_callback(query):
    try:
        await query.answer()
    except NetworkError as error:
        # The spinner acknowledgement does not change the user's selection.
        # BadRequest is a NetworkError subclass; only an expired callback is safe here.
        if isinstance(error, BadRequest) and "query is too old" not in str(error).lower():
            raise
        logger.warning("Could not acknowledge meal callback: %s", type(error).__name__)

def build_photo_screen(language: str) -> tuple[str, InlineKeyboardMarkup]:
    return text(language, "input"), InlineKeyboardMarkup([[
        InlineKeyboardButton(text(language, "cancel_meal"), callback_data="photo_cancel")
    ]])


def build_confirm_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text(language, "approve"), callback_data="confirm_btn_approve")],
        [InlineKeyboardButton(text(language, "resend"), callback_data="confirm_btn_update")],
        [InlineKeyboardButton(text(language, "cancel_meal"), callback_data="confirm_btn_cancel")],
    ])


def build_mealtype_screen(language: str) -> tuple[str, InlineKeyboardMarkup]:
    return text(language, "choose_meal"), InlineKeyboardMarkup([
        [InlineKeyboardButton(text(language, meal), callback_data=f"meal_type-{meal}")
         for meal in ("breakfast", "lunch", "dinner", "other")],
        [InlineKeyboardButton(text(language, "cancel_meal"), callback_data="meal_cancel")],
    ])


async def start_proccess(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    if user is None or user.language not in ("ru", "en") or not user.fatsecret_token or not user.fatsecret_token_secret:
        await start(update, context)
        return ConversationHandler.END
    language = user.language
    if update.callback_query:
        await update.callback_query.answer()
    context.user_data.pop("meal_photo_bytes", None)
    context.user_data.pop("meal_photo_file_id", None)
    context.user_data.pop("meal_description", None)
    context.user_data.pop("meal_type", None)
    screen, markup = build_photo_screen(language)
    await update.callback_query.edit_message_text(screen, reply_markup=markup)
    return WAITING_PHOTO


async def select_meal_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    language = get_user(update.effective_user.id).language
    query = update.callback_query
    await answer_meal_callback(query)
    meal_type = query.data.removeprefix("meal_type-")
    context.user_data["meal_type"] = meal_type
    await send_meal_confirmation(
        context.bot, update.effective_chat.id, language,
        context.user_data["meal_description"], meal_type,
        photo=context.user_data.get("meal_photo_file_id"),
    )
    try:
        await query.delete_message()
    except NetworkError as error:
        # Confirmation is already sent: retain WAITING_CONFIRM even if cleanup fails.
        logger.warning("Could not delete meal selection message: %s", type(error).__name__)
    return WAITING_CONFIRM


async def meal_type_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    language = get_user(update.effective_user.id).language
    await update.message.reply_text(text(language, "meal_reminder"))
    return WAITING_MEAL_TYPE


async def confirm_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    language = get_user(update.effective_user.id).language
    await update.message.reply_text(text(language, "confirm_reminder"))
    return WAITING_CONFIRM


async def send_meal_confirmation(bot, chat_id: int, language: str, description: str, meal_type: str, photo=None):
    prefix = text(language, "confirm_prefix", meal=text(language, meal_type))
    display_description = description or text(language, "no_description")
    suffix = text(language, "confirm_suffix")

    keyboard = build_confirm_keyboard(language)
    confirm_text = f"{prefix}<i>{escape(display_description)}</i>{suffix}"
    caption_length = len((prefix + display_description + suffix).encode("utf-16-le")) // 2

    if photo is not None and caption_length <= MessageLimit.CAPTION_LENGTH:
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=confirm_text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    if photo is not None:
        await bot.send_photo(chat_id=chat_id, photo=photo)

    # Keep even emoji-heavy descriptions within the text limit, without losing text.
    chunks = [display_description[i:i + 1800] for i in range(0, len(display_description), 1800)]
    for index, chunk in enumerate(chunks):
        await bot.send_message(
            chat_id=chat_id,
            text=f"{prefix if index == 0 else ''}<i>{escape(chunk)}</i>{suffix if index == len(chunks) - 1 else ''}",
            reply_markup=keyboard if index == len(chunks) - 1 else None,
            parse_mode="HTML",
        )


async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    if (user is None or user.language not in ("ru", "en")
            or not user.fatsecret_token or not user.fatsecret_token_secret):
        context.user_data.pop("meal_photo_bytes", None)
        context.user_data.pop("meal_photo_file_id", None)
        context.user_data.pop("meal_description", None)
        context.user_data.pop("meal_type", None)
        await start(update, context)
        await update.message.reply_text(text(user.language if user else "ru", "setup_again"))
        return ConversationHandler.END
    language = user.language
    photo = update.message.photo[-1] if update.message.photo else None
    description = ((update.message.caption if photo else update.message.text) or "").strip()

    if photo is None and not description:
        return await photo_exception(update, context)

    # A new text request must not reuse an image from an earlier request.
    context.user_data.pop("meal_photo_bytes", None)
    context.user_data.pop("meal_photo_file_id", None)
    context.user_data.pop("meal_description", None)
    context.user_data.pop("meal_type", None)

    image_bytes = None
    error_text = text(language, "download_error")

    if photo is not None:
        try:
            telegram_file = await photo.get_file()
            buffer = BytesIO()
            await telegram_file.download_to_memory(buffer)
            image_bytes = buffer.getvalue()
        except Exception as error:
            await update.message.reply_text(error_text)
            return WAITING_PHOTO

        context.user_data["meal_photo_file_id"] = photo.file_id

    context.user_data["meal_photo_bytes"] = image_bytes
    context.user_data["meal_description"] = description

    meal_text, meal_markup = build_mealtype_screen(language)
    await update.message.reply_text(meal_text, reply_markup=meal_markup)
    return WAITING_MEAL_TYPE

async def confirm_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await answer_meal_callback(query)

    user = get_user(telegram_id)

    error_text = text(language, "analysis_error")
    error_entry = text(language, "entry_error")
    access_error_text = text(language, "access_error")
    analyze_step1 = text(language, "analysis")
    analyze_step2 = text(language, "search")
    analyze_step3 = text(language, "saving")
    analyze_ready = text(language, "success", meal=text(language, context.user_data.get("meal_type", "other")))
    analyze_not_food = text(language, "not_food")
    analyze_too_complex = text(language, "too_complex")
    analyze_uncertain = text(language, "uncertain")
    back_to_menu = text(language, "menu_button")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                back_to_menu,
                callback_data="menu_back"
            )
        ]
    ])

    if query.data == "confirm_btn_approve":
        await query.delete_message()
        image_bytes = context.user_data.get("meal_photo_bytes")
        description = context.user_data["meal_description"]
        meal_type = context.user_data["meal_type"]

        user_token = user.fatsecret_token
        user_token_secret = user.fatsecret_token_secret

        chat_id = update.effective_chat.id

        status_message = await context.bot.send_message(
            chat_id=chat_id,
            text=analyze_step1,
        )
        stage = analyze_step1

        async def report_retry(attempt, total):
            try:
                await status_message.edit_text(stage + "\n\n" + text(
                    language, "service_retry", attempt=attempt, total=total))
            except NetworkError:
                logger.warning("Could not update Gemini retry status in Telegram")

        try:
            usage = await asyncio.to_thread(consume_meal_attempt, telegram_id)
            if not usage.allowed:
                await status_message.edit_text(
                    text(language, "daily_limit_reached"),
                    reply_markup=build_confirm_keyboard(language),
                )
                return WAITING_CONFIRM

            recognized_meal = await recognize_meal(image_bytes, description, meal_type, on_retry=report_retry)

            print(recognized_meal)

            if recognized_meal["status"] == "not_food":
                await status_message.edit_text(
                    analyze_not_food,
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
                context.user_data.pop("meal_type", None)
        
                return ConversationHandler.END

            elif recognized_meal["status"] == "too_complex":
                await status_message.edit_text(
                    analyze_too_complex,
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
                context.user_data.pop("meal_type", None)
        
                return ConversationHandler.END

            elif recognized_meal["status"] == "uncertain":
                await status_message.edit_text(
                    analyze_uncertain,
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
                context.user_data.pop("meal_type", None)
        
                return ConversationHandler.END


            await status_message.edit_text(analyze_step2)
            stage = analyze_step2
            fatsecret_meal = await search_food(recognized_meal, language, on_retry=report_retry)

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
                await status_message.edit_text(
                    text(language, "partial_error", success=entries_resposnes.count("success"), total=len(entries_resposnes)),
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
                context.user_data.pop("meal_type", None)

                return ConversationHandler.END
        
            elif "error" in entries_resposnes:
                await status_message.edit_text(
                    error_entry,
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
                context.user_data.pop("meal_type", None)

                return ConversationHandler.END

        except GeminiTemporarilyUnavailable:
            # Both Gemini stages precede diary writes; retrying here cannot duplicate entries.
            await status_message.edit_text(text(language, "service_busy"),
                                           reply_markup=build_confirm_keyboard(language))
            return WAITING_CONFIRM
        except Exception as error:
            print(error)
            message = access_error_text if "User location is not supported for the API use." in str(error) else error_text
            await status_message.edit_text(message)
            await send_meal_confirmation(
                context.bot, chat_id, language, description, meal_type,
                photo=BytesIO(image_bytes) if image_bytes is not None else None,
            )
            return WAITING_CONFIRM
    
        await status_message.edit_text(
            analyze_ready,
            reply_markup=keyboard
        )

        context.user_data.pop("meal_photo_bytes", None)
        context.user_data.pop("meal_photo_file_id", None)
        context.user_data.pop("meal_description", None)
        context.user_data.pop("meal_type", None)

        return ConversationHandler.END

    elif query.data == "confirm_btn_update":
        await query.delete_message()

        context.user_data.pop("meal_photo_bytes", None)
        context.user_data.pop("meal_photo_file_id", None)
        context.user_data.pop("meal_description", None)
        context.user_data.pop("meal_type", None)
        
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
        context.user_data.pop("meal_type", None)

        menu_text, markup = build_main_menu(language)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text(language, "meal_cancelled") + "\n\n" + menu_text,
            reply_markup=markup,
        )

        return ConversationHandler.END
    
async def photo_exception(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    await update.message.reply_text(text(language, "input_error"))
    return WAITING_PHOTO

async def cancel_photo_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await query.answer()

    context.user_data.pop("meal_photo_bytes", None)
    context.user_data.pop("meal_photo_file_id", None)
    context.user_data.pop("meal_description", None)
    context.user_data.pop("meal_type", None)

    menu_text, markup = build_main_menu(language)
    await query.edit_message_text(text(language, "meal_cancelled") + "\n\n" + menu_text, reply_markup=markup)
    
    return ConversationHandler.END
