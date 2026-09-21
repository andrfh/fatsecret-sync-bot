"""Synthetic registry and complete SDK tool-loop regressions; network forbidden."""
import copy
import json
import math
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import requests
from google import genai
from google.genai import types

import test_meal_input as support
from test_fatsecret_cards import search_food, serving, details_response
from services.matching_operation import MatchingOperation, MatchingBudgetExceeded, UnverifiedFoodSelection
from services import fatsecret_cards
from test_transient_errors import api_error


def result_for(card, amount=150, indices=None):
    return {'status': 'ok', 'resolution': 'whole_meal', 'foods': [{
        'candidate_ref': card['candidate_ref'], 'serving_ref': card['servings'][0]['serving_ref'],
        'food_name': 'Synthetic food', 'amount_g': amount,
        'item_indices': [0] if indices is None else indices}]}


def generic_response(**overrides):
    return details_response(serving(number_of_units='100', measurement_description='g',
                                    metric_serving_amount='100', **overrides), food_type='Generic')


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')))
        self.search = Mock(return_value={'foods': {'food': search_food(food_type='Generic')}})
        self.get = Mock(return_value=generic_response())
        self.op = MatchingOperation(self.search, self.get)

    def inspect(self, operation=None):
        op = operation or self.op
        ref = op.dispatch('search_food_candidates', {'query': 'rice'})['candidates'][0]['candidate_ref']
        return op.dispatch('get_candidate_portions', {'candidate_ref': ref})

    def test_generic_grams_are_calculated_on_server(self):
        selected = self.op.resolve(result_for(self.inspect()), support.MEAL)
        self.assertEqual(selected['foods'][0]['number_of_units'], 150)
        self.assertEqual(selected['foods'][0]['food_id'], 910001)

    def test_mass_ounces_are_converted(self):
        self.get.return_value = details_response(serving(number_of_units='1',
            metric_serving_amount='2', metric_serving_unit='oz'), food_type='Generic')
        selected = self.op.resolve(result_for(self.inspect()), support.MEAL)
        self.assertAlmostEqual(selected['foods'][0]['number_of_units'], 150 / (2 * 28.349523125))

    def test_fractional_standard_quantity(self):
        self.get.return_value = details_response(serving(number_of_units='0.5',
            metric_serving_amount='100'), food_type='Generic')
        selected = self.op.resolve(result_for(self.inspect()), support.MEAL)
        self.assertEqual(selected['foods'][0]['number_of_units'], .75)

    def test_brand_one_exact_original_serving(self):
        self.get.return_value = details_response(serving(metric_serving_amount='150'))
        self.assertEqual(self.op.resolve(result_for(self.inspect()), support.MEAL)['foods'][0]['number_of_units'], 1)

    def test_brand_cannot_round_mass_or_multiply_packages(self):
        self.get.return_value = details_response(serving(metric_serving_amount='100'))
        with self.assertRaises(UnverifiedFoodSelection):
            self.op.resolve(result_for(self.inspect()), support.MEAL)

    def test_bad_servings_nutrition_and_mass_are_rejected(self):
        for overrides in ({'serving_id': '0'}, {'serving_id': None}, {'serving_id': '-4'},
                          {'protein': None}, {'fat': 'NaN'}, {'calories': 'Infinity'},
                          {'metric_serving_amount': None}, {'metric_serving_unit': 'ml'},
                          {'metric_serving_amount': '-1'}, {'number_of_units': '0'}):
            with self.subTest(overrides=overrides):
                self.get.return_value = details_response(serving(**overrides), food_type='Generic')
                op = MatchingOperation(self.search, self.get)
                with self.assertRaises(UnverifiedFoodSelection):
                    op.resolve(result_for(self.inspect(op)), support.MEAL)

    def test_incomplete_search_nutrition_can_be_resolved_by_details(self):
        self.search.return_value['foods']['food']['food_description'] = 'not parseable'
        self.assertEqual(self.op.resolve(result_for(self.inspect()), support.MEAL)['foods'][0]['number_of_units'], 150)

    def test_repeat_search_cache_and_stable_ref_across_queries(self):
        first = self.op.dispatch('search_food_candidates', {'query': 'Rice'})
        again = self.op.dispatch('search_food_candidates', {'query': '  rice  '})
        alternative = self.op.dispatch('search_food_candidates', {'query': 'boiled rice'})
        self.assertEqual(first, again)
        self.assertEqual(first['candidates'][0]['candidate_ref'], alternative['candidates'][0]['candidate_ref'])
        self.assertEqual(self.search.call_count, 2)
        ref = first['candidates'][0]['candidate_ref']
        a = self.op.dispatch('get_candidate_portions', {'candidate_ref': ref})
        b = self.op.dispatch('get_candidate_portions', {'candidate_ref': ref})
        self.assertEqual(a, b)
        self.get.assert_called_once()
        a['servings'][0]['diary_eligible'] = False
        self.assertTrue(self.op.details[ref]['servings'][0]['diary_eligible'])

    def test_refs_from_another_operation_never_work(self):
        card = self.inspect()
        other = MatchingOperation(self.search, self.get)
        other_card = self.inspect(other)
        self.assertNotEqual(card['candidate_ref'], other_card['candidate_ref'])
        with self.assertRaises(UnverifiedFoodSelection):
            other.resolve(result_for(card), support.MEAL)
        before = self.get.call_count
        self.assertEqual(other.dispatch('get_candidate_portions', {
            'candidate_ref': card['candidate_ref']})['error']['type'], 'unknown_candidate')
        self.assertEqual(self.get.call_count, before)

    def test_unknown_ref_or_raw_id_cannot_call_food_get(self):
        for ref in ('made-up', '910001', 910001, None, []):
            self.assertIn('error', self.op.dispatch('get_candidate_portions', {'candidate_ref': ref}))
        self.get.assert_not_called()

    def test_food_details_must_match_searched_id(self):
        self.get.return_value['food']['food_id'] = 'different'
        self.assertEqual(self.inspect()['error']['type'], 'invalid_response')
        self.assertFalse(self.op.servings)

    def test_serving_cannot_belong_to_another_candidate(self):
        first = self.inspect()
        self.search.return_value = {'foods': {'food': search_food(food_id='910002')}}
        ref = self.op.dispatch('search_food_candidates', {'query': 'second'})['candidates'][0]['candidate_ref']
        data = result_for(first)
        data['foods'][0]['candidate_ref'] = ref
        with self.assertRaises(UnverifiedFoodSelection):
            self.op.resolve(data, support.MEAL)

    def test_fabricated_or_nonfinite_quantity_and_raw_ids_rejected(self):
        card = self.inspect()
        for amount in (0, -1, 140, math.inf, math.nan, True, '150'):
            with self.subTest(amount=amount), self.assertRaises(UnverifiedFoodSelection):
                self.op.resolve(result_for(card, amount), support.MEAL)
        data = result_for(card)
        data['foods'][0]['food_id'] = 910001
        with self.assertRaises(UnverifiedFoodSelection):
            self.op.resolve(data, support.MEAL)

    def test_coverage_cannot_drop_or_duplicate_components(self):
        card = self.inspect()
        meal = copy.deepcopy(support.MEAL)
        meal['items'].append({'name': 'second', 'brand': None, 'amount_g': 50})
        for indices in ([0], [0, 0], [0, 2], [False]):
            with self.subTest(indices=indices), self.assertRaises(UnverifiedFoodSelection):
                self.op.resolve(result_for(card, 150, indices), meal)
        whole = self.op.resolve(result_for(card, 200, [0, 1]), meal)
        self.assertEqual(whole['foods'][0]['number_of_units'], 200)

    def test_empty_success_distinct_from_malformed_and_error(self):
        self.search.return_value = {'foods': {'total_results': '0'}}
        result = self.op.dispatch('search_food_candidates', {'query': 'none'})
        self.assertEqual(result, {'status': 'ok', 'candidates': []})
        self.assertEqual(self.op.successful_empty_searches, 1)
        self.assertFalse(self.op.errors)
        self.search.return_value = {'foods': {'food': 'malformed'}}
        self.assertEqual(self.op.dispatch('search_food_candidates', {'query': 'bad'})['error']['type'], 'invalid_response')

    def test_permanent_errors_are_cached_and_sanitized(self):
        self.search.return_value = {'error': {'retryable': False, 'http_status': 403,
            'message': 'https://secret.invalid/?oauth_token=FAKE_TOKEN', 'code': 'FAKE_TOKEN'}}
        one = self.op.dispatch('search_food_candidates', {'query': 'rice'})
        two = self.op.dispatch('search_food_candidates', {'query': 'rice'})
        self.assertEqual(one, two)
        self.search.assert_called_once()
        self.assertFalse(self.op.has_transient_error)
        self.assertNotIn('FAKE_TOKEN', json.dumps(one))

    def test_transient_reads_have_three_attempt_limit(self):
        self.search.side_effect = requests.ConnectionError('https://secret.invalid/?oauth_token=FAKE_TOKEN')
        for _ in range(8):
            result = self.op.dispatch('search_food_candidates', {'query': 'rice'})
            self.assertTrue(result['error']['retryable'])
        self.assertEqual(self.search.call_count, 3)
        self.assertEqual(self.op.retries, 2)
        self.assertNotIn('FAKE_TOKEN', json.dumps(result))

    def test_fatsecret_gemini_and_tool_budgets(self):
        self.op.MAX_FATSECRET_CALLS = 2
        for i in range(3):
            result = self.op.dispatch('search_food_candidates', {'query': f'rice {i}'})
        self.assertEqual(result['error']['type'], 'budget_exhausted')
        self.assertEqual(self.search.call_count, 2)
        self.op.MAX_GEMINI_CALLS = 1
        self.op.take_gemini_call()
        with self.assertRaises(MatchingBudgetExceeded):
            self.op.take_gemini_call()
        self.op.MAX_TOOL_CALLS = self.op.tool_calls
        self.assertEqual(self.op.dispatch('search_food_candidates', {'query': 'rice'})['error']['type'], 'budget_exhausted')

    def test_partial_failure_allows_only_complete_verified_meal(self):
        card = self.inspect()
        self.search.return_value = {'error': {'retryable': False}}
        self.op.dispatch('search_food_candidates', {'query': 'optional alternative'})
        self.assertEqual(self.op.resolve(result_for(card), support.MEAL)['foods'][0]['food_id'], 910001)
        invalid = result_for(card)
        invalid['foods'][0]['serving_ref'] = 'invented'
        with self.assertRaises(UnverifiedFoodSelection):
            self.op.resolve(invalid, support.MEAL)

    def test_card_parser_rejects_ambiguous_bases_and_overflow(self):
        for description in ('Per 0 g - Calories: 10kcal',
                            'Per 100 g or ml - Calories: 10kcal'):
            result = fatsecret_cards.convert_food_search({'foods': {'food': search_food(
                food_description=description)}}, ['C1'])
            self.assertIsNone(result.public_cards[0]['nutrition']['basis'])
        result = fatsecret_cards.convert_food_details(details_response(serving(
            calories='9' * 400 + '.1')), 'C1', ['S1'])
        self.assertIsNone(result.public_card['servings'][0]['nutrition']['calories_kcal'])
        json.dumps(result.public_card, allow_nan=False)

    def test_provider_text_cannot_smuggle_ids_urls_or_credentials(self):
        self.search.return_value = {'foods': {'food': search_food(
            food_name='Synthetic https://private.invalid/?oauth_token=FAKE_TOKEN',
            food_description='oauth_token=FAKE_TOKEN | Per 100g - Calories: 10kcal')}}
        result = self.op.dispatch('search_food_candidates', {'query': 'synthetic'})
        for token in ('FAKE_TOKEN', 'private.invalid', '910001', 'food_description'):
            self.assertNotIn(token, json.dumps(result))
        self.get.return_value = details_response(serving(serving_description='Provider serving 920001'),
                                                  food_name='Provider food 910001')
        detail = self.op.dispatch('get_candidate_portions', {
            'candidate_ref': result['candidates'][0]['candidate_ref']})
        self.assertNotIn('920001', json.dumps(detail))
        self.assertNotIn('910001', json.dumps(detail))

    def test_dispatch_catches_conversion_errors_without_sensitive_text(self):
        with patch('services.matching_operation.convert_food_search',
                   side_effect=ValueError('https://private.invalid/?oauth_token=FAKE_TOKEN')), \
                self.assertLogs('services.matching_operation', level='WARNING') as logs:
            result = self.op.dispatch('search_food_candidates', {'query': 'rice'})
        self.assertEqual(result['error']['type'], 'invalid_response')
        self.assertNotIn('FAKE_TOKEN', json.dumps(result) + str(logs.output))

    def test_duplicate_raw_foods_keep_one_stable_ref(self):
        self.search.return_value['foods']['food'] = [search_food(), search_food()]
        result = self.op.dispatch('search_food_candidates', {'query': 'rice'})
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(len(self.op.food_ids), 1)

    def test_wrong_tool_arguments_do_not_reach_clients(self):
        for name, args in [('unknown', {}), ('get_candidate_portions', {'food_id': 910001}),
                           ('search_food_candidates', {'query': 'rice', 'page': 1}),
                           ('search_food_candidates', {'query': []})]:
            self.assertIn('error', self.op.dispatch(name, args))
        self.search.assert_not_called()
        self.get.assert_not_called()


