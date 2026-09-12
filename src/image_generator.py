"""Abstraction over the AI image-generation provider.

The default provider is Google's Gemini API. Google renames and retires image
models often, so the configured model is treated as a preference: if it is not
available to this key, the generator discovers a usable image model from the
API instead of failing the run.

Adding a provider means adding one _generate_<name> function and a config
entry — nothing else in the project should know provider details.
"""

import logging
import time
from datetime import datetime, timezone

import requests

from .config import Config
from .imaging import detect_format
from . import queue as queue_mod

log = logging.getLogger(__name__)

MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Preference order when the configured model is unavailable. Imagen models use
# the predict/generate_images path; Gemini "image" models return inline image
# parts from generate_content.
_PREFERRED_HINTS = ("imagen", "image")


class GenerationError(Exception):
    pass


class EmptyGenerationError(GenerationError):
    """The model answered but produced no image.

    Distinct from a permanent failure (missing key, unusable model) because
    it is usually transient: a safety filter tripping on one phrasing, or
    momentary capacity pressure. Worth retrying; the rest is not.
    """


def generate_image(cfg: Config, prompt: str) -> tuple[bytes, str]:
    """Generate one 16:9 image and return (bytes, model used).

    Retries, provider dispatch and moderation live here rather than in
    generate_candidate() so the queue-free paths - local tooling, tests - run
    exactly the same pipeline as a scheduled run.
    """
    if cfg.image_provider != "gemini":
        raise GenerationError(f"Unknown image provider: {cfg.image_provider}")

    attempts = max(1, cfg.generation_retries)
    for attempt in range(1, attempts + 1):
        try:
            image_bytes, model_used = _generate_gemini(cfg, prompt)
            break
        except EmptyGenerationError as exc:
            if attempt == attempts:
                raise GenerationError(
                    f"{exc} (after {attempts} attempts)") from exc
            delay = 2 ** attempt
            log.warning("%s; retrying in %ds (attempt %d/%d)",
                        exc, delay, attempt + 1, attempts)
            time.sleep(delay)

    _moderate(cfg, image_bytes)
    return image_bytes, model_used


def _moderate(cfg: Config, image_bytes: bytes) -> None:
    """Reject an image Roblox would likely refuse.

    Fails open: if the check itself errors, the image proceeds, so a
    moderation outage cannot stall generation.
    """
    try:
        from .image_moderation import check_image_safety
        result = check_image_safety(cfg, image_bytes)
        if not result["safe"]:
            raise GenerationError(
                f"Generated image rejected by moderation: {result['reason']} "
                f"(categories: {', '.join(result['categories'])})")
    except GenerationError:
        raise
    except Exception as exc:
        log.warning("Moderation check failed (continuing): %s", exc)


def generate_candidate(cfg: Config, prompt: str, stem: str,
                       source_description: str, source_thumbnail_id: str) -> str:
    """Generate one candidate, save it into the queue, return its filename.

    The extension comes from the returned image data, not from the caller,
    because providers differ in the format they produce.
    """
    image_bytes, model_used = generate_image(cfg, prompt)
    filename = stem + detect_format(image_bytes)[0]

    metadata = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt": prompt,
        # The seed this image was bred FROM. The new image gets its own
        # description from Gemini vision once it is archived; copying this
        # one forward made whole lineages share a single ancestor's text.
        "source_description": source_description,
        "source_thumbnail_id": source_thumbnail_id,
        "provider": cfg.image_provider,
        "model": model_used,
        "filename": filename,
        "status": "queued",
    }
    queue_mod.write_candidate(image_bytes, filename, metadata, queue_mod.QUEUE_DIR)
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


def _image_capable_names(cfg: Config) -> str:
    """Names of models that advertise image generation, for error messages."""
    try:
        available = list_image_models(cfg.ai_image_api_key)
    except GenerationError:
        return ""
    names = sorted(m["name"] for m in available
                   if any(h in m["name"].lower() for h in _PREFERRED_HINTS))
    return ", ".join(names)


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
                raise EmptyGenerationError(
                    f"{model['name']} returned no images (possibly filtered)")
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
        raise EmptyGenerationError(
            f"{model['name']} returned no image data")
    except GenerationError:
        raise
    except Exception as exc:
        raise GenerationError(
            f"Generation failed on {model['name']}: {type(exc).__name__}: {exc}") from exc
