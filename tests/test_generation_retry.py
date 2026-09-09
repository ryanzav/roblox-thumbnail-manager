import pytest

from src import image_generator as ig
from src.config import DEFAULTS, Config


def make_cfg(**over):
    cfg = Config(**DEFAULTS)
    cfg.ai_image_api_key = "test-key"
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(ig.time, "sleep", lambda s: None)
    monkeypatch.setattr(ig, "append_usage", lambda row: None)


def attempts_then(results):
    """Build a _generate_gemini stub replaying the given outcomes."""
    calls = {"n": 0}

    def fake(cfg, prompt):
        calls["n"] += 1
        outcome = results[min(calls["n"] - 1, len(results) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, "gemini-3-pro-image", {"total_tokens": 42}

    return fake, calls


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
EMPTY = ig.EmptyGenerationError("gemini-3-pro-image returned no image data")


def test_retries_after_an_empty_response(monkeypatch, tmp_path):
    monkeypatch.setattr(ig.queue_mod, "QUEUE_DIR", tmp_path)
    fake, calls = attempts_then([EMPTY, PNG])
    monkeypatch.setattr(ig, "_generate_gemini", fake)

    name = ig.generate_candidate(make_cfg(), "prompt", "candidate-001", "d", "thumb-001")
    assert name == "candidate-001.png"
    assert calls["n"] == 2
    assert (tmp_path / "candidate-001.png").exists()


def test_gives_up_after_the_configured_attempts(monkeypatch, tmp_path):
    monkeypatch.setattr(ig.queue_mod, "QUEUE_DIR", tmp_path)
    fake, calls = attempts_then([EMPTY])
    monkeypatch.setattr(ig, "_generate_gemini", fake)

    with pytest.raises(ig.GenerationError, match="after 3 attempts"):
        ig.generate_candidate(make_cfg(generation_retries=3), "p", "c", "d", "s")
    assert calls["n"] == 3


def test_permanent_errors_are_not_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(ig.queue_mod, "QUEUE_DIR", tmp_path)
    fake, calls = attempts_then([ig.GenerationError("AI_IMAGE_API_KEY is not set")])
    monkeypatch.setattr(ig, "_generate_gemini", fake)

    with pytest.raises(ig.GenerationError, match="not set"):
        ig.generate_candidate(make_cfg(), "p", "c", "d", "s")
    assert calls["n"] == 1


def test_succeeds_first_try_without_retrying(monkeypatch, tmp_path):
    monkeypatch.setattr(ig.queue_mod, "QUEUE_DIR", tmp_path)
    fake, calls = attempts_then([PNG])
    monkeypatch.setattr(ig, "_generate_gemini", fake)

    ig.generate_candidate(make_cfg(), "p", "candidate-002", "d", "s")
    assert calls["n"] == 1
