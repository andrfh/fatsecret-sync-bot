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
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4
from services.meal_state import (clear_meal_data, create_meal_draft,
                                 close_pending_meal_write, meal_draft_expired,
                                 meal_state_handler)

from repositories.user_repository import get_user
from handlers.menu import build_main_menu
from handlers.start import start
from ui.texts import text
from config import DAILY_MEAL_ATTEMPT_LIMIT

from services.gemini_service import recognize_meal
from services.gemini_service import search_food
from services.gemini_service import GeminiTemporarilyUnavailable
from services.matching_operation import UnverifiedFoodSelection
from services.fatsecret_food_service import fatsecret_create_entry
from services.usage_service import consume_meal_attempt
from repositories.write_operation_repository import (
    claim_write_operation,
    close_pending_write_operation,
    create_write_operation,
    finish_write_operation,
)

WAITING_PHOTO = 1
WAITING_CONFIRM = 2
WAITING_MEAL_TYPE = 3
WAITING_FINAL_REVIEW = 4
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


def _number(value: float) -> str:
    rounded = round(float(value), 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"


def _review_keyboard(language: str, operation_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text(language, "write_entries"),
                              callback_data=f"meal_write:{operation_id}")],
        [InlineKeyboardButton(text(language, "cancel_meal"),
                              callback_data=f"meal_write_cancel:{operation_id}")],
    ])


def build_final_review_screen(language: str, foods: list[dict], meal_type: str,
                              operation_id: str) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        text(language, "review_title"),
        text(language, "review_meal", meal=escape(text(language, meal_type))),
        "",
    ]
    totals = {key: 0.0 for key in
              ("calories_kcal", "protein_g", "fat_g", "carbohydrate_g")}
    for index, food in enumerate(foods, start=1):
        review = food["review"]
        nutrition = review["nutrition"]
        for key in totals:
            totals[key] += nutrition[key]
        entry = review["entry_quantity"]
        serving = review["serving_description"] or text(language, "review_serving_unknown")
        lines.extend([
            f"<b>{index}. {escape(review['food_name'])}</b>",
            text(language, "review_serving", serving=escape(serving)),
            text(language, "review_quantity", value=_number(entry["value"]),
                 unit=escape(entry["unit"] or "")),
            text(language, "review_mass", mass=_number(review["mass_g"])),
            text(language, "review_macros", calories=_number(nutrition["calories_kcal"]),
                 protein=_number(nutrition["protein_g"]), fat=_number(nutrition["fat_g"]),
                 carbs=_number(nutrition["carbohydrate_g"])),
            "",
        ])
    lines.extend([
        text(language, "review_total", calories=_number(totals["calories_kcal"]),
             protein=_number(totals["protein_g"]), fat=_number(totals["fat_g"]),
             carbs=_number(totals["carbohydrate_g"])),
        "",
        text(language, "review_warning"),
        text(language, "fatsecret_attribution"),
    ])
    return "\n".join(lines), _review_keyboard(language, operation_id)


def _menu_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(text(language, "menu_button"), callback_data="menu_back")
    ]])


def _with_usage_notice(language: str, message: str, remaining_or_data) -> str:
    remaining = (remaining_or_data.get("_meal_usage_remaining")
                 if isinstance(remaining_or_data, dict) else remaining_or_data)
    if not isinstance(remaining, int):
        return message
    notice = text(
        language,
        "usage_remaining",
        remaining=remaining,
        limit=DAILY_MEAL_ATTEMPT_LIMIT,
    )
    return f"{message}\n\n{notice}"


def build_mealtype_screen(language: str) -> tuple[str, InlineKeyboardMarkup]:
    return text(language, "choose_meal"), InlineKeyboardMarkup([
        [InlineKeyboardButton(text(language, meal), callback_data=f"meal_type-{meal}")
         for meal in ("breakfast", "lunch", "dinner", "other")],
        [InlineKeyboardButton(text(language, "cancel_meal"), callback_data="meal_cancel")],
    ])


