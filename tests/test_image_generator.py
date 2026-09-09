import pytest

from src import image_generator as ig
from src.config import DEFAULTS, Config


def make_cfg(**over):
    cfg = Config(**DEFAULTS)
    cfg.ai_image_api_key = "test-key"
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def test_prefers_configured_model(monkeypatch):
    monkeypatch.setattr(ig, "list_image_models", lambda key: [
        {"name": "imagen-9.0-generate-001", "kind": "imagen"},
        {"name": "imagen-4.0-generate-001", "kind": "imagen"},
    ])
    cfg = make_cfg(image_model="imagen-4.0-generate-001")
    assert ig._resolve_model(cfg)["name"] == "imagen-4.0-generate-001"


def test_falls_back_to_newest_imagen_when_configured_missing(monkeypatch):
    monkeypatch.setattr(ig, "list_image_models", lambda key: [
        {"name": "gemini-3-flash-image", "kind": "gemini"},
        {"name": "imagen-5.0-generate-001", "kind": "imagen"},
        {"name": "imagen-4.0-generate-001", "kind": "imagen"},
    ])
    cfg = make_cfg(image_model="imagen-retired")
    chosen = ig._resolve_model(cfg)
    assert chosen["name"] == "imagen-5.0-generate-001"
    assert chosen["kind"] == "imagen"


def test_falls_back_to_gemini_image_model(monkeypatch):
    monkeypatch.setattr(ig, "list_image_models", lambda key: [
        {"name": "gemini-3-flash-image", "kind": "gemini"},
    ])
    cfg = make_cfg(image_model="imagen-retired")
    assert ig._resolve_model(cfg)["kind"] == "gemini"


def test_configured_model_wins_even_without_image_in_its_name(monkeypatch):
    # gemini-3.8-flash does not advertise images in its name, but an explicit
    # config choice must still be honored rather than silently replaced.
    monkeypatch.setattr(ig, "list_image_models", lambda key: [
        {"name": "gemini-3.8-flash", "kind": "gemini"},
        {"name": "gemini-3-flash-image", "kind": "gemini"},
        {"name": "imagen-5.0-generate-001", "kind": "imagen"},
    ])
    cfg = make_cfg(image_model="gemini-3.8-flash")
    chosen = ig._resolve_model(cfg)
    assert chosen["name"] == "gemini-3.8-flash"
    assert chosen["kind"] == "gemini"


def test_no_models_at_all_raises(monkeypatch):
    monkeypatch.setattr(ig, "list_image_models", lambda key: [])
    with pytest.raises(ig.GenerationError, match="no usable models"):
        ig._resolve_model(make_cfg())


def test_unavailable_model_with_no_image_fallback_raises(monkeypatch):
    monkeypatch.setattr(ig, "list_image_models", lambda key: [
        {"name": "gemini-3.6-flash", "kind": "gemini"},
    ])
    cfg = make_cfg(image_model="gemini-3.8-flash")
    with pytest.raises(ig.GenerationError, match="unavailable"):
        ig._resolve_model(cfg)


def test_list_image_models_classifies_by_capability(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"models": [
                {"name": "models/imagen-4.0-generate-001",
                 "supportedGenerationMethods": ["predict"]},
                {"name": "models/gemini-3.8-flash",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004",
                 "supportedGenerationMethods": ["embedContent"]},
            ]}
    monkeypatch.setattr(ig.requests, "get", lambda *a, **k: FakeResp())
    models = {m["name"]: m["kind"] for m in ig.list_image_models("key")}
    assert models == {"imagen-4.0-generate-001": "imagen",
                      "gemini-3.8-flash": "gemini"}


def test_missing_api_key_raises():
    cfg = make_cfg()
    cfg.ai_image_api_key = ""
    with pytest.raises(ig.GenerationError, match="not set"):
        ig._generate_gemini(cfg, "prompt")
