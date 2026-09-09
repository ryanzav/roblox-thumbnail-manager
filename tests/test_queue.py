import json

from src import queue as queue_mod


def make_candidate(queue_dir, name, generated_at):
    (queue_dir / name).write_bytes(b"\x89PNG fake image data")
    (queue_dir / name).with_suffix(".json").write_text(json.dumps({
        "generated_at": generated_at,
        "prompt": "p", "description": "d", "source_thumbnail_id": "thumb-001",
    }))


def test_fifo_ordering_by_generated_at(tmp_path):
    make_candidate(tmp_path, "b.png", "2026-09-02T00:00:00Z")
    make_candidate(tmp_path, "a.png", "2026-09-01T00:00:00Z")
    names = [c["filename"] for c in queue_mod.list_candidates(tmp_path)]
    assert names == ["a.png", "b.png"]


def test_empty_queue(tmp_path):
    assert queue_mod.list_candidates(tmp_path) == []
    assert queue_mod.queue_size(tmp_path) == 0


def test_missing_queue_dir(tmp_path):
    assert queue_mod.list_candidates(tmp_path / "nope") == []


def test_corrupt_metadata_still_listed(tmp_path):
    (tmp_path / "x.png").write_bytes(b"data")
    (tmp_path / "x.json").write_text("{not json")
    cands = queue_mod.list_candidates(tmp_path)
    assert len(cands) == 1
    assert cands[0]["prompt"] == ""


def test_empty_image_skipped(tmp_path):
    (tmp_path / "empty.png").write_bytes(b"")
    assert queue_mod.list_candidates(tmp_path) == []


def test_archive_moves_file_out_of_queue(tmp_path):
    qdir = tmp_path / "queue"
    qdir.mkdir()
    adir = tmp_path / "archive"
    make_candidate(qdir, "cand.png", "2026-09-01T00:00:00Z")
    cand = queue_mod.list_candidates(qdir)[0]
    dest = queue_mod.archive_candidate(cand, "thumb-005.png", adir)
    assert dest.exists()
    assert dest.read_bytes() == b"\x89PNG fake image data"
    assert not (qdir / "cand.png").exists()
    assert not (qdir / "cand.json").exists()


def test_write_candidate_creates_pair(tmp_path):
    queue_mod.write_candidate(b"img", "candidate-001.png", {"prompt": "p"}, tmp_path)
    assert (tmp_path / "candidate-001.png").read_bytes() == b"img"
    assert json.loads((tmp_path / "candidate-001.json").read_text())["prompt"] == "p"