@meal_state_handler
async def start_proccess(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    clear_meal_data(context.user_data)
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
    await update.callback_query.edit_message_text(screen, reply_markup=markup, parse_mode="HTML")
    return WAITING_PHOTO


@meal_state_handler
async def select_meal_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "meal_description" not in context.user_data or meal_draft_expired(context.user_data):
        return await expired_meal(update, context)
    language = get_user(update.effective_user.id).language
    query = update.callback_query
    await answer_meal_callback(query)
    meal_type = query.data.removeprefix("meal_type-")
    context.user_data["meal_type"] = meal_type
    context.user_data["_meal_action_state"] = "awaiting_analysis"
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


@meal_state_handler
async def meal_type_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "meal_description" not in context.user_data or meal_draft_expired(context.user_data):
        return await expired_meal(update, context)
    language = get_user(update.effective_user.id).language
    await update.message.reply_text(text(language, "meal_reminder"))
    return WAITING_MEAL_TYPE


@meal_state_handler
async def confirm_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "meal_description" not in context.user_data or meal_draft_expired(context.user_data):
        return await expired_meal(update, context)
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


@meal_state_handler
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
    photo_file_id = None
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

        photo_file_id = photo.file_id

    create_meal_draft(context.user_data)
    context.user_data["_meal_telegram_id"] = telegram_id
    context.user_data["_meal_action_state"] = "choosing_meal_type"
    if photo_file_id is not None:
        context.user_data["meal_photo_file_id"] = photo_file_id
    context.user_data["meal_photo_bytes"] = image_bytes
    context.user_data["meal_description"] = description

    meal_text, meal_markup = build_mealtype_screen(language)
    await update.message.reply_text(meal_text, reply_markup=meal_markup, parse_mode="HTML")
    return WAITING_MEAL_TYPE

@meal_state_handler
async def confirm_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action_state = context.user_data.get("_meal_action_state")
    if action_state == "awaiting_write_confirmation":
        await answer_meal_callback(update.callback_query)
        return WAITING_FINAL_REVIEW
    if "meal_description" not in context.user_data or meal_draft_expired(context.user_data):
        return await expired_meal(update, context)
    started = monotonic()
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    await answer_meal_callback(query)

    user = get_user(telegram_id)

    error_text = text(language, "analysis_error")
    analyze_step1 = text(language, "analysis")
    analyze_step2 = text(language, "search")
    analyze_not_food = text(language, "not_food")
    analyze_too_complex = text(language, "too_complex")
    analyze_uncertain = text(language, "uncertain")
    keyboard = _menu_keyboard(language)

    if query.data == "confirm_btn_approve":
        if action_state != "awaiting_analysis":
            return WAITING_CONFIRM
        context.user_data["_meal_action_state"] = "matching"
        await query.delete_message()
        image_bytes = context.user_data.get("meal_photo_bytes")
        description = context.user_data["meal_description"]
        meal_type = context.user_data["meal_type"]

        chat_id = update.effective_chat.id

        status_message = await context.bot.send_message(
            chat_id=chat_id,
            text=analyze_step1,
        )
        stage = analyze_step1
        usage_remaining = None

        async def report_retry(attempt, total):
            try:
                await status_message.edit_text(stage + "\n\n" + text(
                    language, "service_retry", attempt=attempt, total=total))
            except NetworkError:
                logger.warning("Could not update Gemini retry status in Telegram")

        try:
            usage = await asyncio.to_thread(consume_meal_attempt, telegram_id)
            if not usage.allowed:
                context.user_data["_meal_action_state"] = "awaiting_analysis"
                await status_message.edit_text(
                    text(language, "daily_limit_reached", limit=DAILY_MEAL_ATTEMPT_LIMIT),
                    reply_markup=build_confirm_keyboard(language),
                )
                return WAITING_CONFIRM
            if not usage.is_premium:
                usage_remaining = usage.remaining

            recognized_meal = await recognize_meal(image_bytes, description, meal_type, on_retry=report_retry)

            logger.info("Meal stage=recognition items=%s", len(recognized_meal.get("items", [])))

            if recognized_meal["status"] == "not_food":
                await status_message.edit_text(
                    _with_usage_notice(language, analyze_not_food, usage_remaining),
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
                context.user_data.pop("meal_type", None)
        
                return ConversationHandler.END

            elif recognized_meal["status"] == "too_complex":
                await status_message.edit_text(
                    _with_usage_notice(language, analyze_too_complex, usage_remaining),
                    reply_markup=keyboard
                )

                context.user_data.pop("meal_photo_bytes", None)
                context.user_data.pop("meal_photo_file_id", None)
                context.user_data.pop("meal_description", None)
                context.user_data.pop("meal_type", None)
        
                return ConversationHandler.END

            elif recognized_meal["status"] == "uncertain":
                await status_message.edit_text(
                    _with_usage_notice(language, analyze_uncertain, usage_remaining),
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

            logger.info("Meal stage=selection items=%s", len(fatsecret_meal["foods"]))

            if meal_draft_expired(context.user_data):
                await status_message.edit_text(_with_usage_notice(
                    language, text(language, "meal_expired"), usage_remaining),
                    reply_markup=keyboard)
                return ConversationHandler.END

            if usage_remaining is not None:
                context.user_data["_meal_usage_remaining"] = usage_remaining

            operation_id = uuid4().hex
            remaining = context.user_data["_meal_draft_expires_at"] - monotonic()
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(0, remaining))
            await asyncio.to_thread(create_write_operation, operation_id, telegram_id, expires_at)
            context.user_data["_meal_write_operation_id"] = operation_id
            context.user_data["_meal_pending_write"] = fatsecret_meal["foods"]
            context.user_data["_meal_action_state"] = "awaiting_write_confirmation"
            # Gemini and matching no longer need the user's original content.
            context.user_data.pop("meal_photo_bytes", None)
            context.user_data.pop("meal_photo_file_id", None)
            context.user_data.pop("meal_description", None)
            review_text, review_markup = build_final_review_screen(
                language, fatsecret_meal["foods"], meal_type, operation_id)
            await status_message.edit_text(
                _with_usage_notice(language, review_text, context.user_data),
                reply_markup=review_markup,
                parse_mode="HTML",
            )
            logger.info("Meal stage=review items=%s elapsed=%.2fs",
                        len(fatsecret_meal["foods"]), monotonic() - started)
            return WAITING_FINAL_REVIEW

        except UnverifiedFoodSelection:
            message = _with_usage_notice(
                language, text(language, "matching_uncertain"), usage_remaining)
            clear_meal_data(context.user_data)
            await status_message.edit_text(message, reply_markup=keyboard)
            return ConversationHandler.END
        except GeminiTemporarilyUnavailable:
            # Both Gemini stages precede diary writes; retrying here cannot duplicate entries.
            if meal_draft_expired(context.user_data):
                await status_message.edit_text(_with_usage_notice(
                                                   language, text(language, "meal_expired"),
                                                   usage_remaining),
                                               reply_markup=keyboard)
                return ConversationHandler.END
            context.user_data["_meal_action_state"] = "awaiting_analysis"
            await status_message.edit_text(_with_usage_notice(
                                               language, text(language, "service_busy"),
                                               usage_remaining),
                                           reply_markup=build_confirm_keyboard(language))
            return WAITING_CONFIRM
        except Exception as error:
            logger.warning("Meal stage=processing failed type=%s elapsed=%.2fs",
                           type(error).__name__, monotonic() - started)
            message = _with_usage_notice(language, error_text, usage_remaining)
            clear_meal_data(context.user_data)
            await status_message.edit_text(message, reply_markup=keyboard)
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
            parse_mode="HTML",
        )

        return WAITING_PHOTO
    elif query.data == "confirm_btn_cancel":
        await query.delete_message()

        context.user_data.pop("meal_photo_bytes", None)
        context.user_data.pop("meal_photo_file_id", None)
        context.user_data.pop("meal_description", None)
        context.user_data.pop("meal_type", None)

        menu_text, markup = build_main_menu(language)
        cancelled = _with_usage_notice(
            language, text(language, "meal_cancelled"), context.user_data)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=cancelled + "\n\n" + menu_text,
            reply_markup=markup,
            parse_mode="HTML",
        )

        return ConversationHandler.END


