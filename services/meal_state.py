"""Bounded, in-memory meal drafts; no persistent user settings are touched.

Expiry removes data, not ConversationHandler's routing state. The next meal
callback detects the missing draft and ends that state without provider calls.
This avoids a JobQueue dependency and never expires an in-flight handler.
"""
import asyncio
from contextvars import ContextVar
from functools import wraps
import logging
from time import monotonic
from weakref import WeakValueDictionary

from telegram.ext import ConversationHandler

MEAL_DRAFT_TTL_SECONDS = 30 * 60
MEAL_KEYS = ("meal_photo_bytes", "meal_photo_file_id", "meal_description", "meal_type",
             "_meal_draft_token", "_meal_draft_expires_at", "_meal_action_state",
             "_meal_pending_write", "_meal_write_operation_id", "_meal_telegram_id",
             "_meal_usage_remaining")
_expiry_handles = {}
_handler_locks = WeakValueDictionary()
_active_data_ids = ContextVar('active_meal_data_ids', default=frozenset())
logger = logging.getLogger(__name__)


def _cancel_expiry(data):
    handle = _expiry_handles.pop(id(data), None)
    if handle is not None:
        handle.cancel()


def clear_meal_data(data):
    _cancel_expiry(data)
    for key in MEAL_KEYS:
        data.pop(key, None)


async def close_pending_meal_write(data, telegram_id, state='cancelled'):
    """Close only a pending durable marker; an in-flight write is never cancelled."""
    operation_id = data.get("_meal_write_operation_id")
    if not operation_id:
        return
    try:
        from repositories.write_operation_repository import close_pending_write_operation
        await asyncio.to_thread(close_pending_write_operation, operation_id, telegram_id, state)
    except Exception as error:
        logger.warning("Meal close marker failed type=%s", type(error).__name__)


def create_meal_draft(data):
    clear_meal_data(data)
    data["_meal_draft_token"] = object()
    data["_meal_draft_expires_at"] = monotonic() + MEAL_DRAFT_TTL_SECONDS


def meal_draft_expired(data):
    expires_at = data.get("_meal_draft_expires_at")
    return expires_at is None or monotonic() >= expires_at


def _expire_if_current(data, token):
    if data.get("_meal_draft_token") is token:
        operation_id = data.get("_meal_write_operation_id")
        if operation_id:
            try:
                from repositories.write_operation_repository import close_pending_write_operation
                # The Telegram id is stored beside the pending in-memory payload.
                close_pending_write_operation(operation_id, data.get("_meal_telegram_id"), 'expired')
            except Exception as error:
                logger.warning("Meal expiry marker failed type=%s", type(error).__name__)
        clear_meal_data(data)


def _schedule_expiry(data):
    token = data.get("_meal_draft_token")
    expires_at = data.get("_meal_draft_expires_at")
    if token is None or expires_at is None:
        return
    remaining = expires_at - monotonic()
    if remaining <= 0:
        _expire_if_current(data, token)
        return
    _expiry_handles[id(data)] = asyncio.get_running_loop().call_later(
        remaining, _expire_if_current, data, token)


def meal_state_handler(callback):
    """Pause draft expiry during handling, clear on exit, bound retry waits."""
    async def run(update, context):
        data = context.user_data
        _cancel_expiry(data)
        try:
            result = await callback(update, context)
        except BaseException:
            clear_meal_data(data)
            raise
        if result == ConversationHandler.END:
            clear_meal_data(data)
        elif "meal_description" in data or "_meal_pending_write" in data:
            _schedule_expiry(data)
        elif "_meal_draft_token" in data:
            clear_meal_data(data)
        return result

    @wraps(callback)
    async def wrapped(update, context):
        data = context.user_data
        data_id = id(data)
        active = _active_data_ids.get()
        if data_id in active:
            return await run(update, context)
        lock = _handler_locks.setdefault(data_id, asyncio.Lock())
        async with lock:
            marker = _active_data_ids.set(active | {data_id})
            try:
                return await run(update, context)
            finally:
                _active_data_ids.reset(marker)
    return wrapped
