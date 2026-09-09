"""Abstraction over the AI image-generation provider.

The default provider is Google's Imagen via the Gemini API (google-genai).
Adding a provider means adding one _generate_<name> function and a config
entry — nothing else in the project should know provider details.
"""

import logging
from datetime import datetime, timezone

from .config import Config
from . import queue as queue_mod

log = logging.getLogger(__name__)


class GenerationError(Exception):
    pass


def generate_candidate(cfg: Config, prompt: str, filename: str,
                       description: str, source_thumbnail_id: str) -> str:
    """Generate one 16:9 candidate, save it into the queue, return filename."""
    if cfg.image_provider == "gemini":
        image_bytes = _generate_gemini(cfg, prompt)
    else:
        raise GenerationError(f"Unknown image provider: {cfg.image_provider}")

    metadata = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt": prompt,
        "description": description,
        "source_thumbnail_id": source_thumbnail_id,
        "provider": cfg.image_provider,
        "model": cfg.image_model,
        "filename": filename,
        "status": "queued",
    }
    queue_mod.write_candidate(image_bytes, filename, metadata)
    return filename


def _generate_gemini(cfg: Config, prompt: str) -> bytes:
    if not cfg.ai_image_api_key:
        raise GenerationError("AI_IMAGE_API_KEY is not set")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise GenerationError("google-genai is not installed") from exc

    try:
        client = genai.Client(api_key=cfg.ai_image_api_key)
        response = client.models.generate_images(
            model=cfg.image_model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
            ),
        )
        images = response.generated_images or []
        if not images:
            raise GenerationError("Gemini returned no images (possibly filtered)")
        return images[0].image.image_bytes
    except GenerationError:
        raise
    except Exception as exc:
        raise GenerationError(f"Gemini generation failed: {type(exc).__name__}: {exc}") from exc