def _result_lines(language: str, key: str, foods: list[str]) -> str:
    return text(language, key, foods="\n".join(f"• {escape(name)}" for name in foods))


@meal_state_handler
async def final_review_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_meal_callback(query)
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    language = user.language if user and user.language in ("ru", "en") else "ru"
    operation_id = context.user_data.get("_meal_write_operation_id")
    callback_operation_id = query.data.split(":", 1)[1] if ":" in query.data else ""
    pending = context.user_data.get("_meal_pending_write")

    if not operation_id:
        return ConversationHandler.END
    if callback_operation_id != operation_id:
        await query.edit_message_text(text(language, "review_unavailable"),
                                      reply_markup=_menu_keyboard(language))
        return WAITING_FINAL_REVIEW
    if (context.user_data.get("_meal_action_state") != "awaiting_write_confirmation"
            or not pending):
        await query.edit_message_text(text(language, "review_unavailable"),
                                      reply_markup=_menu_keyboard(language))
        return ConversationHandler.END

    if meal_draft_expired(context.user_data):
        try:
            await asyncio.to_thread(close_pending_write_operation,
                                    operation_id, telegram_id, "expired")
        except Exception as error:
            logger.warning("Meal stage=expiry marker failed type=%s", type(error).__name__)
        await query.edit_message_text(_with_usage_notice(
                                          language, text(language, "meal_expired"),
                                          context.user_data),
                                      reply_markup=_menu_keyboard(language))
        return ConversationHandler.END

    if query.data.startswith("meal_write_cancel:"):
        try:
            await asyncio.to_thread(close_pending_write_operation,
                                    operation_id, telegram_id, "cancelled")
        except Exception as error:
            logger.warning("Meal stage=cancel marker failed type=%s", type(error).__name__)
        menu_text, markup = build_main_menu(language)
        cancelled = _with_usage_notice(
            language, text(language, "meal_cancelled"), context.user_data)
        await query.edit_message_text(cancelled + "\n\n" + menu_text,
                                      reply_markup=markup, parse_mode="HTML")
        return ConversationHandler.END

    if user is None or not user.fatsecret_token or not user.fatsecret_token_secret:
        try:
            await asyncio.to_thread(close_pending_write_operation,
                                    operation_id, telegram_id, "cancelled")
        except Exception as error:
            logger.warning("Meal stage=credential marker failed type=%s", type(error).__name__)
        await query.edit_message_text(_with_usage_notice(
                                          language, text(language, "setup_again"),
                                          context.user_data),
                                      reply_markup=_menu_keyboard(language))
        return ConversationHandler.END

    # Update the Telegram screen first. If this fails, no durable claim and no
    # FatSecret POST have happened, so the user may safely press the button again.
    await query.edit_message_text(text(language, "saving"))
    try:
        claim = await asyncio.to_thread(claim_write_operation, operation_id, telegram_id)
    except Exception as error:
        logger.warning("Meal stage=write claim failed type=%s", type(error).__name__)
        await query.edit_message_text(_with_usage_notice(
                                          language, text(language, "write_start_failed"),
                                          context.user_data),
                                      reply_markup=_menu_keyboard(language))
        return ConversationHandler.END
    if claim != "claimed":
        logger.info("Meal stage=write duplicate state=%s", claim)
        await query.edit_message_text(_with_usage_notice(
                                          language, text(language, "write_already_processed"),
                                          context.user_data),
                                      reply_markup=_menu_keyboard(language))
        return ConversationHandler.END

    context.user_data["_meal_action_state"] = "writing"
    meal_type = context.user_data["meal_type"]
    started = monotonic()
    results = {"success": [], "error": [], "uncertain": []}
    for food in pending:
        try:
            response = await asyncio.to_thread(
                fatsecret_create_entry,
                user_token=user.fatsecret_token,
                user_token_secret=user.fatsecret_token_secret,
                food_id=food["food_id"],
                food_entry_name=food["food_name"],
                serving_id=food["serving_id"],
                number_of_units=food["number_of_units"],
                meal=meal_type,
            )
            status = response.get("status") if isinstance(response, dict) else "uncertain"
        except Exception as error:
            logger.warning("Meal stage=entry outcome uncertain type=%s", type(error).__name__)
            status = "uncertain"
        if status not in results:
            status = "uncertain"
        results[status].append(food["review"]["food_name"])

    if results["success"] and not results["error"] and not results["uncertain"]:
        outcome = "completed"
        message = text(language, "success", meal=text(language, meal_type))
    elif results["success"]:
        outcome = "partial" if not results["uncertain"] else "uncertain"
        sections = [text(language, "write_partial_header")]
        sections.append(_result_lines(language, "write_succeeded", results["success"]))
        if results["error"]:
            sections.append(_result_lines(language, "write_failed", results["error"]))
        if results["uncertain"]:
            sections.append(_result_lines(language, "write_uncertain", results["uncertain"]))
        message = "\n\n".join(sections)
    elif results["uncertain"]:
        outcome = "uncertain"
        sections = [_result_lines(language, "write_uncertain", results["uncertain"])]
        if results["error"]:
            sections.append(_result_lines(language, "write_failed", results["error"]))
        message = "\n\n".join(sections)
    else:
        outcome = "failed"
        message = _result_lines(language, "write_all_failed", results["error"])

    try:
        await asyncio.to_thread(finish_write_operation, operation_id, telegram_id, outcome)
    except Exception as error:
        # Entries may already exist. Keep the durable state at "writing" so no
        # callback can replay the POST after an uncertain local bookkeeping error.
        logger.warning("Meal stage=write marker failed type=%s", type(error).__name__)
    logger.info("Meal stage=entry completed items=%s successes=%s failures=%s uncertain=%s elapsed=%.2fs",
                len(pending), len(results["success"]), len(results["error"]),
                len(results["uncertain"]), monotonic() - started)
    message = _with_usage_notice(language, message, context.user_data)
    await query.edit_message_text(message + "\n\n" + text(language, "fatsecret_attribution"),
                                  reply_markup=_menu_keyboard(language), parse_mode="HTML")
    return ConversationHandler.END


