"""Offline regressions for final review, idempotency and write outcomes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import requests
from telegram.ext import ConversationHandler

import test_meal_input as support
from repositories import write_operation_repository
from database import init_db as init_db_module


class FinalReviewFlowTests(support.MealTestSupport, unittest.IsolatedAsyncioTestCase):
    async def prepare_review(self, *, foods=None, meal=None):
        if foods is not None:
            self.api.models.generate_content.return_value.text = support.json.dumps(foods)
        if meal is not None:
            self.api.interactions.create.return_value.output_text = support.json.dumps(meal)
        await self.accept('text')
        result = await self.analyze()
        self.assertEqual(result, support.photo.WAITING_FINAL_REVIEW)
        return self.context.user_data['_meal_write_operation_id']

    def review_text(self):
        call = self.status.edit_text.await_args
        return call.args[0] if call.args else call.kwargs['text']

    async def test_review_contains_verified_values_and_no_private_ids(self):
        operation_id = await self.prepare_review()
        rendered = self.review_text()
        for expected in ('Rice', '100 g', '150 g', '195', '4.5', '1.5', '42'):
            self.assertIn(expected, rendered)
        for forbidden in ('123', '456', 'oauth', 'test-token'):
            self.assertNotIn(forbidden, rendered)
        markup = self.status.edit_text.await_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].callback_data,
                         f'meal_write:{operation_id}')
        self.oauth.post.assert_not_called()
        self.assertNotIn('meal_photo_bytes', self.context.user_data)
        self.assertNotIn('meal_description', self.context.user_data)

        gemini_calls = (self.api.interactions.create.call_count,
                        self.api.models.generate_content.call_count)
        self.assertEqual(await self.final_confirm(), ConversationHandler.END)
        self.oauth.post.assert_called_once()
        self.assertEqual(gemini_calls, (self.api.interactions.create.call_count,
                                        self.api.models.generate_content.call_count))

    async def test_cancel_from_review_never_writes(self):
        await self.prepare_review()
        self.assertEqual(await self.final_confirm('cancel'), ConversationHandler.END)
        self.oauth.post.assert_not_called()
        self.close_write.assert_called_once()
        self.assert_clean()

    async def test_old_initial_confirmation_does_not_repeat_matching(self):
        await self.prepare_review()
        calls = (self.api.interactions.create.call_count,
                 self.api.models.generate_content.call_count,
                 self.tool_search.call_count, self.tool_get.call_count)
        self.assertEqual(await self.analyze(), support.photo.WAITING_FINAL_REVIEW)
        self.assertEqual(calls, (self.api.interactions.create.call_count,
                                 self.api.models.generate_content.call_count,
                                 self.tool_search.call_count, self.tool_get.call_count))
        self.oauth.post.assert_not_called()

    async def test_wrong_and_replayed_callbacks_cannot_write(self):
        operation_id = await self.prepare_review()
        handler = next(h for h in support.app.photo_process_conv.states[support.photo.WAITING_FINAL_REVIEW]
                       if h.callback is support.photo.final_review_screen)
        wrong = self.update(callback=f'meal_write:{"0" * 32}')
        self.assertEqual(await handler.callback(wrong, self.context),
                         support.photo.WAITING_FINAL_REVIEW)
        self.assertEqual(self.context.user_data['_meal_write_operation_id'], operation_id)
        self.oauth.post.assert_not_called()

        self.assertEqual(await self.final_confirm(), ConversationHandler.END)
        replay = self.update(callback=f'meal_write:{operation_id}')
        self.assertEqual(await handler.callback(replay, self.context), ConversationHandler.END)
        self.oauth.post.assert_called_once()
        self.claim_write.assert_called_once()

    async def test_concurrent_double_click_claims_and_writes_once(self):
        operation_id = await self.prepare_review()
        handler = next(h for h in support.app.photo_process_conv.states[support.photo.WAITING_FINAL_REVIEW]
                       if h.callback is support.photo.final_review_screen)
        first = self.update(callback=f'meal_write:{operation_id}')
        second = self.update(callback=f'meal_write:{operation_id}')
        await asyncio.gather(handler.callback(first, self.context),
                             handler.callback(second, self.context))
        self.claim_write.assert_called_once()
        self.oauth.post.assert_called_once()
        self.assert_clean()

    async def test_ambiguous_network_result_is_not_retried(self):
        await self.prepare_review()
        secret = 'https://provider.invalid/?oauth_token=FAKE_TOKEN'
        self.oauth.post.side_effect = requests.ConnectionError(secret)
        with self.assertLogs(level=logging.WARNING) as logs:
            await self.final_confirm()
        self.oauth.post.assert_called_once()
        output = self.status.edit_text.await_args.kwargs['text'] + str(logs.output)
        self.assertIn(support.ui_text('ru', 'write_uncertain', foods='').split('\n')[0], output)
        self.assertNotIn('FAKE_TOKEN', output)
        self.assertNotIn('provider.invalid', output)

    async def test_idempotency_store_failure_stops_before_post(self):
        await self.prepare_review()
        self.claim_write.side_effect = OSError('offline database failure')
        self.assertEqual(await self.final_confirm(), ConversationHandler.END)
        self.oauth.post.assert_not_called()
        self.assertIn(support.ui_text('ru', 'write_start_failed'),
                      self.status.edit_text.await_args.kwargs['text'])

    async def test_partial_result_lists_exact_success_and_failure(self):
        foods = support.copy.deepcopy(support.FOODS)
        foods['resolution'] = 'components'
        foods['foods'][0]['food_name'] = 'Rice'
        foods['foods'].append(dict(foods['foods'][0], food_name='Beans', food_id=789,
                                   serving_id=987))
        meal = support.copy.deepcopy(support.MEAL)
        meal['items'].append({'name': 'beans', 'brand': None, 'amount_g': 150})
        self.set_entry_results(['success', 'error'])
        await self.prepare_review(foods=foods, meal=meal)
        await self.final_confirm()
        result = self.status.edit_text.await_args.kwargs['text']
        success_section, failed_section = result.split(support.ui_text(
            'ru', 'write_failed', foods='').split('\n')[0], 1)
        self.assertIn('Rice', success_section)
        self.assertNotIn('Beans', success_section)
        self.assertIn('Beans', failed_section)
        self.assertEqual(self.oauth.post.call_count, 2)

    async def test_review_reminder_keeps_original_deadline(self):
        await self.prepare_review()
        deadline = self.context.user_data['_meal_draft_expires_at']
        update = self.update('text', 'reminder')
        handler = next(h for h in support.app.photo_process_conv.states[support.photo.WAITING_FINAL_REVIEW]
                       if h.callback is support.photo.final_review_reminder)
        self.assertEqual(await handler.callback(update, self.context),
                         support.photo.WAITING_FINAL_REVIEW)
        self.assertEqual(self.context.user_data['_meal_draft_expires_at'], deadline)
        self.oauth.post.assert_not_called()

    async def test_write_started_before_expiry_completes_and_cleans(self):
        await self.prepare_review()

        def expire_during_write(**kwargs):
            self.context.user_data['_meal_draft_expires_at'] = 0
            return {'status': 'success', 'response': {}}

        with patch.object(support.photo, 'fatsecret_create_entry', side_effect=expire_during_write):
            self.assertEqual(await self.final_confirm(), ConversationHandler.END)
        self.finish_write.assert_called_once()
        self.assert_clean()

    async def test_expired_review_cannot_be_written(self):
        operation_id = await self.prepare_review()
        self.context.user_data['_meal_draft_expires_at'] = 0
        self.assertEqual(await self.final_confirm(), ConversationHandler.END)
        self.oauth.post.assert_not_called()
        self.close_write.assert_called_with(operation_id, 1, 'expired')
        self.assert_clean()

    async def test_final_cleanup_does_not_change_tokens_or_preferences(self):
        original = (self.user.language, self.user.fatsecret_token,
                    self.user.fatsecret_token_secret)
        await self.prepare_review()
        await self.final_confirm()
        self.assertEqual((self.user.language, self.user.fatsecret_token,
                          self.user.fatsecret_token_secret), original)
        self.assert_clean()

    async def test_stale_callback_after_restart_never_writes(self):
        operation_id = await self.prepare_review()
        support.photo.clear_meal_data(self.context.user_data)
        update = self.update(callback=f'meal_write:{operation_id}')
        await support.photo.stale_final_review(update, self.context)
        self.oauth.post.assert_not_called()
        rendered = self.status.edit_text.await_args.kwargs['text']
        self.assertEqual(rendered, support.ui_text('ru', 'review_unavailable'))


class WriteOperationRepositoryTests(unittest.TestCase):
    def database(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'app.db'
        patchers = (patch.object(write_operation_repository, 'DB_PATH', path),
                    patch.object(init_db_module, 'DB_PATH', path))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        return path

    def test_atomic_claim_survives_concurrent_callbacks_and_restart(self):
        self.database()
        init_db_module.init_db()
        expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        write_operation_repository.create_write_operation('a' * 32, 7, expires)
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(
                lambda _: write_operation_repository.claim_write_operation('a' * 32, 7),
                range(2),
            ))
        self.assertEqual(outcomes.count('claimed'), 1)
        self.assertEqual(outcomes.count('writing'), 1)
        # A process restart sees "writing" and cannot claim/replay the POST.
        self.assertEqual(
            write_operation_repository.claim_write_operation('a' * 32, 7), 'writing')

    def test_operation_cannot_be_claimed_by_another_user(self):
        self.database()
        init_db_module.init_db()
        expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        write_operation_repository.create_write_operation('b' * 32, 7, expires)
        self.assertEqual(write_operation_repository.claim_write_operation('b' * 32, 8),
                         'missing')
        self.assertEqual(write_operation_repository.claim_write_operation('b' * 32, 7),
                         'claimed')

    def test_cleanup_retains_ambiguous_operations_and_old_ids_remain_unclaimable(self):
        path = self.database()
        init_db_module.init_db()
        old = datetime.now(timezone.utc) - timedelta(
            days=write_operation_repository.KNOWN_OUTCOME_RETENTION_DAYS + 1)
        future = datetime.now(timezone.utc) + timedelta(minutes=30)
        for operation_id, state in (('u' * 32, 'uncertain'), ('w' * 32, 'writing'),
                                    ('c' * 32, 'completed')):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    """INSERT INTO meal_write_operations
                       (operation_id, telegram_id, state, outcome, created_at, expires_at, updated_at)
                       VALUES (?, 7, ?, ?, ?, ?, ?)""",
                    (operation_id, state, state if state != 'writing' else None,
                     old.isoformat(), future.isoformat(), old.isoformat()),
                )
        write_operation_repository.create_write_operation('n' * 32, 7, future)
        self.assertEqual(write_operation_repository.get_write_operation_state('u' * 32, 7),
                         'uncertain')
        self.assertEqual(write_operation_repository.get_write_operation_state('w' * 32, 7),
                         'writing')
        self.assertEqual(write_operation_repository.get_write_operation_state('c' * 32, 7),
                         'missing')
        self.assertEqual(write_operation_repository.claim_write_operation('c' * 32, 7),
                         'missing')

    def test_cleanup_closes_expired_pending_without_deleting_ambiguous_rows(self):
        path = self.database()
        init_db_module.init_db()
        now = datetime.now(timezone.utc)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                """INSERT INTO meal_write_operations
                   (operation_id, telegram_id, state, outcome, created_at, expires_at, updated_at)
                   VALUES (?, 8, 'pending', NULL, ?, ?, ?)""",
                ('p' * 32, (now - timedelta(hours=1)).isoformat(),
                 (now - timedelta(minutes=30)).isoformat(),
                 (now - timedelta(hours=1)).isoformat()),
            )
        write_operation_repository.cleanup_write_operations(now=now)
        self.assertEqual(write_operation_repository.get_write_operation_state('p' * 32, 8),
                         'expired')

    def test_schema_migration_preserves_existing_user_and_oauth_tokens(self):
        path = self.database()
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                """CREATE TABLE users (
                    telegram_id INTEGER PRIMARY KEY,
                    language TEXT,
                    fatsecret_token TEXT,
                    fatsecret_token_secret TEXT,
                    fatsecret_connected_at TEXT
                )""")
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                (7, 'ru', 'synthetic-token', 'synthetic-secret', '2026-01-01T00:00:00+00:00'),
            )
        init_db_module.init_db()
        with closing(sqlite3.connect(path)) as connection, connection:
            user = connection.execute(
                """SELECT telegram_id, language, fatsecret_token, fatsecret_token_secret,
                          fatsecret_connected_at, is_premium, daily_usage_count, daily_usage_date
                   FROM users WHERE telegram_id = 7""").fetchone()
            operation_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='meal_write_operations'"
            ).fetchone()
        self.assertEqual(user, (7, 'ru', 'synthetic-token', 'synthetic-secret',
                                '2026-01-01T00:00:00+00:00', 0, 0, None))
        self.assertEqual(operation_table, ('meal_write_operations',))

    def test_cancel_and_expiry_are_durable_and_not_claimable(self):
        self.database()
        init_db_module.init_db()
        now = datetime.now(timezone.utc)
        write_operation_repository.create_write_operation(
            'd' * 32, 7, now + timedelta(minutes=30), now=now)
        self.assertTrue(write_operation_repository.close_pending_write_operation(
            'd' * 32, 7, 'cancelled', now=now))
        self.assertEqual(write_operation_repository.claim_write_operation('d' * 32, 7),
                         'cancelled')

        write_operation_repository.create_write_operation(
            'e' * 32, 7, now + timedelta(seconds=1), now=now)
        self.assertEqual(write_operation_repository.claim_write_operation(
            'e' * 32, 7, now=now + timedelta(seconds=2)), 'expired')
        self.assertEqual(write_operation_repository.claim_write_operation('e' * 32, 7),
                         'expired')


if __name__ == '__main__':
    unittest.main()
