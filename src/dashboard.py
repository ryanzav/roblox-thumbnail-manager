"""Prepares the data consumed by the static GitHub Pages dashboard."""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import queue as queue_mod
from .config import REPO_ROOT, Config
from .history import METRICS_CSV, THUMBNAILS_CSV
from .imaging import IMAGE_EXTENSIONS
from .usage import summarize
from .models import ThumbnailMetrics, ThumbnailRecord

DOCS_DATA_DIR = REPO_ROOT / "docs" / "data"
DOCS_QUEUE_IMAGE_DIR = REPO_ROOT / "docs" / "images" / "queue"
LATEST_JSON = DOCS_DATA_DIR / "latest.json"


def build_dashboard_data(cfg: Config, metrics: list[ThumbnailMetrics],
                         evaluation_status: str, queue_count: int,
                         docs_data_dir: Path = DOCS_DATA_DIR,
                         records: list[ThumbnailRecord] | None = None) -> None:
    docs_data_dir.mkdir(parents=True, exist_ok=True)

    for src in (METRICS_CSV, THUMBNAILS_CSV):
        if src.exists():
            shutil.copy2(src, docs_data_dir / src.name)

    # Count from the registry, not the metrics snapshot: metrics are collected
    # before this run's activations, so a thumbnail activated moments ago is
    # already active but has no row yet.
    if records is not None:
        active_keys = {r.thumbnail_key for r in records if r.status == "active"}
    else:
        active_keys = {m.thumbnail_key for m in metrics if m.status == "active"}
    active = [m for m in metrics if m.thumbnail_key in active_keys]
    best = max((m.qualified_ptr for m in active if m.qualified_ptr is not None), default=None)

    publish_queue_preview(docs_data_dir)

    latest = {
        "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active_count": len(active_keys),
        "target_active": cfg.target_active_thumbnails,
        "queue_size": queue_count,
        "best_qptr": best,
        "evaluation_status": evaluation_status,
        "gate_impressions": cfg.minimum_impressions,
        "usage": summarize(budget_usd=cfg.image_budget_usd),
    }
    (docs_data_dir / "latest.json").write_text(json.dumps(latest, indent=2) + "\n")


def publish_queue_preview(docs_data_dir: Path = DOCS_DATA_DIR,
                          queue_image_dir: Path = DOCS_QUEUE_IMAGE_DIR) -> list[dict]:
    """Mirror pending queue candidates into docs/ so Pages can preview them.

    The queue is the staging area for creatives that have not been uploaded to
    Roblox yet, so these images live only in the repo until activation.
    """
    candidates = queue_mod.list_candidates(queue_mod.QUEUE_DIR)

    entries = []
    for c in candidates:
        entries.append({
            "filename": c["filename"],
            "url": queue_image_url(c["filename"]),
            "generated_at": c["generated_at"],
            "prompt": c["prompt"],
            "description": c["description"],
            "source_thumbnail_id": c["source_thumbnail_id"],
            "provider": c["provider"],
            "model": c["model"],
            "total_tokens": c.get("total_tokens", ""),
            "estimated_cost_usd": c.get("estimated_cost_usd", ""),
        })

    docs_data_dir.mkdir(parents=True, exist_ok=True)
    (docs_data_dir / "queue.json").write_text(json.dumps(entries, indent=2) + "\n")
    return entries


def queue_image_url(filename: str) -> str:
    """Where the dashboard should load a queued candidate from.

    Queued images live only in thumbnails/queue/, which GitHub Pages does not
    publish (it serves docs/ alone), so the dashboard reads them straight from
    the repository instead of keeping a second copy under docs/.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    if repo:
        return f"https://raw.githubusercontent.com/{repo}/{branch}/thumbnails/queue/{filename}"
    return f"../thumbnails/queue/{filename}"
