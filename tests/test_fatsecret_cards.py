"""Offline tests for pure FatSecret response card conversion."""

import copy
import json
import unittest

from services.fatsecret_cards import convert_food_details, convert_food_search


def search_food(**overrides):
    value = {
        "food_id": "910001",
        "food_name": "Synthetic Yogurt, Unsweetened (Vanilla)",
        "brand_name": "Example Brand",
        "food_type": "Brand",
        "food_url": "https://provider.invalid/food/910001",
        "food_description": (
            "Per 100 g - Calories: 62kcal | Fat: 1.50g | "
            "Carbs: 4.00g | Protein: 10.00g"
        ),
        "unknown_provider_field": "must not leave the converter",
    }
    value.update(overrides)
    return value


def serving(**overrides):
    value = {
        "serving_id": "920001",
        "serving_description": "1 synthetic container",
        "serving_url": "https://provider.invalid/serving/920001",
        "number_of_units": "1.000",
        "measurement_description": "container",
        "metric_serving_amount": "170.000",
        "metric_serving_unit": "g",
        "calories": "105",
        "protein": "17.00",
        "fat": "2.50",
        "carbohydrate": "6.80",
        "sodium": "40",
    }
    value.update(overrides)
    return value


def details_response(servings, **food_overrides):
    food = {
        "food_id": "910001",
        "food_name": "Synthetic Yogurt, Unsweetened (Vanilla)",
        "brand_name": "Example Brand",
        "food_type": "Brand",
        "food_url": "https://provider.invalid/food/910001",
        "unknown_provider_field": "must not leave the converter",
    }
    food.update(food_overrides)
    if servings is not None:
        food["servings"] = {"serving": servings}
    return {"food": food}