class SDKIntegrationTests(support.MealTestSupport, unittest.IsolatedAsyncioTestCase):
    """Use real SDK serialization and function responses, mock only HTTP transport."""
    def setUp(self):
        super().setUp()
        self.sleep = self.enterContext(patch.object(support.gemini_service.asyncio, 'sleep', new_callable=AsyncMock))
        self.sdk = genai.Client(api_key='offline-synthetic-key', http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1)))
        self.addCleanup(self.sdk.close)
        self.enterContext(patch.object(support.gemini_client, 'client', self.sdk))
        self.enterContext(patch.object(self.sdk.interactions, 'create',
            side_effect=lambda **kwargs: self.api.interactions.create(**kwargs)))
        self.http = self.enterContext(patch.object(self.sdk._api_client, 'request', side_effect=self.transport))
        self.tool_search.side_effect = lambda q: {'foods': {'food': search_food(food_type='Generic')}}
        self.tool_get.side_effect = lambda f: generic_response()
        self.requests = []
        self.mode = 'success'

    def transport(self, method, path, body, options):
        self.requests.append(copy.deepcopy(body))
        contents = body['contents']
        last = contents[-1]['parts']
        responses = [p['functionResponse'] for p in last if 'functionResponse' in p]
        if not responses:
            if self.mode == 'unknown':
                parts = [{'functionCall': {'name': 'get_candidate_portions', 'args': {'candidate_ref': '910001'}}}]
            else:
                parts = [{'functionCall': {'name': 'search_food_candidates', 'args': {'query': 'rice'}}}]
        elif self.mode == 'loop':
            parts = [{'functionCall': {'name': 'search_food_candidates', 'args': {'query': 'rice'}}}]
        elif 'error' in responses[0]['response'] or not responses[0]['response'].get('candidates', [1]):
            # A model still trying to select fabricated references after a failed tool.
            parts = [{'text': json.dumps({'status': 'ok', 'resolution': 'whole_meal', 'foods': [{
                'candidate_ref': 'fabricated', 'serving_ref': 'fabricated', 'food_name': 'Rice',
                'amount_g': 150, 'item_indices': [0]}]})}]
        elif responses[0]['name'] == 'search_food_candidates':
            ref = responses[0]['response']['candidates'][0]['candidate_ref']
            parts = [{'functionCall': {'name': 'get_candidate_portions', 'args': {'candidate_ref': ref}}}]
        else:
            data = result_for(responses[0]['response'])
            if self.mode == 'forged':
                data['foods'][0]['serving_ref'] += '-forged'
            parts = [{'text': json.dumps(data)}]
        return types.HttpResponse(headers={}, body=json.dumps({
            'candidates': [{'content': {'role': 'model', 'parts': parts}, 'finishReason': 'STOP'}]}))

    async def test_real_sdk_serialization_and_generic_success(self):
        await self.accept('text')
        await self.confirm()
        self.oauth.post.assert_called_once()
        self.assertEqual(self.oauth.post.call_args.kwargs['data']['number_of_units'], 150)
        self.assertEqual(self.http.call_count, 3)
        payload = json.dumps(self.requests)
        for forbidden in ('910001', '920001', 'provider.invalid', 'food_id', 'serving_id', 'oauth_token'):
            self.assertNotIn(forbidden, payload)
        tools = self.requests[0]['tools'][0]['functionDeclarations']
        self.assertEqual({t['name'] for t in tools}, {'search_food_candidates', 'get_candidate_portions'})
        self.assert_clean()

    async def test_real_sdk_brand_success(self):
        self.tool_search.side_effect = lambda q: {'foods': {'food': search_food()}}
        self.tool_get.side_effect = lambda f: details_response(serving(metric_serving_amount='150'))
        await self.accept('text')
        await self.confirm()
        self.oauth.post.assert_called_once()
        self.assertEqual(self.oauth.post.call_args.kwargs['data']['number_of_units'], 1)

    async def test_unknown_and_forged_refs_never_write(self):
        for mode in ('unknown', 'forged'):
            with self.subTest(mode=mode):
                self.mode = mode
                self.tool_get.reset_mock()
                await self.accept('text')
                await self.confirm()
                if mode == 'unknown':
                    self.tool_get.assert_not_called()
                self.oauth.post.assert_not_called()
                self.assertEqual(self.status.edit_text.await_args.args[0], support.ui_text('ru', 'matching_uncertain'))
                self.assert_clean()

    async def test_invalid_portions_do_not_write_through_handler(self):
        for overrides in ({'serving_id': '0'}, {'protein': None},
                          {'metric_serving_unit': 'ml'}, {'metric_serving_amount': None}):
            with self.subTest(overrides=overrides):
                self.tool_get.side_effect = lambda f: details_response(serving(**overrides), food_type='Generic')
                await self.accept('text')
                await self.confirm()
                self.oauth.post.assert_not_called()
                self.assert_clean()

    async def test_retry_matching_reuses_search_cache_and_writes_once(self):
        calls = 0
        def detail(food_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise requests.ConnectionError('https://private.invalid/?oauth_token=FAKE_TOKEN')
            return generic_response()
        self.tool_get.side_effect = detail
        await self.accept('text')
        with self.assertLogs(level='WARNING') as logs:
            await self.confirm()
        self.tool_search.assert_called_once()
        self.assertEqual(self.tool_get.call_count, 2)
        self.oauth.post.assert_called_once()
        output = json.dumps(self.requests) + str(logs.output) + str(self.status.edit_text.await_args_list)
        self.assertNotIn('FAKE_TOKEN', output)
        self.assertNotIn('private.invalid', output)
        self.assert_clean()

    async def test_exhausted_transient_error_cannot_accept_fabricated_refs(self):
        failure = requests.HTTPError('https://private.invalid/?oauth_token=FAKE_TOKEN')
        failure.response = SimpleNamespace(status_code=429)
        self.tool_search.side_effect = failure
        await self.accept('text')
        self.assertEqual(await self.confirm(), support.photo.WAITING_CONFIRM)
        self.assertEqual(self.tool_search.call_count, 3)
        self.oauth.post.assert_not_called()
        self.assertNotIn('FAKE_TOKEN', json.dumps(self.requests))

    async def test_empty_search_ends_without_write_or_retry(self):
        self.tool_search.side_effect = lambda q: {'foods': {'total_results': '0'}}
        await self.accept('text')
        await self.confirm()
        self.tool_search.assert_called_once()
        self.oauth.post.assert_not_called()
        self.assert_clean()

    async def test_actual_sdk_loop_stops_at_shared_gemini_budget(self):
        self.mode = 'loop'
        await self.accept('text')
        await self.confirm()
        self.assertEqual(self.http.call_count, MatchingOperation.MAX_GEMINI_CALLS)
        self.tool_search.assert_called_once()
        self.oauth.post.assert_not_called()
        self.assert_clean()

    async def test_gemini_failure_after_tools_preserves_cache_and_budget(self):
        failed = False
        def transport(method, path, body, options):
            nonlocal failed
            if not failed and len(body['contents']) == 5:
                failed = True
                raise api_error(503)
            return self.transport(method, path, body, options)
        self.http.side_effect = transport
        await self.accept('text')
        await self.confirm()
        self.assertEqual(self.http.call_count, 6)
        self.tool_search.assert_called_once()
        self.tool_get.assert_called_once()
        self.oauth.post.assert_called_once()
        self.assert_clean()

    async def test_budget_does_not_reset_on_gemini_retry(self):
        failed = False
        def transport(method, path, body, options):
            nonlocal failed
            if not failed and len(body['contents']) == 3:
                failed = True
                raise api_error(503)
            return self.transport(method, path, body, options)
        self.http.side_effect = transport
        await self.accept('text')
        with patch.object(MatchingOperation, 'MAX_GEMINI_CALLS', 3):
            await self.confirm()
        self.assertEqual(self.http.call_count, 3)
        self.tool_search.assert_called_once()
        self.oauth.post.assert_not_called()
        self.assert_clean()

    async def test_read_budget_exhaustion_ends_without_retry(self):
        await self.accept('text')
        with patch.object(MatchingOperation, 'MAX_FATSECRET_CALLS', 1):
            await self.confirm()
        self.tool_get.assert_not_called()
        self.tool_search.assert_called_once()
        self.sleep.assert_not_awaited()
        self.oauth.post.assert_not_called()
        self.assert_clean()

    async def test_eight_components_fit_budget_and_write_once_each(self):
        meal = copy.deepcopy(support.MEAL)
        meal['items'] = [dict(name=f'item {i}', brand=None, amount_g=150) for i in range(8)]
        self.api.interactions.create.return_value.output_text = json.dumps(meal)
        self.set_entry_results(['success'] * 8)
        self.tool_search.side_effect = lambda q: {'foods': {'food': search_food(food_id=str(910001 + int(q)))}}
        self.tool_get.side_effect = lambda f: details_response(serving(), food_id=str(f), food_type='Generic')
        def transport(method, path, body, options):
            history = body['contents']
            details = [p['functionResponse']['response'] for content in history for p in content['parts']
                       if 'functionResponse' in p and p['functionResponse']['name'] == 'get_candidate_portions']
            index = len(details)
            responses = [p['functionResponse'] for p in history[-1]['parts'] if 'functionResponse' in p]
            if index == 8:
                foods = [result_for(d, 150, [i])['foods'][0] for i, d in enumerate(details)]
                parts = [{'text': json.dumps(dict(status='ok', resolution='components', foods=foods))}]
            elif responses and responses[0]['name'] == 'search_food_candidates':
                ref = responses[0]['response']['candidates'][0]['candidate_ref']
                parts = [{'functionCall': {'name': 'get_candidate_portions', 'args': {'candidate_ref': ref}}}]
            else:
                parts = [{'functionCall': {'name': 'search_food_candidates', 'args': {'query': str(index)}}}]
            return types.HttpResponse(headers={}, body=json.dumps({'candidates': [
                {'content': {'role': 'model', 'parts': parts}}]}))
        self.http.side_effect = transport
        await self.accept('text')
        await self.confirm()
        self.assertEqual(self.http.call_count, 17)
        self.assertEqual(self.tool_search.call_count, 8)
        self.assertEqual(self.tool_get.call_count, 8)
        self.assertEqual(self.oauth.post.call_count, 8)
        self.assertEqual(len({c.kwargs['data']['food_id'] for c in self.oauth.post.call_args_list}), 8)
        self.assert_clean()


if __name__ == '__main__':
    unittest.main()
