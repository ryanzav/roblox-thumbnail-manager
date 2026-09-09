"""Abstraction over the AI image-generation provider.

The default provider is Google's Gemini API. Google renames and retires image
models often, so the configured model is treated as a preference: if it is not
available to this key, the generator discovers a usable image model from the
API instead of failing the run.

Adding a provider means adding one _generate_<name> function and a config
entry — nothing else in the project should know provider details.
"""

import logging
from datetime import datetime, timezone

import requests

from .config import Config
from . import queue as queue_mod

log = logging.getLogger(__name__)

MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Preference order when the configured model is unavailable. Imagen models use
# the predict/generate_images path; Gemini "image" models return inline image
# parts from generate_content.
_PREFERRED_HINTS = ("imagen", "image")


class GenerationError(Exception):
    pass


def generate_candidate(cfg: Config, prompt: str, filename: str,
                       description: str, source_thumbnail_id: str) -> str:
    """Generate one 16:9 candidate, save it into the queue, return filename."""
    if cfg.image_provider == "gemini":
        image_bytes, model_used = _generate_gemini(cfg, prompt)
    else:
        raise GenerationError(f"Unknown image provider: {cfg.image_provider}")

    metadata = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt": prompt,
        "description": description,
        "source_thumbnail_id": source_thumbnail_id,
        "provider": cfg.image_provider,
        "model": model_used,
        "filename": filename,
        "status": "queued",
    }
    queue_mod.write_candidate(image_bytes, filename, metadata)
    return filename


def list_image_models(api_key: str) -> list[dict]:
    """Return every model this key may use, as {name, kind}.

    kind is "imagen" for the predict/generate_images path and "gemini" for
    models that return inline image parts from generate_content.
    """
    try:
        resp = requests.get(MODELS_URL, params={"key": api_key, "pageSize": 200}, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GenerationError(f"Could not list models: {type(exc).__name__}") from exc

    models = []
    for m in resp.json().get("models", []):
        name = m.get("name", "").removeprefix("models/")
        methods = m.get("supportedGenerationMethods", [])
        if "predict" in methods and "imagen" in name.lower():
            models.append({"name": name, "kind": "imagen"})
        elif "generateContent" in methods:
            models.append({"name": name, "kind": "gemini"})
    return models


def _resolve_model(cfg: Config) -> dict:
    available = list_image_models(cfg.ai_image_api_key)
    if not available:
        raise GenerationError("This API key has no usable models available")

    # An explicitly configured model wins whenever the key can use it at all.
    # Model names do not reliably advertise image support, so the config is
    # treated as authoritative rather than second-guessed by a name heuristic.
    for m in available:
        if m["name"] == cfg.image_model:
            return m

    # Otherwise fall back to models whose names do advertise image generation.
    for hint in _PREFERRED_HINTS:
        matches = sorted((m for m in available if hint in m["name"].lower()),
                         key=lambda m: m["name"])
        if matches:
            chosen = matches[-1]
            log.warning("Configured image model %r unavailable; using %r",
                        cfg.image_model, chosen["name"])
            return chosen
    raise GenerationError(
        f"Configured image model {cfg.image_model!r} is unavailable and no "
        f"image-capable model was found")


def _generate_gemini(cfg: Config, prompt: str) -> tuple[bytes, str]:
    if not cfg.ai_image_api_key:
        raise GenerationError("AI_IMAGE_API_KEY is not set")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise GenerationError("google-genai is not installed") from exc

    model = _resolve_model(cfg)
    client = genai.Client(api_key=cfg.ai_image_api_key)

    try:
        if model["kind"] == "imagen":
            response = client.models.generate_images(
                model=model["name"],
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="16:9"),
            )
            images = response.generated_images or []
            if not images:
                raise GenerationError("Model returned no images (possibly filtered)")
            return images[0].image.image_bytes, model["name"]

        contents = prompt + "\n\nProduce a 16:9 landscape image."
        try:
            response = client.models.generate_content(
                model=model["name"], contents=contents,
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
        except Exception:
            # Some models reject an image-only modality list or the field
            # entirely; retry with the model's default response shape.
            response = client.models.generate_content(
                model=model["name"], contents=contents)

        for candidate in response.candidates or []:
            for part in (candidate.content.parts or []):
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    return inline.data, model["name"]
        raise GenerationError(
            f"{model['name']} returned no image data — it may not support "
            f"image generation")
    except GenerationError:
        raise
    except Exception as exc:
        raise GenerationError(
            f"Generation failed on {model['name']}: {type(exc).__name__}: {exc}") from exc
