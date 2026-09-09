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
    assert published[0]["url"].endswith("thumbnails/queue/candidate-001.png")


def test_empty_queue_publishes_empty_list(tmp_path, monkeypatch):
    qdir = tmp_path / "queue"
    qdir.mkdir()
    monkeypatch.setattr(queue_mod, "QUEUE_DIR", qdir)
    docs_data = tmp_path / "docs" / "data"
    assert dashboard.publish_queue_preview(docs_data, tmp_path / "unused") == []
    assert json.loads((docs_data / "queue.json").read_text()) == []


def test_queue_image_url_uses_repo_when_running_in_actions(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    assert dashboard.queue_image_url("c.png") == (
        "https://raw.githubusercontent.com/owner/repo/main/thumbnails/queue/c.png")


def test_queue_image_url_falls_back_to_relative_path(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert dashboard.queue_image_url("c.png") == "../thumbnails/queue/c.png"
