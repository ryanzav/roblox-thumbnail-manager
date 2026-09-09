"""Prepares the data consumed by the static GitHub Pages dashboard."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import queue as queue_mod
from .config import REPO_ROOT, Config
from .history import METRICS_CSV, THUMBNAILS_CSV
from .models import ThumbnailMetrics

DOCS_DATA_DIR = REPO_ROOT / "docs" / "data"
DOCS_QUEUE_IMAGE_DIR = REPO_ROOT / "docs" / "images" / "queue"
LATEST_JSON = DOCS_DATA_DIR / "latest.json"


def build_dashboard_data(cfg: Config, metrics: list[ThumbnailMetrics],
                         evaluation_status: str, queue_count: int,
                         docs_data_dir: Path = DOCS_DATA_DIR) -> None:
    docs_data_dir.mkdir(parents=True, exist_ok=True)

    for src in (METRICS_CSV, THUMBNAILS_CSV):
        if src.exists():
            shutil.copy2(src, docs_data_dir / src.name)

    active = [m for m in metrics if m.status == "active"]
    best = max((m.qualified_ptr for m in active if m.qualified_ptr is not None), default=None)

    publish_queue_preview(docs_data_dir)

    latest = {
        "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active_count": len(active),
        "target_active": cfg.target_active_thumbnails,
        "queue_size": queue_count,
        "best_qptr": best,
        "evaluation_status": evaluation_status,
        "gate_impressions": cfg.minimum_impressions,
    }
    (docs_data_dir / "latest.json").write_text(json.dumps(latest, indent=2) + "\n")


def publish_queue_preview(docs_data_dir: Path = DOCS_DATA_DIR,
                          queue_image_dir: Path = DOCS_QUEUE_IMAGE_DIR) -> list[dict]:
    """Mirror pending queue candidates into docs/ so Pages can preview them.

    The queue is the staging area for creatives that have not been uploaded to
    Roblox yet, so these images live only in the repo until activation.
    """
    candidates = queue_mod.list_candidates(queue_mod.QUEUE_DIR)
    queue_image_dir.mkdir(parents=True, exist_ok=True)

    current = {c["filename"] for c in candidates}
    for stale in queue_image_dir.glob("*.png"):
        if stale.name not in current:
            stale.unlink()

    entries = []
    for c in candidates:
        shutil.copy2(c["path"], queue_image_dir / c["filename"])
        entries.append({
            "filename": c["filename"],
            "generated_at": c["generated_at"],
            "prompt": c["prompt"],
            "description": c["description"],
            "source_thumbnail_id": c["source_thumbnail_id"],
            "provider": c["provider"],
            "model": c["model"],
        })

    docs_data_dir.mkdir(parents=True, exist_ok=True)
    (docs_data_dir / "queue.json").write_text(json.dumps(entries, indent=2) + "\n")
    return entries
