import json

from src import dashboard, queue as queue_mod


def test_queue_preview_publishes_metadata_without_copying_images(tmp_path, monkeypatch):
    qdir = tmp_path / "queue"
    qdir.mkdir()
    (qdir / "candidate-001.png").write_bytes(b"img-bytes")
    (qdir / "candidate-001.json").write_text(json.dumps({
        "generated_at": "2026-09-09T00:00:00Z", "prompt": "Create a variation...",
        "description": "A butterfly", "source_thumbnail_id": "thumb-001",
        "provider": "gemini", "model": "gemini-3-pro-image",
    }))
    monkeypatch.setattr(queue_mod, "QUEUE_DIR", qdir)

    docs_data, img_dir = tmp_path / "docs" / "data", tmp_path / "docs" / "images" / "queue"
    entries = dashboard.publish_queue_preview(docs_data, img_dir)

    # thumbnails/queue/ stays the only copy of a queued image.
    assert not img_dir.exists()
    published = json.loads((docs_data / "queue.json").read_text())
    assert published == entries
    assert published[0]["source_thumbnail_id"] == "thumb-001"
    assert "url" not in published[0]


def test_empty_queue_publishes_empty_list(tmp_path, monkeypatch):
    qdir = tmp_path / "queue"
    qdir.mkdir()
    monkeypatch.setattr(queue_mod, "QUEUE_DIR", qdir)
    docs_data = tmp_path / "docs" / "data"
    assert dashboard.publish_queue_preview(docs_data, tmp_path / "unused") == []
    assert json.loads((docs_data / "queue.json").read_text()) == []


def test_queue_entries_carry_metadata_but_no_image_url(tmp_path, monkeypatch):
    """A queued candidate has not been uploaded to Roblox, so it has no CDN
    URL, and images are no longer committed for the dashboard to link to."""
    qdir = tmp_path / "queue"
    qdir.mkdir()
    (qdir / "candidate-001.png").write_bytes(b"img")
    (qdir / "candidate-001.json").write_text(json.dumps({
        "generated_at": "2026-09-12T00:00:00Z", "prompt": "a prompt",
        "source_thumbnail_id": "thumb-001",
    }))
    monkeypatch.setattr(queue_mod, "QUEUE_DIR", qdir)

    entries = dashboard.publish_queue_preview(tmp_path / "docs" / "data",
                                              tmp_path / "unused")
    assert entries[0]["filename"] == "candidate-001.png"
    assert entries[0]["prompt"] == "a prompt"
    assert "url" not in entries[0]
