"""Daily usage quota persistence and meal-flow integration tests."""
import importlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from telegram.ext import ConversationHandler

import test_meal_input as meal_tests

db_init = importlib.import_module("database.init_db")
user_repository = importlib.import_module("repositories.user_repository")
usage_service = importlib.import_module("services.usage_service")


class UsagePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "usage.db"
        self.enterContext(patch.object(db_init, "DB_PATH", self.db_path))
        self.enterContext(patch.object(user_repository, "DB_PATH", self.db_path))
        self.enterContext(patch.object(usage_service, "DAILY_MEAL_ATTEMPT_LIMIT", 4))
        db_init.init_db()
        user_repository.create_user(1)

    def consume(self, day=date(2026, 9, 15)):
        return usage_service.consume_meal_attempt(1, usage_date=day)

    def test_regular_limit_and_rejected_attempt_does_not_increment(self):
        results = [self.consume() for _ in range(5)]
        self.assertEqual([result.allowed for result in results], [True] * 4 + [False])
        self.assertEqual([result.remaining for result in results], [3, 2, 1, 0, 0])
        user = user_repository.get_user(1)
        self.assertEqual(user.daily_usage_count, 4)
        self.assertEqual(user.daily_usage_date, "2026-09-15")

    def test_counter_resets_on_new_calendar_day(self):
        for _ in range(4):
            self.consume(date(2026, 9, 15))
        result = self.consume(date(2026, 9, 16))
        self.assertTrue(result.allowed)
        self.assertEqual(result.remaining, 3)
        user = user_repository.get_user(1)
        self.assertEqual(user.daily_usage_count, 1)
        self.assertEqual(user.daily_usage_date, "2026-09-16")

    def test_premium_bypasses_limit_without_changing_counter(self):
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("UPDATE users SET is_premium = 1 WHERE telegram_id = 1")
        for _ in range(10):
            result = self.consume()
            self.assertTrue(result.allowed)
            self.assertTrue(result.is_premium)
            self.assertIsNone(result.remaining)
        user = user_repository.get_user(1)
        self.assertIs(user.is_premium, True)
        self.assertEqual(user.daily_usage_count, 0)
        self.assertIsNone(user.daily_usage_date)

    def test_concurrent_attempts_cannot_exceed_limit(self):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: self.consume(), range(20)))
        self.assertEqual(sum(result.allowed for result in results), 4)
        self.assertEqual(user_repository.get_user(1).daily_usage_count, 4)

    def test_missing_user_fails_closed(self):
        with self.assertRaises(LookupError):
            usage_service.consume_meal_attempt(999, usage_date=date(2026, 9, 15))

    def test_existing_database_is_migrated_without_data_loss(self):
        self.db_path.unlink()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("""
                CREATE TABLE users (
                    telegram_id INTEGER PRIMARY KEY,
                    language TEXT,
                    fatsecret_token TEXT,
                    fatsecret_token_secret TEXT,
                    fatsecret_connected_at TEXT
                )
            """)
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                (7, "ru", "token", "secret", "2026-09-01"),
            )
        db_init.init_db()
        db_init.init_db()
        user = user_repository.get_user(7)
        self.assertEqual((user.language, user.fatsecret_token, user.fatsecret_token_secret),
                         ("ru", "token", "secret"))
        self.assertIs(user.is_premium, False)
        self.assertEqual(user.daily_usage_count, 0)
        self.assertIsNone(user.daily_usage_date)


class UsageFlowTests(meal_tests.MealTestSupport, unittest.IsolatedAsyncioTestCase):
    async def test_attempt_is_consumed_only_after_confirmation(self):
        await meal_tests.photo.process_photo(self.update("photo"), self.context)
        await self.choose("dinner")
        self.consume_attempt.assert_not_called()
        self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.consume_attempt.assert_called_once_with(1)

    async def test_limit_blocks_both_languages_before_gemini_and_preserves_draft(self):
        for language in ("ru", "en"):
            with self.subTest(language=language):
                self.user.language = language
                await self.accept("text")
                saved = self.context.user_data.copy()
                self.api.reset_mock()
                self.oauth.post.reset_mock()
                self.status.edit_text.reset_mock()
                self.consume_attempt.return_value = usage_service.UsageResult(False, False, 0)
                self.assertEqual(await self.confirm(), meal_tests.photo.WAITING_CONFIRM)
                self.api.interactions.create.assert_not_called()
                self.api.models.generate_content.assert_not_called()
                self.oauth.post.assert_not_called()
                self.assertEqual(self.context.user_data, saved)
                result = self.status.edit_text.await_args
                self.assertEqual(
                    result.args[0],
                    meal_tests.ui_text(language, "daily_limit_reached", limit=4),
                )
                self.assertEqual(result.kwargs["reply_markup"].inline_keyboard[0][0].callback_data,
                                 "confirm_btn_approve")
                await self.confirm("cancel")
                self.consume_attempt.return_value = usage_service.UsageResult(True, False, 3)

    async def test_photo_text_and_caption_share_the_same_quota_check(self):
        for kind in ("photo", "text", "caption"):
            with self.subTest(kind=kind):
                self.consume_attempt.reset_mock()
                self.api.reset_mock(side_effect=True)
                self.restore_generate_content()
                self.api.interactions.create.return_value = SimpleNamespace(
                    output_text=json.dumps(meal_tests.MEAL)
                )
                self.api.models.generate_content.return_value = SimpleNamespace(
                    text=json.dumps(meal_tests.FOODS)
                )
                self.set_entry_results(["success"])
                await self.accept(kind)
                await self.confirm()
                self.consume_attempt.assert_called_once_with(1)

    async def test_recognition_rejection_and_fatsecret_failure_each_consume_one_attempt(self):
        for outcome in ("not_food", "fatsecret_error"):
            with self.subTest(outcome=outcome):
                self.consume_attempt.reset_mock()
                self.api.reset_mock(side_effect=True)
                self.restore_generate_content()
                self.oauth.post.reset_mock()
                await self.accept("text")
                if outcome == "not_food":
                    self.api.interactions.create.return_value = SimpleNamespace(
                        output_text=json.dumps({"status": "not_food"})
                    )
                else:
                    self.api.interactions.create.return_value = SimpleNamespace(
                        output_text=json.dumps(meal_tests.MEAL)
                    )
                    self.api.models.generate_content.return_value = SimpleNamespace(
                        text=json.dumps(meal_tests.FOODS)
                    )
                    self.set_entry_results(["error"])
                self.assertEqual(await self.confirm(), ConversationHandler.END)
                self.consume_attempt.assert_called_once_with(1)

    async def test_failed_processing_consumes_attempt_and_new_operation_consumes_another(self):
        await self.accept("text")
        self.api.interactions.create.side_effect = [
            RuntimeError("AI failure"),
            SimpleNamespace(output_text=json.dumps(meal_tests.MEAL)),
        ]
        self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.assert_clean()
        self.assertEqual(self.consume_attempt.call_count, 1)
        await self.accept("text")
        self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.assertEqual(self.consume_attempt.call_count, 2)
        self.oauth.post.assert_called_once()

    async def test_quota_storage_failure_does_not_call_external_services(self):
        await self.accept("caption")
        self.api.reset_mock()
        self.oauth.post.reset_mock()
        self.consume_attempt.side_effect = sqlite3.OperationalError("database unavailable")
        self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.api.interactions.create.assert_not_called()
        self.api.models.generate_content.assert_not_called()
        self.oauth.post.assert_not_called()
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
