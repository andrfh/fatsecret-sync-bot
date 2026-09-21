"""Pure conversion of FatSecret responses into model-safe food cards.

The functions in this module do not perform I/O. Public cards deliberately omit
provider identifiers and URLs; the corresponding identifiers are returned in a
separate internal mapping for a future operation-local registry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import math
from typing import Any


_CANDIDATE_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_SERVING_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_DESCRIPTION_BASIS_RE = re.compile(
    r"\bPer\s+(?P<basis>.+?)\s*-\s*"
    r"(?=(?:Calories|Fat|Carbs|Carbohydrates?|Protein)\s*:)",
    re.IGNORECASE,
)
_DESCRIPTION_NUTRIENT_RE = re.compile(
    r"(?:^|\|)\s*(?P<label>Calories|Fat|Carbs|Carbohydrates?|Protein)\s*:"
    r"\s*(?P<value>[^|]+)",
    re.IGNORECASE,
)
_PARENTHETICAL_RE = re.compile(r"[\[(]([^\])]+)[\])]")


@dataclass(frozen=True)
class SearchCardsConversion:
    """Public search cards and their private candidate-to-food mapping."""

    public_cards: list[dict[str, Any]]
    food_ids_by_candidate_ref: dict[str, str]


@dataclass(frozen=True)
class ServingCardConversion:
    """A public food card and private identifiers from a food/v5 response."""

    public_card: dict[str, Any] | None
    food_id: str | None
    serving_ids_by_ref: dict[str, str | None]


def convert_food_search(
    response: Mapping[str, Any] | None,
    candidate_refs: Sequence[str],
) -> SearchCardsConversion:
    """Convert foods/search/v1 into public cards and a private ID mapping.

    ``candidate_refs`` contains one caller-owned reference for each structurally
    valid food object, in response order. Foods without a positive ``food_id``
    cannot be inspected safely and are omitted from both results.
    """

    foods_container = response.get("foods") if isinstance(response, Mapping) else None
    raw_foods = _dict_items(foods_container.get("food") if isinstance(foods_container, Mapping) else None)
    refs = _validated_refs(candidate_refs, len(raw_foods), _CANDIDATE_REF_RE, "candidate")

    public_cards: list[dict[str, Any]] = []
    food_ids: dict[str, str] = {}
    for food, candidate_ref in zip(raw_foods, refs):
        food_id = _positive_id(food.get("food_id"))
        if food_id is None:
            continue
        public_cards.append(_without_identifiers(_search_card(food, candidate_ref), [food_id]))
        food_ids[candidate_ref] = food_id

    return SearchCardsConversion(public_cards, food_ids)


def convert_food_details(
    response: Mapping[str, Any] | None,
    candidate_ref: str,
    serving_refs: Sequence[str],
) -> ServingCardConversion:
    """Convert food/v5 into one public card and separate private identifiers."""

    candidate_ref = _validated_ref(candidate_ref, _CANDIDATE_REF_RE, "candidate")
    food = response.get("food") if isinstance(response, Mapping) else None
    if not isinstance(food, Mapping):
        if serving_refs:
            raise ValueError("serving_refs must be empty when the food is absent")
        return ServingCardConversion(None, None, {})

    servings_container = food.get("servings")
    raw_servings = _dict_items(
        servings_container.get("serving") if isinstance(servings_container, Mapping) else None
    )
    refs = _validated_refs(serving_refs, len(raw_servings), _SERVING_REF_RE, "serving")

    public_servings: list[dict[str, Any]] = []
    serving_ids: dict[str, str | None] = {}
    for serving, serving_ref in zip(raw_servings, refs):
        normalized_id, eligible, reason = _serving_id_status(serving.get("serving_id"))
        serving_ids[serving_ref] = normalized_id
        public_servings.append(
            _serving_card(serving, serving_ref, eligible=eligible, ineligible_reason=reason)
        )

    card = _food_identity(food, candidate_ref)
    card["servings"] = public_servings
    food_id = _positive_id(food.get("food_id"))
    card = _without_identifiers(card, [food_id, *serving_ids.values()])
    return ServingCardConversion(card, food_id, serving_ids)


def _search_card(food: Mapping[str, Any], candidate_ref: str) -> dict[str, Any]:
    card = _food_identity(food, candidate_ref)
    description = _clean_text(food.get("food_description"))
    nutrition, description_feature = _parse_food_description(description)
    card["features"] = _features(food.get("food_name"), description_feature)
    card["nutrition"] = nutrition
    return card


def _food_identity(food: Mapping[str, Any], candidate_ref: str) -> dict[str, Any]:
    food_name = _clean_text(food.get("food_name"))
    brand = _clean_text(food.get("brand_name"))
    if food_name and brand and brand.casefold() not in food_name.casefold():
        full_name = f"{brand} {food_name}"
    else:
        full_name = food_name or brand

    food_type_value = _clean_text(food.get("food_type"))
    food_type_lookup = {"generic": "generic", "brand": "brand"}
    return {
        "candidate_ref": candidate_ref,
        "name": full_name,
        "brand": brand,
        "food_type": food_type_lookup.get(food_type_value.casefold(), "unknown")
        if food_type_value
        else "unknown",
        "features": _features(food_name, None),
    }


def _serving_card(
    serving: Mapping[str, Any],
    serving_ref: str,
    *,
    eligible: bool,
    ineligible_reason: str | None,
) -> dict[str, Any]:
    description = _clean_text(serving.get("serving_description"))
    number_of_units = _nonnegative_number(serving.get("number_of_units"), allow_zero=False)
    measurement = _clean_text(serving.get("measurement_description"))
    metric_amount = _nonnegative_number(serving.get("metric_serving_amount"), allow_zero=False)
    metric_unit = _metric_unit(serving.get("metric_serving_unit"))
    metric_quantity = (
        {"value": metric_amount, "unit": metric_unit}
        if metric_amount is not None and metric_unit is not None
        else None
    )

    macros = _structured_macros(serving)
    has_basis = bool(description or number_of_units is not None or measurement or metric_quantity)
    present_macros = sum(value is not None for value in macros.values())
    if present_macros == 4 and has_basis:
        status = "complete"
    elif present_macros or has_basis:
        status = "partial"
    else:
        status = "missing"

    return {
        "serving_ref": serving_ref,
        "description": description,
        "standard_quantity": {
            "value": number_of_units,
            "unit": measurement,
        },
        "metric_quantity": metric_quantity,
        "nutrition": {
            "status": status,
            "basis": "this_standard_serving",
            **macros,
        },
        "diary_eligible": eligible,
        "diary_ineligible_reason": ineligible_reason,
    }


def _parse_food_description(description: str | None) -> tuple[dict[str, Any], str | None]:
    empty_macros = {
        "calories_kcal": None,
        "protein_g": None,
        "fat_g": None,
        "carbohydrate_g": None,
    }
    if description is None:
        return {"status": "missing", "basis": None, **empty_macros}, None

    basis_match = _DESCRIPTION_BASIS_RE.search(description)
    if len(list(_DESCRIPTION_BASIS_RE.finditer(description))) > 1:
        return {"status": "unparsed", "basis": None, **empty_macros}, None
    basis = _description_basis(basis_match.group("basis")) if basis_match else None
    description_feature = _description_feature(description, basis_match)

    macros = dict(empty_macros)
    seen: set[str] = set()
    duplicate: set[str] = set()
    nutrient_text = description[basis_match.end():] if basis_match else description
    for match in _DESCRIPTION_NUTRIENT_RE.finditer(nutrient_text):
        label = match.group("label").casefold()
        key, unit = _description_nutrient_contract(label)
        if key in seen:
            duplicate.add(key)
            macros[key] = None
            continue
        seen.add(key)
        macros[key] = _number_with_unit(match.group("value"), unit)
    for key in duplicate:
        macros[key] = None

    parsed_count = sum(value is not None for value in macros.values())
    if basis is not None and parsed_count == 4 and not duplicate:
        status = "complete"
    elif basis is not None or parsed_count:
        status = "partial"
    else:
        status = "unparsed"

    return {"status": status, "basis": basis, **macros}, description_feature


def _description_basis(value: str) -> dict[str, Any] | None:
    description = _clean_text(value)
    if description is None:
        return None

    exact_metric = re.fullmatch(
        r"(?P<value>[+]?(?:\d+(?:\.\d*)?|\.\d+))\s*"
        r"(?P<unit>g|grams?|ml|millilit(?:er|re)s?|oz|fl\s*oz)",
        description,
        re.IGNORECASE,
    )
    if exact_metric:
        amount = _nonnegative_number(exact_metric.group("value"), allow_zero=False)
        if amount is None:
            return None
        unit_text = re.sub(r"\s+", " ", exact_metric.group("unit").casefold())
        unit_map = {
            "g": "g",
            "gram": "g",
            "grams": "g",
            "ml": "ml",
            "milliliter": "ml",
            "milliliters": "ml",
            "millilitre": "ml",
            "millilitres": "ml",
            "oz": "oz",
            "fl oz": "fl oz",
        }
        unit = unit_map[unit_text]
        kind = "volume" if unit in ("ml", "fl oz") else "mass"
        return {"kind": kind, "value": amount, "unit": unit, "description": description}

    portion = re.fullmatch(
        r"(?P<value>[+]?(?:\d+(?:\.\d*)?|\.\d+))\s+(?P<unit>.+)",
        description,
    )
    if not portion:
        return None
    amount = _nonnegative_number(portion.group("value"), allow_zero=False)
    unit = _clean_text(portion.group("unit").split("(", 1)[0])
    if amount is None or unit is None or not re.fullmatch(
        r'(?:servings?|packages?|containers?|cups?|pieces?|slices?|bars?|bottles?|tablespoons?|teaspoons?)',
        unit, re.IGNORECASE,
    ):
        return None
    return {
        "kind": "portion",
        "value": amount,
        "unit": unit.casefold(),
        "description": description,
    }


def _description_nutrient_contract(label: str) -> tuple[str, str]:
    if label == "calories":
        return "calories_kcal", "kcal"
    if label == "protein":
        return "protein_g", "g"
    if label == "fat":
        return "fat_g", "g"
    return "carbohydrate_g", "g"


def _number_with_unit(value: str, expected_unit: str) -> int | float | None:
    match = re.fullmatch(
        r"(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?P<unit>[A-Za-z]+)",
        value.strip(),
    )
    if not match or match.group("unit").casefold() != expected_unit:
        return None
    return _nonnegative_number(match.group("number"))


def _structured_macros(source: Mapping[str, Any]) -> dict[str, int | float | None]:
    return {
        "calories_kcal": _nonnegative_number(source.get("calories")),
        "protein_g": _nonnegative_number(source.get("protein")),
        "fat_g": _nonnegative_number(source.get("fat")),
        "carbohydrate_g": _nonnegative_number(source.get("carbohydrate")),
    }


def _features(food_name: Any, description_feature: str | None) -> list[str]:
    name = _clean_text(food_name)
    values: list[str] = []
    if name:
        values.extend(_clean_text(match) for match in _PARENTHETICAL_RE.findall(name))
        values.extend(
            _clean_text(_PARENTHETICAL_RE.sub("", part))
            for part in name.split(",")[1:]
        )
    if description_feature:
        values.append(description_feature)

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        folded = value.casefold()
        if folded not in seen:
            seen.add(folded)
            result.append(value)
    return result


def _description_feature(description: str, basis_match: re.Match[str] | None) -> str | None:
    if basis_match is None or basis_match.start() == 0:
        return None
    prefix = description[:basis_match.start()].strip(" \t|;:-")
    if not prefix or len(prefix) > 200 or not any(character.isalpha() for character in prefix):
        return None
    lowered = prefix.casefold()
    if "http://" in lowered or "https://" in lowered:
        return None
    if any(label in lowered for label in ("calories:", "protein:", "fat:", "carbs:")):
        return None
    return _clean_text(prefix)


def _serving_id_status(value: Any) -> tuple[str | None, bool, str | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, False, "missing_serving_id"
    normalized = _nonnegative_id(value)
    if normalized is None:
        return None, False, "invalid_serving_id"
    if normalized == "0":
        return normalized, False, "derived_serving"
    return normalized, True, None


def _metric_unit(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    normalized = re.sub(r"\s+", " ", text.casefold())
    return normalized if normalized in {"g", "ml", "oz"} else None


def _nonnegative_number(value: Any, *, allow_zero: bool = True) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not _DECIMAL_RE.fullmatch(value):
            return None
    elif not isinstance(value, (int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        return None
    try:
        finite_float = float(number)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(finite_float) or (number != 0 and finite_float == 0):
        return None
    return int(number) if number == number.to_integral_value() else float(number)


def _positive_id(value: Any) -> str | None:
    normalized = _nonnegative_id(value)
    return normalized if normalized is not None and normalized != "0" else None


def _nonnegative_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value >= 0 else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value.isascii() or not value.isdigit():
        return None
    return str(int(value))


def _dict_items(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _validated_refs(
    refs: Sequence[str],
    expected_count: int,
    pattern: re.Pattern[str],
    label: str,
) -> list[str]:
    if isinstance(refs, (str, bytes)):
        raise TypeError(f"{label}_refs must be a sequence of references")
    result = [_validated_ref(ref, pattern, label) for ref in refs]
    if len(result) != expected_count:
        raise ValueError(f"expected {expected_count} {label} references, got {len(result)}")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} references must be unique")
    return result


def _validated_ref(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid local {label} reference")
    return value


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    if re.search(r'(?:\w+://|www\.|oauth|(?:food|serving)_id|(?:access|api)[_ -]?(?:token|key))',
                 value, re.IGNORECASE):
        return None
    return value or None


def _without_identifiers(value, identifiers):
    """Also discard identifiers accidentally embedded in provider text fields."""
    if isinstance(value, dict):
        return {key: item if key.endswith('_ref') else _without_identifiers(item, identifiers)
                for key, item in value.items()}
    if isinstance(value, list):
        return [clean for item in value if (clean := _without_identifiers(item, identifiers)) is not None]
    if isinstance(value, str) and any(
        identifier not in (None, '0') and re.search(r'(?<!\d)' + re.escape(identifier) + r'(?!\d)', value)
        for identifier in identifiers
    ):
        return None
    return value
