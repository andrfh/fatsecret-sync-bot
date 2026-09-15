"""Offline regressions for Gemini overload and Telegram callback failures."""
import json
import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from google.genai.errors import ClientError, ServerError
from telegram.error import NetworkError, BadRequest
from telegram.ext import ConversationHandler

import test_meal_input as meal_tests


def api_error(code=503, retry_after=None):
    cls = ClientError if code < 500 else ServerError
    return cls(code, {'error': {'code': code, 'status': 'UNAVAILABLE',
                              'message': 'This model is currently experiencing high demand.'}},
               response=SimpleNamespace(headers={} if retry_after is None else {'Retry-After': retry_after}))


class TransientErrorTests(meal_tests.MealTestSupport, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.sleep = self.enterContext(patch.object(meal_tests.gemini_service.asyncio, 'sleep', new_callable=AsyncMock))
        self.enterContext(patch.object(meal_tests.gemini_service.random, 'uniform', return_value=0))

    async def test_recover_on_each_gemini_stage_without_restarting_other_stage(self):
        for stage in ('recognition', 'search'):
            for code in (429, 503):
                with self.subTest(stage=stage, code=code):
                    self.consume_attempt.reset_mock()
                    self.api.reset_mock(side_effect=True)
                    self.api.interactions.create.return_value = SimpleNamespace(output_text=json.dumps(meal_tests.MEAL))
                    self.api.models.generate_content.return_value = SimpleNamespace(text=json.dumps(meal_tests.FOODS))
                    self.set_entry_results(['success'])
                    self.oauth.post.reset_mock()
                    self.sleep.reset_mock()
                    operation = self.api.interactions.create if stage == 'recognition' else self.api.models.generate_content
                    operation.side_effect = [api_error(code), api_error(code), operation.return_value]
                    await self.accept('text')
                    self.assertEqual(await self.confirm(), ConversationHandler.END)
                    self.assertEqual(operation.call_count, 3)
                    other = self.api.models.generate_content if stage == 'recognition' else self.api.interactions.create
                    self.assertEqual(other.call_count, 1)
                    self.assertEqual([c.args[0] for c in self.sleep.await_args_list], [2, 4])
                    self.oauth.post.assert_called_once()
                    self.consume_attempt.assert_called_once_with(1)
                    self.assert_clean()

    async def test_ssl_eof_retries_each_gemini_stage(self):
        for stage in ('recognition', 'search'):
            with self.subTest(stage=stage):
                self.api.reset_mock(side_effect=True)
                recognition = SimpleNamespace(output_text=json.dumps(meal_tests.MEAL))
                search = SimpleNamespace(text=json.dumps(meal_tests.FOODS))
                self.api.interactions.create.return_value = recognition
                self.api.models.generate_content.return_value = search
                self.set_entry_results(['success'])
                self.oauth.post.reset_mock()
                self.sleep.reset_mock()
                operation = self.api.interactions.create if stage == 'recognition' else self.api.models.generate_content
                operation.side_effect = [
                    ssl.SSLEOFError(8, 'EOF occurred in violation of protocol'),
                    recognition if stage == 'recognition' else search,
                ]
                await self.accept('text')
                self.assertEqual(await self.confirm(), ConversationHandler.END)
                self.assertEqual(operation.call_count, 2)
                self.sleep.assert_awaited_once_with(2)
                self.oauth.post.assert_called_once()

    async def test_wrapped_ssl_error_is_detected_and_exhaustion_preserves_draft(self):
        wrapped = RuntimeError('request failed')
        wrapped.__cause__ = ssl.SSLEOFError(8, 'EOF occurred in violation of protocol')
        self.api.interactions.create.side_effect = wrapped
        await self.accept('photo')
        saved = self.context.user_data.copy()
        self.status.edit_text.reset_mock()
        self.assertEqual(await self.confirm(), meal_tests.photo.WAITING_CONFIRM)
        self.assertEqual(self.api.interactions.create.call_count, 3)
        self.assertEqual(self.context.user_data, saved)
        self.oauth.post.assert_not_called()
        self.assertEqual(self.status.edit_text.await_args.args[0],
                         meal_tests.ui_text('ru', 'service_busy'))

    async def test_exhaustion_preserves_draft_and_manual_retry_works(self):
        for language in ('ru', 'en'):
            self.user.language = language
            for stage in ('recognition', 'search'):
                for kind in ('photo', 'text', 'caption'):
                    with self.subTest(language=language, stage=stage, kind=kind):
                        self.api.reset_mock(side_effect=True)
                        self.api.interactions.create.return_value = SimpleNamespace(output_text=json.dumps(meal_tests.MEAL))
                        self.api.models.generate_content.return_value = SimpleNamespace(text=json.dumps(meal_tests.FOODS))
                        self.oauth.post.reset_mock()
                        self.set_entry_results(['success'])
                        operation = self.api.interactions.create if stage == 'recognition' else self.api.models.generate_content
                        operation.side_effect = api_error()
                        await self.accept(kind)
                        saved = self.context.user_data.copy()
                        self.bot.send_message.reset_mock()
                        self.status.edit_text.reset_mock()
                        self.assertEqual(await self.confirm(), meal_tests.photo.WAITING_CONFIRM)
                        self.assertEqual(operation.call_count, 3)
                        self.assertEqual(self.context.user_data, saved)
                        self.oauth.post.assert_not_called()
                        self.assertEqual(self.bot.send_message.await_count, 1)
                        final = self.status.edit_text.await_args
                        self.assertEqual(final.args[0], meal_tests.ui_text(language, 'service_busy'))
                        self.assertEqual(final.kwargs['reply_markup'].inline_keyboard[0][0].callback_data,
                                         'confirm_btn_approve')
                        operation.side_effect = None
                        self.assertEqual(await self.confirm(), ConversationHandler.END)
                        self.oauth.post.assert_called_once()
                        self.assert_clean()

    async def test_permanent_error_and_invalid_json_are_not_retried(self):
        for failure in (api_error(400), api_error(403), RuntimeError('Other failure'),
                        FileNotFoundError('local file missing')):
            self.api.interactions.create.reset_mock()
            self.api.interactions.create.side_effect = failure
            with self.assertRaises(type(failure)):
                await meal_tests.gemini_service.recognize_meal(None, 'rice', 'dinner')
            self.api.interactions.create.assert_called_once()
        self.api.interactions.create.side_effect = None
        self.api.interactions.create.reset_mock()
        self.api.interactions.create.return_value.output_text = 'invalid JSON'
        with self.assertRaises(ValueError):
            await meal_tests.gemini_service.recognize_meal(None, 'rice', 'dinner')
        self.api.interactions.create.assert_called_once()
        self.sleep.assert_not_awaited()

    async def test_retry_after_and_excessive_delay(self):
        self.api.interactions.create.side_effect = [api_error(429, '10'),
                                                   SimpleNamespace(output_text=json.dumps(meal_tests.MEAL))]
        await meal_tests.gemini_service.recognize_meal(None, 'rice', 'dinner')
        self.sleep.assert_awaited_once_with(10)
        self.sleep.reset_mock()
        self.api.interactions.create.reset_mock()
        self.api.interactions.create.side_effect = api_error(429, '120')
        with self.assertRaises(meal_tests.gemini_service.GeminiTemporarilyUnavailable):
            await meal_tests.gemini_service.recognize_meal(None, 'rice', 'dinner')
        self.api.interactions.create.assert_called_once()
        self.sleep.assert_not_awaited()

    async def test_telegram_ack_failure_does_not_block_dinner(self):
        await meal_tests.photo.process_photo(self.update('photo'), self.context)
        self.bot.answer_callback_query.side_effect = NetworkError('httpx.ConnectError')
        self.bot.delete_message.side_effect = NetworkError('httpx.ConnectError')
        await self.choose('dinner')
        self.assertEqual(self.context.user_data['meal_type'], 'dinner')
        self.assertIn('Ужин', self.bot.send_photo.await_args.kwargs['caption'])
        self.api.interactions.create.assert_not_called()

    async def test_unrelated_bad_request_is_not_silenced(self):
        self.bot.answer_callback_query.side_effect = BadRequest('Invalid query parameter')
        with self.assertRaises(BadRequest):
            await meal_tests.photo.answer_meal_callback(self.update(callback='meal_type-dinner').callback_query)


class TransientRoutingTests(meal_tests.MealTestSupport, unittest.IsolatedAsyncioTestCase):
    asyncSetUp = meal_tests.MealRoutingTests.asyncSetUp
    asyncTearDown = meal_tests.MealRoutingTests.asyncTearDown
    dispatch = meal_tests.MealRoutingTests.dispatch
    state = meal_tests.MealRoutingTests.state

    async def test_dinner_transition_survives_ack_and_cleanup_errors(self):
        await self.dispatch('photo')
        self.bot.answer_callback_query.side_effect = NetworkError('httpx.ConnectError')
        self.bot.delete_message.side_effect = NetworkError('httpx.ConnectError')
        await self.dispatch(callback='meal_type-dinner')
        self.assertEqual(self.state(), meal_tests.photo.WAITING_CONFIRM)
        self.assertEqual(self.context.user_data['meal_type'], 'dinner')
        self.bot.answer_callback_query.side_effect = None
        self.bot.delete_message.side_effect = None
        await self.dispatch(callback='confirm_btn_approve')
        self.assertIsNone(self.state())
        self.oauth.post.assert_called_once()
        self.assertEqual(self.oauth.post.call_args.kwargs['data']['meal'], 'dinner')

    async def test_overloaded_search_can_be_retried_or_cancelled(self):
        self.enterContext(patch.object(meal_tests.gemini_service.asyncio, 'sleep', new_callable=AsyncMock))
        for action in ('approve', 'cancel'):
            with self.subTest(action=action):
                self.oauth.post.reset_mock()
                self.set_entry_results(['success'])
                await self.dispatch('text')
                await self.dispatch(callback='meal_type-dinner')
                self.api.models.generate_content.side_effect = api_error()
                await self.dispatch(callback='confirm_btn_approve')
                self.assertEqual(self.state(), meal_tests.photo.WAITING_CONFIRM)
                self.oauth.post.assert_not_called()
                self.api.models.generate_content.side_effect = None
                await self.dispatch(callback=f'confirm_btn_{action}')
                self.assertIsNone(self.state())
                self.assert_clean()
                self.assertEqual(self.oauth.post.call_count, 1 if action == 'approve' else 0)


if __name__ == '__main__':
    unittest.main()
