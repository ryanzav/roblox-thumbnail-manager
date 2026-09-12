import json

import pytest

from src import notify
from src.config import DEFAULTS, Config

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32


def make_cfg(**over):
    cfg = Config(**DEFAULTS)
    cfg.notify_email = "someone@example.com"
    cfg.smtp_user = "sender@example.com"
    cfg.smtp_password = "secret"
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


class FakeSMTP:
    """Captures the sent message instead of talking to a mail server."""

    sent = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def candidate(tmp_path, name, data=PNG, **meta):
    image = tmp_path / name
    image.write_bytes(data)
    image.with_suffix(".json").write_text(json.dumps({
        "generated_at": "2026-09-12T01:00:00Z", "model": "gemini-3-pro-image",
        "source_thumbnail_id": "thumb-001", "prompt": "a prompt", **meta,
    }))
    return image


def attachments(msg):
    return [p.get_filename() for p in msg.iter_attachments()]


def body(msg):
    return msg.get_body(preferencelist=("plain",)).get_content()


def test_several_candidates_arrive_as_one_email(tmp_path):
    paths = [candidate(tmp_path, f"candidate-{i:03d}.png") for i in (1, 2, 3)]
    assert notify.notify_new_images(make_cfg(), paths) is True

    assert len(FakeSMTP.sent) == 1, "one run must produce one email"
    msg = FakeSMTP.sent[0]
    assert msg["Subject"] == "3 new thumbnail candidates"
    assert attachments(msg) == ["candidate-001.png", "candidate-002.png",
                                "candidate-003.png"]
    text = body(msg)
    for name in ("candidate-001.png", "candidate-002.png", "candidate-003.png"):
        assert name in text
    assert "1 of 3" in text and "3 of 3" in text


def test_a_single_candidate_still_names_itself_in_the_subject(tmp_path):
    path = candidate(tmp_path, "candidate-007.png")
    assert notify.notify_new_images(make_cfg(), [path]) is True
    msg = FakeSMTP.sent[0]
    assert msg["Subject"] == "New thumbnail candidate: candidate-007.png"
    assert attachments(msg) == ["candidate-007.png"]
    # No "1 of 1" scaffolding when there is nothing to enumerate.
    assert " of 1 " not in body(msg)


def test_attachment_type_follows_the_actual_image_bytes(tmp_path):
    paths = [candidate(tmp_path, "a.png", PNG), candidate(tmp_path, "b.jpg", JPEG)]
    notify.notify_new_images(make_cfg(), paths)
    types = [p.get_content_type() for p in FakeSMTP.sent[0].iter_attachments()]
    assert types == ["image/png", "image/jpeg"]


def test_nothing_generated_sends_nothing(tmp_path):
    assert notify.notify_new_images(make_cfg(), []) is False
    assert FakeSMTP.sent == []


def test_missing_files_are_skipped(tmp_path):
    real = candidate(tmp_path, "real.png")
    assert notify.notify_new_images(make_cfg(), [real, tmp_path / "gone.png"]) is True
    assert attachments(FakeSMTP.sent[0]) == ["real.png"]


def test_without_smtp_credentials_it_skips_quietly(tmp_path):
    path = candidate(tmp_path, "candidate-001.png")
    assert notify.notify_new_images(make_cfg(smtp_password=""), [path]) is False
    assert FakeSMTP.sent == []


def test_a_send_failure_never_raises(tmp_path, monkeypatch):
    def explode(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(notify.smtplib, "SMTP", explode)
    path = candidate(tmp_path, "candidate-001.png")
    assert notify.notify_new_images(make_cfg(), [path]) is False


def test_corrupt_metadata_still_sends_the_image(tmp_path):
    image = tmp_path / "candidate-009.png"
    image.write_bytes(PNG)
    image.with_suffix(".json").write_text("{not json")
    assert notify.notify_new_images(make_cfg(), [image]) is True
    assert attachments(FakeSMTP.sent[0]) == ["candidate-009.png"]
