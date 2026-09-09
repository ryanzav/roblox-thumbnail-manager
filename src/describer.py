"""Generates thumbnail descriptions from images with Gemini vision.

Descriptions are the creative seed for new AI candidates, so they aim for
concrete visual detail rather than marketing copy.
"""

import logging

from .config import Config

log = logging.getLogger(__name__)

DESCRIBE_PROMPT = """Describe this Roblox game thumbnail in 1-3 sentences for use
as an image-generation seed. Concretely describe the main subject, art style,
composition, camera angle, colors, background, and any text or characters.
Do not mention that it is a thumbnail or an image; just describe the scene."""


class DescriptionError(Exception):
    pass


def describe_image(cfg: Config, image_path: str) -> str:
    if not cfg.ai_image_api_key:
        raise DescriptionError("AI_IMAGE_API_KEY is not set")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise DescriptionError("google-genai is not installed") from exc

    with open(image_path, "rb") as fh:
        data = fh.read()
    try:
        client = genai.Client(api_key=cfg.ai_image_api_key)
        response = client.models.generate_content(
            model=cfg.description_model,
            contents=[
                types.Part.from_bytes(data=data, mime_type="image/png"),
                DESCRIBE_PROMPT,
            ],
        )
        text = (response.text or "").strip()
    except Exception as exc:
        raise DescriptionError(f"Description failed: {type(exc).__name__}: {exc}") from exc
    if not text:
        raise DescriptionError("Gemini returned an empty description")
    return " ".join(text.split())
