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


def test_no_image_models_raises(monkeypatch):
    monkeypatch.setattr(ig, "list_image_models", lambda key: [])
    with pytest.raises(ig.GenerationError, match="no image-capable models"):
        ig._resolve_model(make_cfg())


def test_list_image_models_filters_by_capability(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"models": [
                {"name": "models/imagen-4.0-generate-001",
                 "supportedGenerationMethods": ["predict"]},
                {"name": "models/gemini-3.6-flash",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3-flash-image",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004",
                 "supportedGenerationMethods": ["embedContent"]},
            ]}
    monkeypatch.setattr(ig.requests, "get", lambda *a, **k: FakeResp())
    models = ig.list_image_models("key")
    assert {m["name"] for m in models} == {"imagen-4.0-generate-001", "gemini-3-flash-image"}


def test_missing_api_key_raises():
    cfg = make_cfg()
    cfg.ai_image_api_key = ""
    with pytest.raises(ig.GenerationError, match="not set"):
        ig._generate_gemini(cfg, "prompt")
