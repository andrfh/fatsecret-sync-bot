import os
import unittest
from types import SimpleNamespace

from google.genai.errors import ServerError

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import clients.gemini_client as gemini_client
from models.Meal import MealItem, MealRecognition, MealStatus, MealKind


class FakeResponse:
    def __init__(self, parsed):
        self.parsed = parsed
        self.text = ""


class GeminiRetryTests(unittest.TestCase):
    def test_generate_meal_recognition_retries_transient_server_errors(self):
        calls = {"count": 0}
        expected = MealRecognition(
            status=MealStatus.ok,
            meal_kind=MealKind.single_item,
            meal_name="Apple",
            brand=None,
            items=[MealItem(name="Apple", amount_g=180)],
        )

        def fake_generate_content(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                error = ServerError(503, {"error": {"message": "high demand"}})
                error.code = 503
                raise error
            return FakeResponse(expected)

        original_client = gemini_client.client
        gemini_client.client = SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate_content))
        try:
            result = gemini_client._generate_meal_recognition("prompt", b"img")
            self.assertIs(result, expected)
            self.assertEqual(calls["count"], 2)
        finally:
            gemini_client.client = original_client


if __name__ == "__main__":
    unittest.main()
