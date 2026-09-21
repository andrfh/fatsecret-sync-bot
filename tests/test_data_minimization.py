"""Offline privacy regressions: no provider calls or production database access."""
import asyncio
import copy
import io
import json
import logging
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests
from google.genai import _extra_utils, interactions, types
from telegram.error import NetworkError
from telegram.ext import ConversationHandler

import test_meal_input as support
from services import fatsecret_food_service as food_service, meal_state
from services.safe_logging import MetadataOnlyFilter
from clients import gemini_client

SENSITIVE = 'https://example.invalid/?oauth_token=FAKE_SECRET&query=PRIVATE_MEAL'


class DataMinimizationTests(support.MealTestSupport, unittest.IsolatedAsyncioTestCase):
    def tool_driven_response(self, calls, response=support.FOODS):
        def run(*args, **kwargs):
            search_tool, get_tool = kwargs['config'].tools
            candidate = None
            detail = None
            for tool, value in calls:
                if tool == 'search':
                    found = search_tool(value).get('candidates', [])
                    if found:
                        candidate = found[0]['candidate_ref']
                else:
                    detail = get_tool(candidate or 'unknown')
            if candidate and detail and detail.get('servings'):
                # Test fixture translates its intended choice to the new public contract.
                # The unconfirmed-serving regression deliberately sends an unknown ref.
                serving_ref = detail['servings'][0]['serving_ref']
                if getattr(self, 'fabricate_serving', False):
                    serving_ref += '-fabricated'
                return type('Response', (), {'text': json.dumps({
                    'status': 'ok', 'resolution': 'whole_meal', 'foods': [{
                        'candidate_ref': candidate, 'serving_ref': serving_ref,
                        'food_name': 'Rice', 'item_indices': [0], 'amount_g': 150}]})})()
            return type('Response', (), {'text': json.dumps(response)})()
        return run

    async def test_sdk_support_and_interactions_store_false(self):
        self.assertIn('store', interactions.CreateModelInteractionParamsNonStreaming.__annotations__)
        self.assertNotIn('store', types.GenerateContentConfig.model_fields)
        await self.accept('caption')
        await self.confirm()
        self.assertIs(self.api.interactions.create.call_args.kwargs['store'], False)
        self.assertNotIn('previous_interaction_id', self.api.interactions.create.call_args.kwargs)

    async def test_two_operations_have_independent_model_inputs(self):
        for index, kind in enumerate(('caption', 'text')):
            marker = f'UniqueMealMarker{index}'
            meal = copy.deepcopy(support.MEAL)
            meal['meal_name'] = marker
            meal['items'][0]['name'] = marker
            self.api.interactions.create.return_value.output_text = json.dumps(meal)
            self.set_entry_results(['success'])
            await self.accept(kind, marker)
            self.assertEqual(await self.confirm(), ConversationHandler.END)
            self.assert_clean()
        recognition = self.api.interactions.create.call_args_list
        selection = self.api.models.generate_content.call_args_list
        self.assertEqual(len(recognition), 2)
        self.assertEqual(len(selection), 2)
        self.assertNotIn('UniqueMealMarker0', str(recognition[1]))
        self.assertNotIn('UniqueMealMarker0', selection[1].kwargs['contents'])
        self.assertEqual([part['type'] for part in recognition[1].kwargs['input']], ['text'])

    async def test_terminal_error_clears_draft_without_logging_content(self):
        await self.accept('caption', 'PRIVATE_MEAL')
        self.api.interactions.create.side_effect = RuntimeError(SENSITIVE)
        with self.assertLogs('handlers.photo', level='WARNING') as captured:
            self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.assert_clean()
        self.assertNotIn('PRIVATE_MEAL', str(captured.output))
        self.assertNotIn('FAKE_SECRET', str(captured.output))
        self.assertIn('RuntimeError', str(captured.output))
        self.oauth.post.assert_not_called()

    async def test_telegram_failure_after_processing_still_clears_draft(self):
        await self.accept('caption')
        self.status.edit_text.side_effect = NetworkError(SENSITIVE)
        with self.assertRaises(NetworkError):
            await self.confirm()
        self.assert_clean()

    async def test_cancel_failure_still_clears_draft(self):
        await self.accept('caption')
        self.bot.delete_message.side_effect = NetworkError(SENSITIVE)
        with self.assertRaises(NetworkError):
            await self.confirm('cancel')
        self.assert_clean()

    async def test_cancel_command_is_registered_and_clears_only_meal_fields(self):
        permanent = {'language': 'ru', 'oauth_token': 'FAKE_PERSISTENT_TOKEN'}
        self.context.user_data.update(permanent)
        await self.accept('caption')
        self.assertTrue(any('cancel' in getattr(handler, 'commands', ())
                            for handler in support.app.photo_process_conv.fallbacks))
        self.assertEqual(await support.photo.cancel_photo_flow(
            self.update(), self.context), ConversationHandler.END)
        self.assertEqual(self.context.user_data, dict(unrelated='keep', **permanent))

    async def test_navigation_clears_draft(self):
        from handlers.start import start
        from handlers.menu import back_to_main_menu
        for callback, update in ((start, self.update()),
                                 (back_to_main_menu, self.update(callback='menu_back'))):
            await self.accept('caption')
            await callback(update, self.context)
            self.assert_clean()

    async def test_timeout_erases_draft_and_stale_confirmation_does_not_call_apis(self):
        with patch.object(meal_state, 'MEAL_DRAFT_TTL_SECONDS', 0):
            await support.photo.process_photo(self.update('caption'), self.context)
            await asyncio.sleep(0.01)
        self.assert_clean()
        self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.api.interactions.create.assert_not_called()
        self.api.models.generate_content.assert_not_called()
        self.oauth.post.assert_not_called()

    async def test_expired_meal_selection_is_safe(self):
        self.assertEqual(await support.photo.select_meal_type(
            self.update(callback='meal_type-dinner'), self.context), ConversationHandler.END)
        self.assert_clean()
        self.api.interactions.create.assert_not_called()

    async def test_temporary_failure_keeps_only_bounded_retry_draft(self):
        await self.accept('caption')
        self.api.interactions.create.side_effect = support.gemini_service.GeminiTemporarilyUnavailable()
        self.context.user_data['_meal_draft_expires_at'] = meal_state.monotonic() + 0.01
        self.assertEqual(await self.confirm(), support.photo.WAITING_CONFIRM)
        self.assertIn('meal_description', self.context.user_data)
        await asyncio.sleep(0.02)
        self.assert_clean()

    async def test_global_error_handler_clears_state_and_logs_type_only(self):
        await self.accept('caption')
        self.context.error = RuntimeError(SENSITIVE)
        with self.assertLogs('services.application', level='ERROR') as captured:
            await support.app.handle_error(self.update(), self.context)
        self.assert_clean()
        self.assertNotIn('FAKE_SECRET', str(captured.output))

    def test_tool_exception_is_safe_in_actual_sdk_function_response(self):
        for name, target, args in (
            ('fatsecret_food_search', 'food_search', {'query': 'rice'}),
            ('fatsecret_get_food', 'get_food', {'food_id': 123}),
        ):
            with self.subTest(tool=name):
                response = types.GenerateContentResponse(candidates=[types.Candidate(
                    content=types.Content(parts=[types.Part.from_function_call(name=name, args=args)]))])
                with patch.object(food_service, target, side_effect=requests.exceptions.ConnectionError(SENSITIVE)), \
                        self.assertLogs('services.fatsecret_food_service', level='WARNING') as captured:
                    parts = _extra_utils.get_function_response_parts(response, {name: getattr(food_service, name)})
                payload = parts[0].function_response.response
                self.assertTrue(payload['result']['error']['retryable'])
                for secret in ('FAKE_SECRET', 'PRIVATE_MEAL', 'example.invalid'):
                    self.assertNotIn(secret, json.dumps(payload))
                    self.assertNotIn(secret, str(captured.output))

    def test_tool_http_and_api_failures_have_safe_codes(self):
        for status in (403, 429, 503):
            response = requests.Response()
            response.status_code = status
            failure = requests.HTTPError(SENSITIVE, response=response)
            with patch.object(food_service, 'get_food', side_effect=failure):
                result = food_service.fatsecret_get_food(123)['error']
            self.assertEqual(result['http_status'], status)
            self.assertEqual(result['retryable'], status in (429, 503))
            self.assertNotIn('FAKE_SECRET', json.dumps(result))
        with patch.object(food_service, 'get_food', side_effect=support.fatsecret_client.FatSecretAPIError('9')):
            self.assertEqual(food_service.fatsecret_get_food(123)['error']['code'], 9)

    def test_full_success_and_empty_search_responses_are_unchanged(self):
        for payload in ({'foods': {'total_results': '0'}},
                        {'foods': {'food': [{'food_id': '123', 'food_description': 'synthetic nutrition'}]}},
                        {'food': {'food_id': '123', 'servings': {'serving': {'calories': '100', 'protein': '5'}}}}):
            for operation, tool, value in (('food_search', food_service.fatsecret_food_search, 'rice'),
                                           ('get_food', food_service.fatsecret_get_food, 123)):
                with patch.object(food_service, operation, return_value=payload):
                    self.assertIs(tool(value), payload)

    def test_api_error_does_not_retain_provider_message(self):
        response = self.oauth.get.return_value
        response.json.return_value = {'error': {'code': '9', 'message': SENSITIVE}}
        with self.assertRaises(support.fatsecret_client.FatSecretAPIError) as raised:
            support.fatsecret_client._parse_fatsecret_response(response)
        self.assertEqual(raised.exception.code, 9)
        self.assertNotIn('FAKE_SECRET', str(raised.exception))

    def test_library_logs_and_tracebacks_are_redacted(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(MetadataOnlyFilter())
        try:
            raise RuntimeError(SENSITIVE)
        except RuntimeError:
            import sys
            record = logging.LogRecord('httpx', logging.ERROR, __file__, 1,
                                       'Request failed %s', (SENSITIVE,), sys.exc_info())
            handler.handle(record)
        self.assertNotIn('FAKE_SECRET', stream.getvalue())
        self.assertNotIn('example.invalid', stream.getvalue())
        self.assertIn('details omitted', stream.getvalue())

    async def test_transient_tool_error_with_fabricated_ids_never_writes(self):
        await self.accept('text')
        unsafe = requests.exceptions.HTTPError(SENSITIVE)
        unsafe.response = type('Response', (), {'status_code': 429})()
        def failed_search(query):
            def operation():
                raise unsafe
            return food_service._safe_tool_call(operation)
        self.tool_search.side_effect = failed_search
        self.api.models.generate_content.side_effect = self.tool_driven_response([('search', 'rice')])
        with patch.object(support.gemini_service.asyncio, 'sleep', new_callable=AsyncMock), \
                self.assertLogs('services.fatsecret_food_service', level='WARNING') as logs:
            self.assertEqual(await self.confirm(), support.photo.WAITING_CONFIRM)
        self.assertEqual(self.api.models.generate_content.call_count, 3)
        self.oauth.post.assert_not_called()
        rendered = str(logs.output) + str(self.status.edit_text.await_args)
        self.assertNotIn('FAKE_SECRET', rendered)
        self.assertNotIn('example.invalid', rendered)

    async def test_unconfirmed_serving_is_rejected_before_write(self):
        await self.accept('text')
        self.fabricate_serving = True
        self.tool_search.side_effect = lambda query: {
            'foods': {'food': {'food_id': '123'}, 'total_results': '1'}}
        self.tool_get.side_effect = lambda food_id: {
            'food': {'food_id': '123', 'servings': {'serving': {'serving_id': '999'}}}}
        self.api.models.generate_content.side_effect = self.tool_driven_response(
            [('search', 'rice'), ('get', 123)])
        self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.oauth.post.assert_not_called()
        self.assert_clean()

    async def test_partial_permanent_tool_error_allows_fully_verified_selection(self):
        await self.accept('text')
        responses = iter((
            {'foods': {'food': {'food_id': '123'}, 'total_results': '1'}},
            {'error': {'type': 'request_failed', 'retryable': False,
                       'http_status': 403, 'code': None}},
        ))
        self.tool_search.side_effect = lambda query: next(responses)
        self.tool_get.side_effect = self.synthetic_food_get
        self.api.models.generate_content.side_effect = self.tool_driven_response(
            [('search', 'rice'), ('search', 'optional alternative'), ('get', 123)])
        self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.oauth.post.assert_called_once()
        self.assert_clean()

    def test_successful_empty_search_is_not_an_api_error(self):
        audit = food_service.FoodToolAudit()
        audit.record_search({'foods': {'total_results': '0'}})
        self.assertEqual(audit.successful_empty_searches, 1)
        self.assertEqual(audit.errors, [])
        self.assertFalse(audit.has_transient_error)

    async def test_reminders_do_not_extend_absolute_deadline(self):
        clock = [100.0]
        with patch.object(meal_state, 'monotonic', side_effect=lambda: clock[0]):
            await support.photo.process_photo(self.update('text'), self.context)
            deadline = self.context.user_data['_meal_draft_expires_at']
            self.assertEqual(deadline, 100.0 + meal_state.MEAL_DRAFT_TTL_SECONDS)
            clock[0] = 500.0
            await support.photo.meal_type_reminder(self.update('text'), self.context)
            self.assertEqual(self.context.user_data['_meal_draft_expires_at'], deadline)

    def test_old_timer_cannot_delete_new_draft(self):
        meal_state.create_meal_draft(self.context.user_data)
        old_token = self.context.user_data['_meal_draft_token']
        meal_state.create_meal_draft(self.context.user_data)
        new_token = self.context.user_data['_meal_draft_token']
        self.context.user_data['meal_description'] = 'new meal'
        meal_state._expire_if_current(self.context.user_data, old_token)
        self.assertIs(self.context.user_data['_meal_draft_token'], new_token)
        self.assertEqual(self.context.user_data['meal_description'], 'new meal')

    async def test_temporary_failure_after_absolute_deadline_cannot_be_retried(self):
        await self.accept('text')
        self.context.user_data['_meal_draft_expires_at'] = meal_state.monotonic() - 1
        self.api.interactions.create.side_effect = support.gemini_service.GeminiTemporarilyUnavailable()
        self.assertEqual(await self.confirm(), ConversationHandler.END)
        self.assert_clean()
        self.oauth.post.assert_not_called()

    def test_late_external_handler_still_receives_redacted_record(self):
        stream = io.StringIO()
        logger = logging.getLogger('httpx.late-handler')
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        logger.propagate = False
        try:
            try:
                raise RuntimeError(SENSITIVE)
            except RuntimeError:
                logger.exception('failed URL=%s', SENSITIVE)
        finally:
            logger.removeHandler(handler)
            logger.propagate = True
        self.assertIn('details omitted', stream.getvalue())
        self.assertNotIn('FAKE_SECRET', stream.getvalue())

    async def test_authorization_failure_omits_exception_content(self):
        update = self.update(callback='fatsecret_auth_start')
        with patch.object(support.fatsecret_auth, 'start_authorization',
                          side_effect=RuntimeError(SENSITIVE)), \
                self.assertLogs('handlers.fatsecret_auth', level='WARNING') as logs:
            result = await support.fatsecret_auth.start_fatsecret_auth(update, self.context)
        self.assertEqual(result, ConversationHandler.END)
        rendered = str(logs.output) + str(self.status.edit_text.await_args)
        self.assertNotIn('FAKE_SECRET', rendered)
        self.assertNotIn('example.invalid', rendered)

    async def test_authorization_telegram_failure_drops_temporary_request_tokens(self):
        update = self.update(callback='fatsecret_auth_start')
        self.status.edit_text.side_effect = NetworkError('synthetic Telegram failure')
        with patch.object(support.fatsecret_auth, 'start_authorization', return_value=(
                'https://authorization.invalid/', 'synthetic-request', 'synthetic-secret')):
            with self.assertRaises(NetworkError):
                await support.fatsecret_auth.start_fatsecret_auth(update, self.context)
        self.assertNotIn('request_token', self.context.user_data)
        self.assertNotIn('request_token_secret', self.context.user_data)


class ExternalTimeoutTests(unittest.TestCase):
    def test_gemini_client_has_bounded_request_timeout(self):
        constructed = Mock()
        with patch.object(gemini_client.genai, 'Client', return_value=constructed) as client:
            self.assertIs(gemini_client._build_client(), constructed)
        options = client.call_args.kwargs['http_options']
        self.assertEqual(options.timeout, 30_000)
        self.assertEqual(options.retry_options.attempts, 1)

    def test_all_fatsecret_requests_have_bounded_timeouts(self):
        oauth = Mock()
        oauth.fetch_request_token.return_value = {
            'oauth_token': 'synthetic-request', 'oauth_token_secret': 'synthetic-secret'}
        oauth.authorization_url.return_value = 'https://authorization.invalid/'
        oauth.get.return_value.text = (
            'oauth_token=synthetic-access&oauth_token_secret=synthetic-access-secret')
        oauth.get.return_value.json.return_value = {'food': {}}
        oauth.post.return_value.json.return_value = {'food_entry_id': '1'}
        with patch.object(support.fatsecret_client, 'OAuth1Session', return_value=oauth):
            support.fatsecret_client.create_authorization('key', 'secret')
            oauth.fetch_request_token.assert_called_once_with(
                support.fatsecret_client.REQUEST_TOKEN_URL, timeout=30)
            support.fatsecret_client.exchange_verifier(
                'key', 'secret', 'request', 'request-secret', 'verifier')
            self.assertEqual(oauth.get.call_args.kwargs['timeout'], 30)
            support.fatsecret_client.food_search('rice', 'key', 'secret')
            self.assertEqual(oauth.get.call_args.kwargs['timeout'], 30)
            support.fatsecret_client.get_food(1, 'key', 'secret')
            self.assertEqual(oauth.get.call_args.kwargs['timeout'], 30)
            support.fatsecret_client.create_food_entry(
                'key', 'secret', 'user-token', 'user-secret', 1, 'Rice', 2, 1, 'lunch', 1)
            self.assertEqual(oauth.post.call_args.kwargs['timeout'], 30)


if __name__ == '__main__':
    unittest.main()