class SearchCardTests(unittest.TestCase):
    def test_one_product_array_and_empty_search(self):
        single = convert_food_search({"foods": {"food": search_food()}}, ["C1"])
        self.assertEqual(len(single.public_cards), 1)
        self.assertEqual(single.food_ids_by_candidate_ref, {"C1": "910001"})

        many = convert_food_search(
            {"foods": {"food": [search_food(), search_food(food_id="910002", food_name="Other")]}},
            ["C1", "C2"],
        )
        self.assertEqual([card["candidate_ref"] for card in many.public_cards], ["C1", "C2"])
        self.assertEqual(many.food_ids_by_candidate_ref["C2"], "910002")

        empty = convert_food_search({"foods": {"total_results": "0"}}, [])
        self.assertEqual(empty.public_cards, [])
        self.assertEqual(empty.food_ids_by_candidate_ref, {})

    def test_malformed_food_id_is_not_exposed_as_candidate(self):
        result = convert_food_search(
            {"foods": {"food": [search_food(food_id=None), search_food(food_id="-7")]}},
            ["C1", "C2"],
        )
        self.assertEqual(result.public_cards, [])
        self.assertEqual(result.food_ids_by_candidate_ref, {})

    def test_complete_partial_unparsed_and_missing_descriptions(self):
        descriptions = [
            search_food(),
            search_food(
                food_id="910002",
                food_description=(
                    "Per 1 package - Calories: 250kcal | Fat: NaNg | Carbs: 30g"
                ),
            ),
            search_food(food_id="910003", food_description="Nutrition facts unavailable"),
            search_food(food_id="910004", food_description=None),
        ]
        cards = convert_food_search(
            {"foods": {"food": descriptions}}, ["C1", "C2", "C3", "C4"]
        ).public_cards

        self.assertEqual([card["nutrition"]["status"] for card in cards],
                         ["complete", "partial", "unparsed", "missing"])
        partial = cards[1]["nutrition"]
        self.assertEqual(partial["calories_kcal"], 250)
        self.assertEqual(partial["carbohydrate_g"], 30)
        self.assertIsNone(partial["fat_g"])
        self.assertIsNone(partial["protein_g"])
        for key in ("calories_kcal", "protein_g", "fat_g", "carbohydrate_g"):
            self.assertIsNone(cards[2]["nutrition"][key])
            self.assertIsNone(cards[3]["nutrition"][key])

    def test_zero_is_data_but_missing_and_invalid_numbers_are_null(self):
        foods = [
            search_food(
                food_description=(
                    "Per 100 ml - Calories: 0kcal | Fat: 0g | Carbs: 0g | Protein: 0g"
                )
            ),
            search_food(
                food_id="910002",
                food_description=(
                    "Per 1 serving - Calories: Infinitykcal | Fat: -1g | "
                    "Carbs: 2g | Protein: NaNg"
                ),
            ),
        ]
        cards = convert_food_search({"foods": {"food": foods}}, ["C1", "C2"]).public_cards
        zero = cards[0]["nutrition"]
        self.assertEqual(zero["status"], "complete")
        self.assertEqual(
            [zero[key] for key in ("calories_kcal", "protein_g", "fat_g", "carbohydrate_g")],
            [0, 0, 0, 0],
        )
        invalid = cards[1]["nutrition"]
        self.assertEqual(invalid["status"], "partial")
        self.assertEqual(invalid["carbohydrate_g"], 2)
        self.assertIsNone(invalid["calories_kcal"])
        self.assertIsNone(invalid["protein_g"])
        self.assertIsNone(invalid["fat_g"])

    def test_mass_volume_package_and_unknown_basis_are_distinct(self):
        foods = []
        for index, basis in enumerate(("100g", "100 ml", "1 package", "a package"), start=1):
            foods.append(search_food(
                food_id=str(910000 + index),
                food_description=(
                    f"Per {basis} - Calories: 10kcal | Fat: 1g | Carbs: 1g | Protein: 1g"
                ),
            ))
        cards = convert_food_search(
            {"foods": {"food": foods}}, ["C1", "C2", "C3", "C4"]
        ).public_cards

        self.assertEqual(cards[0]["nutrition"]["basis"]["kind"], "mass")
        self.assertEqual(cards[0]["nutrition"]["basis"]["unit"], "g")
        self.assertEqual(cards[1]["nutrition"]["basis"]["kind"], "volume")
        self.assertEqual(cards[1]["nutrition"]["basis"]["unit"], "ml")
        self.assertEqual(cards[2]["nutrition"]["basis"], {
            "kind": "portion", "value": 1, "unit": "package", "description": "1 package"})
        self.assertIsNone(cards[3]["nutrition"]["basis"])
        self.assertEqual(cards[3]["nutrition"]["status"], "partial")

    def test_only_conservative_non_nutrition_features_are_kept(self):
        food = search_food(
            food_description=(
                "Lactose free | Per 100 g - Calories: 62kcal | Fat: 1.5g | "
                "Carbs: 4g | Protein: 10g"
            )
        )
        card = convert_food_search({"foods": {"food": food}}, ["C1"]).public_cards[0]
        self.assertEqual(card["features"], ["Vanilla", "Unsweetened", "Lactose free"])
        self.assertNotIn("Calories", json.dumps(card))


