"""Persistent idempotency markers for confirmed FatSecret diary writes.

Only operation metadata is stored. Product data, provider responses, photos and
user-entered meal text remain in the in-memory Telegram conversation draft.
"""
from datetime import datetime, timedelta, timezone
import sqlite3

from config import DB_PATH


# Rows whose outcome is known may be pruned after the replay-protection window.
# ``writing`` and ``uncertain`` are deliberately retained: a POST may already
# have reached FatSecret, so removing their only durable marker would also
# remove the evidence that the operation must never be replayed automatically.
KNOWN_OUTCOME_RETENTION_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError('timezone-aware datetime required')
    return value.astimezone(timezone.utc).isoformat()


def _cleanup(connection, current: datetime) -> None:
    # Expired pending rows are safe to close, but are retained through the
    # same replay-protection window as other known outcomes.
    connection.execute(
        """UPDATE meal_write_operations
           SET state = 'expired', updated_at = ?
           WHERE state = 'pending' AND expires_at <= ?""",
        (_iso(current), _iso(current)),
    )
    # Missing operation ids are never claimable, so pruning a known outcome
    # cannot make an old callback writable. Ambiguous outcomes are retained.
    connection.execute(
        """DELETE FROM meal_write_operations
           WHERE state IN ('completed', 'partial', 'failed', 'cancelled', 'expired')
             AND updated_at < ?""",
        (_iso(current - timedelta(days=KNOWN_OUTCOME_RETENTION_DAYS)),),
    )


def cleanup_write_operations(*, now: datetime | None = None) -> None:
    """Close expired pending rows and prune only old, known outcomes."""
    current = now or _now()
    connection = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        connection.execute('BEGIN IMMEDIATE')
        _cleanup(connection, current)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_write_operation(operation_id: str, telegram_id: int,
                           expires_at: datetime, *, now: datetime | None = None) -> None:
    current = now or _now()
    if expires_at <= current:
        raise ValueError('write operation is already expired')
    connection = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute(
            """UPDATE meal_write_operations
               SET state = 'cancelled', updated_at = ?
               WHERE telegram_id = ? AND state = 'pending'""",
            (_iso(current), telegram_id),
        )
        connection.execute(
            """INSERT INTO meal_write_operations
               (operation_id, telegram_id, state, outcome, created_at, expires_at, updated_at)
               VALUES (?, ?, 'pending', NULL, ?, ?, ?)""",
            (operation_id, telegram_id, _iso(current), _iso(expires_at), _iso(current)),
        )
        _cleanup(connection, current)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def claim_write_operation(operation_id: str, telegram_id: int,
                          *, now: datetime | None = None) -> str:
    """Atomically claim a pending operation and return its resulting state."""
    current = now or _now()
    connection = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute(
            """SELECT state, expires_at FROM meal_write_operations
               WHERE operation_id = ? AND telegram_id = ?""",
            (operation_id, telegram_id),
        ).fetchone()
        if row is None:
            connection.commit()
            return 'missing'
        state, expires_at = row
        if state == 'pending' and datetime.fromisoformat(expires_at) <= current:
            connection.execute(
                """UPDATE meal_write_operations SET state = 'expired', updated_at = ?
                   WHERE operation_id = ? AND telegram_id = ? AND state = 'pending'""",
                (_iso(current), operation_id, telegram_id),
            )
            connection.commit()
            return 'expired'
        if state == 'pending':
            changed = connection.execute(
                """UPDATE meal_write_operations SET state = 'writing', updated_at = ?
                   WHERE operation_id = ? AND telegram_id = ? AND state = 'pending'""",
                (_iso(current), operation_id, telegram_id),
            ).rowcount
            connection.commit()
            return 'claimed' if changed == 1 else 'unavailable'
        connection.commit()
        return state
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def finish_write_operation(operation_id: str, telegram_id: int, outcome: str,
                           *, now: datetime | None = None) -> bool:
    if outcome not in {'completed', 'partial', 'failed', 'uncertain'}:
        raise ValueError('invalid write outcome')
    connection = sqlite3.connect(DB_PATH, timeout=30)
    try:
        changed = connection.execute(
            """UPDATE meal_write_operations
               SET state = ?, outcome = ?, updated_at = ?
               WHERE operation_id = ? AND telegram_id = ? AND state = 'writing'""",
            (outcome, outcome, _iso(now or _now()), operation_id, telegram_id),
        ).rowcount
        connection.commit()
        return changed == 1
    finally:
        connection.close()


def close_pending_write_operation(operation_id: str, telegram_id: int, state: str,
                                  *, now: datetime | None = None) -> bool:
    if state not in {'cancelled', 'expired'}:
        raise ValueError('invalid pending operation state')
    connection = sqlite3.connect(DB_PATH, timeout=30)
    try:
        changed = connection.execute(
            """UPDATE meal_write_operations SET state = ?, updated_at = ?
               WHERE operation_id = ? AND telegram_id = ? AND state = 'pending'""",
            (state, _iso(now or _now()), operation_id, telegram_id),
        ).rowcount
        connection.commit()
        return changed == 1
    finally:
        connection.close()


def get_write_operation_state(operation_id: str, telegram_id: int) -> str:
    connection = sqlite3.connect(DB_PATH)
    try:
        row = connection.execute(
            """SELECT state FROM meal_write_operations
               WHERE operation_id = ? AND telegram_id = ?""",
            (operation_id, telegram_id),
        ).fetchone()
        return row[0] if row else 'missing'
    finally:
        connection.close()
