from google import genai

import os
from dotenv import load_dotenv

import base64

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def recognize_image(image_bytes: bytes, description: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")

    interaction = client.interactions.create(
        model="gemini-3.1-flash-lite",
        input=[
            {
                "type": "image",
                "data": encoded,
                "mime_type": "image/jpeg",
            },
            {
                "type": "text",
                "text": (
                    f"Recognize the meal in the image. "
                    f"User description: {description}. "
                    "Briefly list the visible food items and estimate their amounts in grams."
                )
            },
        ],
    )

    return interaction.output_text
