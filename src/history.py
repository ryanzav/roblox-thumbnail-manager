"""Maintains data/metrics.csv, data/thumbnails.csv, and data/state.json.

Writes are atomic (temp file + os.replace) so an interrupted run cannot
corrupt history.
"""

import csv
import json
import os
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

from .config import REPO_ROOT
from .models import ThumbnailMetrics, ThumbnailRecord

DATA_DIR = REPO_ROOT / "data"
METRICS_CSV = DATA_DIR / "metrics.csv"
THUMBNAILS_CSV = DATA_DIR / "thumbnails.csv"
STATE_JSON = DATA_DIR / "state.json"

METRICS_COLUMNS = [
    "timestamp", "thumbnail_key", "roblox_asset_id", "status",
    "impressions", "qualified_plays", "qualified_ptr", "l7_qualified_ptr",
    "average_session_minutes", "winning_segments",
]

THUMBNAIL_COLUMNS = [f.name for f in fields(ThumbnailRecord)]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", newline="") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_metrics(timestamp: str, rows: list[ThumbnailMetrics],
                   path: Path = METRICS_CSV) -> None:
    """Append one snapshot. Rewrites the whole file atomically to avoid a
    torn append; metrics.csv is append-only in content, not in mechanism."""
    existing = path.read_text() if path.exists() else ""
    out = []
    if not existing.strip():
        out.append(",".join(METRICS_COLUMNS))
    else:
        out.append(existing.rstrip("\n"))
    for m in rows:
        record = {
            "timestamp": timestamp,
            **{k: ("" if v is None else v) for k, v in asdict(m).items()},
        }
        out.append(",".join(_csv_field(record.get(c, "")) for c in METRICS_COLUMNS))
    _atomic_write(path, "\n".join(out) + "\n")


def _csv_field(value) -> str:
    s = str(value)
    if any(ch in s for ch in ',"\n'):
        s = '"' + s.replace('"', '""') + '"'
    return s


def load_thumbnails(path: Path = THUMBNAILS_CSV) -> list[ThumbnailRecord]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        return [
            ThumbnailRecord(**{c: (row.get(c) or "") for c in THUMBNAIL_COLUMNS})
            for row in reader
        ]


def save_thumbnails(records: list[ThumbnailRecord], path: Path = THUMBNAILS_CSV) -> None:
    lines = [",".join(THUMBNAIL_COLUMNS)]
    for r in records:
        d = asdict(r)
        lines.append(",".join(_csv_field(d[c]) for c in THUMBNAIL_COLUMNS))
    _atomic_write(path, "\n".join(lines) + "\n")


def load_state(path: Path = STATE_JSON) -> dict:
    if not path.exists():
        return {"next_thumbnail_sequence": 1}
    return json.loads(path.read_text())


def save_state(state: dict, path: Path = STATE_JSON) -> None:
    _atomic_write(path, json.dumps(state, indent=2) + "\n")
