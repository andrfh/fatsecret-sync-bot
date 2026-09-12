import json


def create_verify_prompt(recognition: dict) -> str:
    recognition_json = json.dumps(recognition, ensure_ascii=False, indent=2)

    return f"""
    You are reviewing a meal recognition that was produced from the SAME photo you
    are given now. Correct it against the photo.

    CURRENT RECOGNITION:
    {recognition_json}

    Check two things:

    1. OVER-DECOMPOSITION
    If the items are really parts of ONE dish that has an established name and a
    stable recipe, merge them into a single item named after that dish, summing
    their "amount_g". This applies whether the dish is cooked together or assembled
    to order:
    - handheld units: burger = bun + patty + cheese; sandwich = bread + filling;
      wrap; taco; hot dog; burrito; ice cream cone;
    - cooked dishes: plov / pilaf = rice + carrot + meat; risotto; paella; biryani;
      fried rice; lasagna; stew; curry; soup; shakshuka; carbonara; mac and cheese;
    - assembled named dishes: Caesar salad = lettuce + croutons + chicken +
      parmesan + dressing; Greek salad; Olivier salad; a sushi roll = rice + fish
      + nori + filling; a poke bowl.
    Keep items separate only when the meal is genuinely an assortment of separate
    foods with no common dish name (meat + rice + salad, eggs + toast + bacon). A
    platter of assorted sushi keeps one item per distinct roll or nigiri type, but
    no roll is split into its ingredients.

    2. NON-VISIBLE SEASONING
    Remove any item that is a seasoning or additive rather than a visible food:
    salt, pepper, sugar, cooking oil, olive oil, butter used for frying, spices,
    dried herbs, seasoning blends, or a sauce or dressing that is not visible as a
    distinct layer or pool in the image.

    RULES
    - Keep "status", "meal_name" and "brand" unchanged.
    - Update "meal_kind" only if a merge makes the previous value wrong
      (for example it becomes a "single_item" after merging).
    - Do not invent foods that are not already listed or clearly visible.
    - Keep at most 8 items.
    - If nothing needs changing, return the recognition unchanged.

    The response structure is enforced by a schema.
    """
