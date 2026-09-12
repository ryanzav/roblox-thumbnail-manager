"""Manages thumbnails/queue/ — the local pool of AI-generated candidates.

Each candidate is <name>.png plus a <name>.json metadata sidecar. Ordering is
FIFO by generation timestamp (falling back to filename) so behavior is
deterministic.
"""

import json
import logging
import shutil
from pathlib import Path

from .config import REPO_ROOT
from .imaging import IMAGE_EXTENSIONS

log = logging.getLogger(__name__)

QUEUE_DIR = REPO_ROOT / "thumbnails" / "queue"
ARCHIVE_DIR = REPO_ROOT / "docs" / "images" / "thumbnails"


def list_candidates(queue_dir: Path = QUEUE_DIR) -> list[dict]:
    """Return queued candidates oldest-first. Skips corrupt/missing pairs."""
    if not queue_dir.exists():
        return []
    candidates = []
    images = sorted(p for p in queue_dir.iterdir()
                    if p.suffix.lower() in IMAGE_EXTENSIONS)
    for png in images:
        if png.stat().st_size == 0:
            log.warning("Skipping empty queue file %s", png.name)
            continue
        meta_path = png.with_suffix(".json")
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                log.warning("Corrupt metadata for %s; using defaults", png.name)
        candidates.append({
            "path": png,
            "filename": png.name,
            "generated_at": meta.get("generated_at", ""),
            "prompt": meta.get("prompt", ""),
            "source_description": meta.get("source_description",
                                           meta.get("description", "")),
            "source_thumbnail_id": meta.get("source_thumbnail_id", ""),
            "provider": meta.get("provider", ""),
            "model": meta.get("model", ""),
        })
    candidates.sort(key=lambda c: (c["generated_at"] or "9999", c["filename"]))
    return candidates


def write_candidate(image_bytes: bytes, filename: str, metadata: dict,
                    queue_dir: Path = QUEUE_DIR) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    png = queue_dir / filename
    png.write_bytes(image_bytes)
    png.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return png


def archive_candidate(candidate: dict, final_filename: str,
                      archive_dir: Path = ARCHIVE_DIR) -> Path:
    """Move an activated candidate's image out of the queue into the
    permanent tracked-image directory. Never deletes the only copy."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / final_filename
    shutil.copy2(candidate["path"], dest)
    if dest.exists() and dest.stat().st_size == candidate["path"].stat().st_size:
        candidate["path"].unlink()
        meta = candidate["path"].with_suffix(".json")
        if meta.exists():
            meta.unlink()
    return dest


def queue_size(queue_dir: Path = QUEUE_DIR) -> int:
    return len(list_candidates(queue_dir))


def candidates_needed(active_count: int, queued_count: int,
                      target_active: int) -> int:
    """How many candidates to generate: enough to fill the open active slots,
    counting candidates already waiting in the queue.

    Generation is demand-driven — a candidate is only worth paying for when
    there is a slot for it — so a full active set generates nothing.
    """
    open_slots = target_active - active_count
    return max(0, open_slots - queued_count)
