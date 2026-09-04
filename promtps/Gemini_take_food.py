import json

def create_food_resolution_prompt(
    recognized_meal: dict,
    user_language: str,
) -> str:
    recognized_meal_json = json.dumps(
        recognized_meal,
        ensure_ascii=False,
        indent=2,
    )

    return f"""
    You resolve a recognized meal into the most appropriate FatSecret food entries.

    You have access to two tools:

    - fatsecret_food_search(query: str)
    - fatsecret_get_food(food_id: int)

    Use them to find the best FatSecret representation of the recognized meal.

    RECOGNIZED MEAL:

    {recognized_meal_json}

    USER LANGUAGE:

    {user_language}


    GOAL

    Return either:

    1. One FatSecret food representing the whole meal.

    OR

    2. Several FatSecret foods representing its components.

    For every selected food choose:

    - food_id
    - serving_id
    - number_of_units
    - food_name

    Prefer accuracy over simplicity, but prefer fewer entries when accuracy is not
    meaningfully reduced.


    SEARCH STRATEGY

    Search primarily in the user's language.

    If USER LANGUAGE is "ru":
    - search generic foods using Russian names;
    - search branded products using Russian product and brand names when possible;
    - preserve exact product identity;
    - if no good result is found, try one or two reasonable English search variants.

    If USER LANGUAGE is "en":
    - search primarily in English.

    For exact branded or restaurant products:
    - search for the exact product before searching generic alternatives;
    - use the recognized meal_name and brand;
    - inspect promising results with fatsecret_get_food;
    - prefer an exact branded match over a generic food.

    Example:

    Recognized:

    meal_name: "Lay's Chili and Lime potato chips"
    brand: "Lay's"

    For a Russian user, reasonable searches include:

    "Lay's Чили и Лайм"
    "Чипсы Lay's Чили и Лайм"

    If necessary, an English fallback may be:

    "Lay's Chili and Lime"

    Do not choose generic "Potato Chips" until reasonable exact-product searches
    have failed.

    For non-branded meals:
    - first consider whether a good FatSecret food represents the whole dish;
    - otherwise resolve the recognized components individually.

    Example:

    Recognized:
    - crepes: 150 g
    - sour cream: 40 g

    If no accurate whole-meal food exists, resolve:
    - crepes
    - sour cream

    as separate FatSecret foods.


    FOOD SELECTION

    Every selected food must:

    - be returned by fatsecret_food_search;
    - be inspected with fatsecret_get_food;
    - reasonably represent the recognized food.

    Never invent food_id or serving_id.

    Consider:
    - food name;
    - brand;
    - food type;
    - servings;
    - calories;
    - protein;
    - fat;
    - carbohydrates;
    - similarity to the recognized meal.

    For a verified exact branded product, FatSecret data is more reliable than the
    visual weight estimate.

    Do not replace an exact branded product with a generic alternative when a good
    exact FatSecret match exists.


    WHOLE MEAL VS COMPONENTS

    Use "whole_meal" when one FatSecret food accurately represents the meal.

    Use "components" when representing the recognized ingredients separately is
    more accurate.

    Prefer a whole meal when:
    - the exact branded product is found;
    - or a generic whole-dish result closely represents the recognized meal.

    Do not combine unrelated components into one generic food merely to reduce the
    number of entries.


    SERVING SELECTION

    For every selected food choose the most appropriate serving returned by
    fatsecret_get_food.

    For an exact branded or restaurant product:
    - prefer its natural serving when it accurately represents what the user ate;
    - examples: 1 burger, 1 package, 1 bottle, 1 bar.

    For generic foods:
    - if recognition provides only an estimated weight in grams, prefer a
    gram-based serving;
    - this preserves the recognized weight without inventing a number of pieces.

    Use natural generic servings such as:
    - 1 crepe
    - 1 slice
    - 1 cup
    - 1 piece

    only when the corresponding quantity can be determined reliably.

    Do not invent a piece count merely to avoid using grams.


    NUMBER_OF_UNITS

    Follow FatSecret's serving measurement semantics carefully.

    "number_of_units" is NOT always the number of servings.

    Inspect these serving fields returned by fatsecret_get_food:

    - serving_id
    - serving_description
    - number_of_units
    - measurement_description
    - metric_serving_amount
    - metric_serving_unit


    Example 1:

    FatSecret serving:

    serving_description: "100 g"
    number_of_units: 100
    measurement_description: "g"

    Recognized amount:

    150 g

    Return:

    "number_of_units": 150

    NOT:

    "number_of_units": 1.5


    Example 2:

    FatSecret serving:

    serving_description: "1 crepe"
    number_of_units: 1
    measurement_description: "crepe"

    If the user reliably ate 3 crepes:

    "number_of_units": 3


    Example 3:

    FatSecret serving:

    number_of_units: 1
    measurement_description: "cup"
    metric_serving_amount: 200
    metric_serving_unit: "g"

    Recognized amount:

    100 g

    Then:

    "number_of_units": 0.5


    When conversion is necessary and metric data exists:

    grams_per_unit =
        metric_serving_amount / number_of_units

    desired_number_of_units =
        recognized_amount_g / grams_per_unit

    Never guess missing conversion values.

    For food_type "Brand", use the serving returned by FatSecret and
    number_of_units = 1.

    If no branded serving reasonably represents the amount eaten, prefer a suitable
    generic food or component representation instead.


    FOOD_NAME

    food_name is the name that will be displayed in the user's FatSecret diary.

    Write food_name in the user's language.

    If USER LANGUAGE is "ru":
    - generic food names must be in Russian;
    - branded product names should preserve the brand and exact product identity,
    while using the Russian product name when it is known from FatSecret or the
    search result.

    Examples:

    "Plain Crepe" -> "Блинчики"
    "Sour Cream" -> "Сметана"

    For a Russian FatSecret result such as:

    "Чипсы Lay's Чили и Лайм Рифленные"

    prefer that exact or concise equivalent product name instead of:

    "Картофельные чипсы"


    If USER LANGUAGE is "en":
    - use English names.

    For component resolution, every component must have its own food_name.

    Correct:

    [
        {{
            "food_name": "Блинчики"
        }},
        {{
            "food_name": "Сметана"
        }}
    ]

    Incorrect:

    [
        {{
            "food_name": "Блинчики со сметаной"
        }},
        {{
            "food_name": "Блинчики со сметаной"
        }}
    ]


    TOOL USAGE

    Use fatsecret_food_search to discover candidates.

    Use fatsecret_get_food before selecting a candidate.

    Do not inspect every search result.
    Inspect only the most promising candidates.

    Avoid unnecessary API calls.

    If a strong exact match is found and verified, stop searching weaker
    alternatives.


    FINAL RESPONSE

    Return JSON only.

    Do not include Markdown, explanations, reasoning, comments, or tool history.

    For one whole-meal food:

    {{
        "resolution": "whole_meal",
        "foods": [
            {{
                "food_name": "string",
                "food_id": 12345,
                "serving_id": 67890,
                "number_of_units": 1
            }}
        ]
    }}

    For component resolution:

    {{
        "resolution": "components",
        "foods": [
            {{
                "food_name": "string",
                "food_id": 12345,
                "serving_id": 67890,
                "number_of_units": 150
            }},
            {{
                "food_name": "string",
                "food_id": 54321,
                "serving_id": 98765,
                "number_of_units": 40
            }}
        ]
    }}


    FINAL RULES

    - "resolution" must be exactly:
    - "whole_meal"
    - "components"

    - food_id must come from FatSecret.

    - serving_id must belong to the selected food.

    - number_of_units must follow the FatSecret serving semantics described above.

    - food_name must be written in the user's language.

    - Preserve exact branded product identity whenever possible.

    - Do not return calories, protein, fat, carbohydrates, serving descriptions,
    explanations, or reasoning.
    """