class ServingCardTests(unittest.TestCase):
    def test_one_array_missing_and_absent_servings(self):
        one = convert_food_details(details_response(serving()), "C1", ["S1"])
        self.assertEqual(len(one.public_card["servings"]), 1)
        self.assertEqual(one.serving_ids_by_ref, {"S1": "920001"})

        many = convert_food_details(
            details_response([serving(), serving(serving_id="920002")]),
            "C1", ["S1", "S2"],
        )
        self.assertEqual(len(many.public_card["servings"]), 2)

        no_servings = convert_food_details(details_response(None), "C1", [])
        self.assertEqual(no_servings.public_card["servings"], [])
        self.assertEqual(no_servings.serving_ids_by_ref, {})

        absent_food = convert_food_details({}, "C1", [])
        self.assertIsNone(absent_food.public_card)
        self.assertIsNone(absent_food.food_id)

    def test_serving_id_zero_missing_invalid_and_positive(self):
        values = [
            serving(serving_id="0"),
            serving(serving_id=None),
            serving(serving_id="not-an-id"),
            serving(serving_id="920004"),
        ]
        result = convert_food_details(details_response(values), "C1", ["S1", "S2", "S3", "S4"])
        cards = result.public_card["servings"]
        self.assertEqual(result.serving_ids_by_ref,
                         {"S1": "0", "S2": None, "S3": None, "S4": "920004"})
        self.assertEqual(
            [(item["diary_eligible"], item["diary_ineligible_reason"]) for item in cards],
            [
                (False, "derived_serving"),
                (False, "missing_serving_id"),
                (False, "invalid_serving_id"),
                (True, None),
            ],
        )

    def test_serving_nutrition_numbers_and_explicit_basis(self):
        result = convert_food_details(details_response(serving()), "C1", ["S1"])
        card = result.public_card["servings"][0]
        self.assertEqual(card["description"], "1 synthetic container")
        self.assertEqual(card["standard_quantity"], {"value": 1, "unit": "container"})
        self.assertEqual(card["metric_quantity"], {"value": 170, "unit": "g"})
        self.assertEqual(card["nutrition"]["basis"], "this_standard_serving")
        self.assertEqual(card["nutrition"]["status"], "complete")

    def test_partial_missing_zero_nan_infinity_negative_and_bad_metric(self):
        values = [
            serving(calories="0", protein=None, fat="NaN", carbohydrate="-2"),
            serving(
                serving_id="920002", serving_description=None, number_of_units="Infinity",
                measurement_description=None, metric_serving_amount="-100",
                metric_serving_unit="g", calories=None, protein=None, fat=None,
                carbohydrate=None,
            ),
        ]
        cards = convert_food_details(details_response(values), "C1", ["S1", "S2"]).public_card["servings"]
        self.assertEqual(cards[0]["nutrition"]["calories_kcal"], 0)
        self.assertEqual(cards[0]["nutrition"]["status"], "partial")
        self.assertIsNone(cards[0]["nutrition"]["protein_g"])
        self.assertIsNone(cards[0]["nutrition"]["fat_g"])
        self.assertIsNone(cards[0]["nutrition"]["carbohydrate_g"])
        self.assertEqual(cards[1]["standard_quantity"], {"value": None, "unit": None})
        self.assertIsNone(cards[1]["metric_quantity"])
        self.assertEqual(cards[1]["nutrition"]["status"], "missing")

    def test_millilitres_are_not_converted_to_grams(self):
        card = convert_food_details(
            details_response(serving(metric_serving_amount="250", metric_serving_unit="ml")),
            "C1", ["S1"],
        ).public_card["servings"][0]
        self.assertEqual(card["metric_quantity"], {"value": 250, "unit": "ml"})
        self.assertNotIn("g", card["metric_quantity"].values())


class IsolationTests(unittest.TestCase):
    def test_public_serialization_contains_no_provider_ids_urls_or_extra_fields(self):
        search = convert_food_search({"foods": {"food": search_food()}}, ["C1"])
        details = convert_food_details(details_response(serving()), "C1", ["S1"])
        serialized = json.dumps(
            {"search": search.public_cards, "details": details.public_card},
            ensure_ascii=False,
            sort_keys=True,
        )
        for forbidden in (
            "910001", "920001", "food_id", "serving_id", "food_url", "serving_url",
            "provider.invalid", "unknown_provider_field", "oauth",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(search.food_ids_by_candidate_ref, {"C1": "910001"})
        self.assertEqual(details.food_id, "910001")
        self.assertEqual(details.serving_ids_by_ref, {"S1": "920001"})

    def test_conversion_does_not_mutate_source_responses(self):
        search_response = {"foods": {"food": [search_food(), search_food(food_id="910002")]}}
        detail_response = details_response([serving(), serving(serving_id="920002")])
        search_before = copy.deepcopy(search_response)
        detail_before = copy.deepcopy(detail_response)

        convert_food_search(search_response, ["C1", "C2"])
        convert_food_details(detail_response, "C1", ["S1", "S2"])

        self.assertEqual(search_response, search_before)
        self.assertEqual(detail_response, detail_before)

    def test_references_are_caller_owned_but_must_not_look_like_raw_ids(self):
        with self.assertRaises(ValueError):
            convert_food_search({"foods": {"food": search_food()}}, ["910001"])
        with self.assertRaises(ValueError):
            convert_food_details(details_response(serving()), "C1", ["920001"])
        with self.assertRaises(ValueError):
            convert_food_search(
                {"foods": {"food": [search_food(), search_food(food_id="910002")]}},
                ["C1", "C1"],
            )


if __name__ == "__main__":
    unittest.main()
