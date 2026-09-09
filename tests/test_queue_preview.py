import json

from src import dashboard, queue as queue_mod


def test_queue_preview_publishes_images_and_metadata(tmp_path, monkeypatch):
    qdir = tmp_path / "queue"
    qdir.mkdir()
    (qdir / "candidate-001.png").write_bytes(b"img-bytes")
    (qdir / "candidate-001.json").write_text(json.dumps({
        "generated_at": "2026-09-09T00:00:00Z", "prompt": "Create a variation...",
        "description": "A butterfly", "source_thumbnail_id": "thumb-001",
        "provider": "gemini", "model": "imagen-4.0-generate-001",
    }))
    monkeypatch.setattr(queue_mod, "QUEUE_DIR", qdir)

    docs_data, img_dir = tmp_path / "docs" / "data", tmp_path / "docs" / "images" / "queue"
    entries = dashboard.publish_queue_preview(docs_data, img_dir)

    assert (img_dir / "candidate-001.png").read_bytes() == b"img-bytes"
    published = json.loads((docs_data / "queue.json").read_text())
    assert published == entries
    assert published[0]["source_thumbnail_id"] == "thumb-001"
    assert published[0]["prompt"] == "Create a variation..."


def test_queue_preview_removes_stale_images(tmp_path, monkeypatch):
    qdir = tmp_path / "queue"
    qdir.mkdir()
    monkeypatch.setattr(queue_mod, "QUEUE_DIR", qdir)

    docs_data, img_dir = tmp_path / "docs" / "data", tmp_path / "docs" / "images" / "queue"
    img_dir.mkdir(parents=True)
    # An image left over from a candidate that has since been activated.
    (img_dir / "candidate-old.png").write_bytes(b"stale")

    entries = dashboard.publish_queue_preview(docs_data, img_dir)

    assert entries == []
    assert not (img_dir / "candidate-old.png").exists()
    assert json.loads((docs_data / "queue.json").read_text()) == []
