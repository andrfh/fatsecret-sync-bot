"""Operation-local candidate registry, read budgets and final diary validation."""
from copy import deepcopy
from decimal import Decimal
import logging
import math
from uuid import uuid4

from services.fatsecret_cards import (
    convert_food_search, convert_food_details, _dict_items, _positive_id,
)
from services.fatsecret_food_service import _safe_tool_call

logger = logging.getLogger(__name__)


class UnverifiedFoodSelection(ValueError):
    """Selection cannot be safely converted to diary entries."""


class MatchingBudgetExceeded(UnverifiedFoodSelection):
    """A shared matching budget was exhausted."""


class MatchingOperation:
    # Eight components: two query variants and two inspections each = 32 reads.
    # Reserve 16 more reads for transient retries; no restart resets this budget.
    MAX_FATSECRET_CALLS = 48
    MAX_GEMINI_CALLS = 36  # 32 sequential tool rounds, final answer, 3 spare calls.
    MAX_TOOL_CALLS = 96   # Includes cache hits and invalid requests.
    MAX_ATTEMPTS_PER_READ = 3

    def __init__(self, search, get_food):
        self._search = search
        self._get_food = get_food
        self._prefix = "O" + uuid4().hex
        self.food_ids = {}
        self._refs_by_id = {}
        self.candidates = {}
        self.details = {}
        self.servings = {}
        self.cache = {}
        self.errors = []
        self.pending_errors = {}
        self.read_attempts = {}
        self.fatsecret_calls = 0
        self.gemini_calls = 0
        self.tool_calls = 0
        self.cache_hits = 0
        self.retries = 0
        self.successful_empty_searches = 0
        self.budget_exhausted = False

    @property
    def has_transient_error(self):
        return any(e['retryable'] for e in self.pending_errors.values())

    def take_gemini_call(self):
        if self.gemini_calls >= self.MAX_GEMINI_CALLS:
            raise MatchingBudgetExceeded("Gemini matching budget exhausted")
        self.gemini_calls += 1

    def _error(self, kind, retryable=False, status=None, code=None):
        if kind == 'budget_exhausted':
            self.budget_exhausted = True
        error = dict(type=kind, retryable=retryable, http_status=status, code=code)
        self.errors.append(error)
        return {'error': error}

    def _read(self, key, operation, argument):
        if self.read_attempts.get(key, 0) >= self.MAX_ATTEMPTS_PER_READ:
            return {'error': self.pending_errors.get(key, {
                'type': 'budget_exhausted', 'retryable': False,
                'http_status': None, 'code': None})}
        if self.fatsecret_calls >= self.MAX_FATSECRET_CALLS:
            return self._error('budget_exhausted')
        previous = self.read_attempts.get(key, 0)
        self.read_attempts[key] = previous + 1
        self.fatsecret_calls += 1
        self.retries += int(previous > 0)
        response = _safe_tool_call(operation, argument)
        if not isinstance(response, dict):
            return self._error('invalid_response')
        if 'error' in response:
            raw = response['error'] if isinstance(response['error'], dict) else {}
            status = raw.get('http_status')
            status = status if type(status) is int and 100 <= status <= 599 else None
            code = raw.get('code')
            code = code if type(code) is int else None
            retryable = raw.get('retryable') is True
            result = self._error('temporarily_unavailable' if retryable else 'request_failed',
                                 retryable, status, code)
            self.pending_errors[key] = result['error']
            logger.warning('Matching stage=tool status=%s attempt=%s retryable=%s',
                           status, previous + 1, retryable)
            if not retryable:
                self.cache[key] = result
            return result
        self.pending_errors.pop(key, None)
        return response

    def search_food_candidates(self, query: str) -> dict:
        """Search foods by name/brand. Returns cards and operation-local references."""
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            return self._error('invalid_arguments')
        query = ' '.join(query.split())
        key = ('search', query.casefold())
        if key in self.cache:
            self.cache_hits += 1
            return deepcopy(self.cache[key])
        raw = self._read(key, self._search, query)
        if 'error' in raw:
            return raw
        container = raw.get('foods')
        if not isinstance(container, dict):
            return self._error('invalid_response')
        items = _dict_items(container.get('food'))
        # A malformed response must not masquerade as an empty successful search.
        if not items and str(container.get('total_results')) != '0':
            return self._error('invalid_response')
        cards = []
        seen = set()
        for item in items:
            food_id = _positive_id(item.get('food_id'))
            if food_id is None or food_id in seen:
                continue
            seen.add(food_id)
            ref = self._refs_by_id.get(food_id, f'{self._prefix}-C{len(self.food_ids) + 1}')
            converted = convert_food_search({'foods': {'food': item}}, [ref])
            if not converted.public_cards:
                continue
            card = converted.public_cards[0]
            self.food_ids[ref] = food_id
            self._refs_by_id[food_id] = ref
            self.candidates[ref] = card
            cards.append(card)
        if items and not cards:
            return self._error('invalid_response')
        if not cards:
            self.successful_empty_searches += 1
        result = {'status': 'ok', 'candidates': cards}
        self.cache[key] = result
        return deepcopy(result)

    def get_candidate_portions(self, candidate_ref: str) -> dict:
        """Get servings only for a candidate from this operation's search results."""
        if not isinstance(candidate_ref, str) or candidate_ref not in self.food_ids:
            return self._error('unknown_candidate')
        key = ('get', candidate_ref)
        if key in self.cache:
            self.cache_hits += 1
            return deepcopy(self.cache[key])
        raw = self._read(key, self._get_food, int(self.food_ids[candidate_ref]))
        if 'error' in raw:
            return raw
        food = raw.get('food')
        if not isinstance(food, dict) or _positive_id(food.get('food_id')) != self.food_ids[candidate_ref]:
            return self._error('invalid_response')
        container = food.get('servings')
        items = _dict_items(container.get('serving') if isinstance(container, dict) else None)
        refs = [f'{candidate_ref}-S{i + 1}' for i in range(len(items))]
        converted = convert_food_details(raw, candidate_ref, refs)
        card = converted.public_card
        self.details[candidate_ref] = card
        for serving in card['servings']:
            ref = serving['serving_ref']
            self.servings[ref] = (candidate_ref, converted.serving_ids_by_ref[ref], serving)
        result = {'status': 'ok', **card}
        self.cache[key] = result
        return deepcopy(result)

    def dispatch(self, name, args):
        """The only tool entrypoint used by Gemini; never propagate raw exceptions."""
        if self.tool_calls >= self.MAX_TOOL_CALLS:
            return self._error('budget_exhausted')
        self.tool_calls += 1
        allowed = {'search_food_candidates': ('query', self.search_food_candidates),
                   'get_candidate_portions': ('candidate_ref', self.get_candidate_portions)}
        if not isinstance(name, str) or name not in allowed or not isinstance(args, dict):
            return self._error('invalid_arguments')
        parameter, function = allowed[name]
        if set(args) != {parameter}:
            return self._error('invalid_arguments')
        try:
            return function(args[parameter])
        except Exception as error:
            logger.warning('Matching stage=conversion failed type=%s', type(error).__name__)
            return self._error('invalid_response')

    def resolve(self, data, recognized_meal):
        """Validate the entire meal before producing any private diary payload."""
        if not isinstance(data, dict) or data.get('status') != 'ok':
            raise UnverifiedFoodSelection('No confident match')
        if set(data) != {'status', 'resolution', 'foods'}:
            raise UnverifiedFoodSelection('Unexpected selection fields')
        foods = data.get('foods')
        resolution = data.get('resolution')
        if resolution not in ('whole_meal', 'components') or not isinstance(foods, list) or not 1 <= len(foods) <= 8:
            raise UnverifiedFoodSelection('Invalid selection')
        if resolution == 'whole_meal' and len(foods) != 1:
            raise UnverifiedFoodSelection('Invalid whole meal')
        items = recognized_meal['items']
        covered = set()
        resolved = []
        for choice in foods:
            if not isinstance(choice, dict) or set(choice) != {
                'candidate_ref', 'serving_ref', 'food_name', 'item_indices', 'amount_g'
            }:
                raise UnverifiedFoodSelection('Invalid food selection')
            ref, serving_ref = choice['candidate_ref'], choice['serving_ref']
            if not isinstance(ref, str) or not isinstance(serving_ref, str):
                raise UnverifiedFoodSelection('Invalid references')
            record = self.servings.get(serving_ref)
            if ref not in self.food_ids or ref not in self.details or not record or record[0] != ref:
                raise UnverifiedFoodSelection('Unconfirmed references')
            _, serving_id, serving = record
            if not serving['diary_eligible'] or _positive_id(serving_id) is None:
                raise UnverifiedFoodSelection('Serving is not writable')
            name = choice['food_name']
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                raise UnverifiedFoodSelection('Invalid display name')
            indices = choice['item_indices']
            if not isinstance(indices, list) or not indices or any(
                type(i) is not int or i < 0 or i >= len(items) for i in indices
            ) or len(set(indices)) != len(indices) or covered.intersection(indices):
                raise UnverifiedFoodSelection('Invalid component coverage')
            covered.update(indices)
            mass = sum(Decimal(str(items[i]['amount_g'])) for i in indices)
            claimed = choice['amount_g']
            if type(claimed) not in (float, int) or not math.isfinite(claimed) or claimed <= 0 or Decimal(str(claimed)) != mass:
                raise UnverifiedFoodSelection('Unconfirmed amount')
            nutrition = serving['nutrition']
            if nutrition['status'] != 'complete' or not self.details[ref]['name']:
                raise UnverifiedFoodSelection('Incomplete nutrition')
            metric = serving['metric_quantity']
            units = serving['standard_quantity']['value']
            if not metric or metric['unit'] not in ('g', 'oz') or units is None:
                raise UnverifiedFoodSelection('No reliable serving mass')
            standard_mass = Decimal(str(metric['value']))
            if metric['unit'] == 'oz':
                standard_mass *= Decimal('28.349523125')
            food_type = self.details[ref]['food_type']
            if food_type == 'brand':
                # food_entry.create documents Brand number_of_units = 1 only.
                # No rounding or inferred package counts; exact mass is required.
                if units != 1 or mass != standard_mass:
                    raise UnverifiedFoodSelection('Branded serving does not match amount')
                quantity = 1.0
            elif food_type == 'generic':
                quantity = float(mass * Decimal(str(units)) / standard_mass)
            else:
                raise UnverifiedFoodSelection('Unknown food type')
            if not math.isfinite(quantity) or quantity <= 0:
                raise UnverifiedFoodSelection('Invalid calculated quantity')
            factor = mass / standard_mass
            try:
                calculated_nutrition = {
                    key: float(Decimal(str(nutrition[key])) * factor)
                    for key in ('calories_kcal', 'protein_g', 'fat_g', 'carbohydrate_g')
                }
            except (OverflowError, ValueError):
                raise UnverifiedFoodSelection('Invalid calculated nutrition') from None
            if any(not math.isfinite(value) or value < 0
                   for value in calculated_nutrition.values()):
                raise UnverifiedFoodSelection('Invalid calculated nutrition')
            official_name = self.details[ref]['name']
            resolved.append({
                'food_name': official_name,
                'food_id': int(self.food_ids[ref]),
                'serving_id': int(serving_id),
                'number_of_units': quantity,
                'review': {
                    'food_name': official_name,
                    'serving_description': serving['description'],
                    'standard_quantity': deepcopy(serving['standard_quantity']),
                    'entry_quantity': {
                        'value': quantity,
                        'unit': serving['standard_quantity']['unit'],
                    },
                    'mass_g': float(mass),
                    'nutrition': calculated_nutrition,
                },
            })
        if covered != set(range(len(items))):
            raise UnverifiedFoodSelection('Incomplete component coverage')
        return {'resolution': resolution, 'foods': resolved}
