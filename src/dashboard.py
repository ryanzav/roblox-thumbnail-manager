"""Prepares the data consumed by the static GitHub Pages dashboard."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import REPO_ROOT, Config
from .history import METRICS_CSV, THUMBNAILS_CSV
from .models import ThumbnailMetrics

DOCS_DATA_DIR = REPO_ROOT / "docs" / "data"
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