@meal_state_handler
async def final_review_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if meal_draft_expired(context.user_data):
        return await expired_meal(update, context)
    user = get_user(update.effective_user.id)
    language = user.language if user else "ru"
    await update.message.reply_text(text(language, "review_reminder"))
    return WAITING_FINAL_REVIEW


async def stale_final_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catch callbacks left in Telegram after restart or conversation cleanup."""
    query = update.callback_query
    await answer_meal_callback(query)
    user = get_user(update.effective_user.id)
    language = user.language if user and user.language in ("ru", "en") else "ru"
    await query.edit_message_text(text(language, "review_unavailable"),
                                  reply_markup=_menu_keyboard(language))
    
@meal_state_handler
async def photo_exception(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    await update.message.reply_text(text(language, "input_error"))
    return WAITING_PHOTO

@meal_state_handler
async def cancel_photo_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    language = get_user(telegram_id).language
    query = update.callback_query
    if query:
        await query.answer()

    await close_pending_meal_write(context.user_data, telegram_id)

    context.user_data.pop("meal_photo_bytes", None)
    context.user_data.pop("meal_photo_file_id", None)
    context.user_data.pop("meal_description", None)
    context.user_data.pop("meal_type", None)

    menu_text, markup = build_main_menu(language)
    if query:
        await query.edit_message_text(text(language, "meal_cancelled") + "\n\n" + menu_text,
                                      reply_markup=markup, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(text(language, "meal_cancelled") + "\n\n" + menu_text,
                                                  reply_markup=markup, parse_mode="HTML")
    
    return ConversationHandler.END


async def expired_meal(update, context):
    clear_meal_data(context.user_data)
    user = get_user(update.effective_user.id)
    language = user.language if user else "ru"
    if update.callback_query:
        await answer_meal_callback(update.callback_query)
    await update.effective_message.reply_text(text(language, "meal_expired"))
    return ConversationHandler.END
