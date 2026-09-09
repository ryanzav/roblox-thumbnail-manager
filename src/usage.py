"""Ledger of AI image-generation usage and estimated spend.

Google's Gemini API reports token usage per response but does not expose an
account balance, so "remaining credits" can only be derived from a budget the
operator states in config.
"""

import csv
import logging
from pathlib import Path

from .config import REPO_ROOT
from .history import _atomic_write

log = logging.getLogger(__name__)

USAGE_CSV = REPO_ROOT / "data" / "usage.csv"

COLUMNS = ["timestamp", "filename", "model", "source_thumbnail_id",
           "prompt_tokens", "output_tokens", "total_tokens", "estimated_cost_usd"]


def append_usage(row: dict, path: Path = USAGE_CSV) -> None:
    """Append one generation to the ledger. Never raises on a bad row."""
    try:
        existing = path.read_text() if path.exists() else ""
        lines = [existing.rstrip("\n")] if existing.strip() else [",".join(COLUMNS)]
        lines.append(",".join(_field(row.get(c, "")) for c in COLUMNS))
        _atomic_write(path, "\n".join(lines) + "\n")
    except Exception as exc:  # accounting must never fail a run
        log.warning("Could not record usage: %s", exc)


def _field(value) -> str:
    s = "" if value is None else str(value)
    if any(ch in s for ch in ',"\n'):
        s = '"' + s.replace('"', '""') + '"'
    return s


def summarize(path: Path = USAGE_CSV, budget_usd: float = 0.0) -> dict:
    """Totals for the dashboard: images generated, tokens, spend, remaining."""
    images = tokens = 0
    spend = 0.0
    if path.exists():
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                images += 1
                tokens += _num(row.get("total_tokens"))
                spend += _num(row.get("estimated_cost_usd"), float)
    summary = {
        "images_generated": images,
        "total_tokens": tokens,
        "estimated_spend_usd": round(spend, 4),
        "budget_usd": budget_usd or None,
        "estimated_remaining_usd": round(budget_usd - spend, 4) if budget_usd else None,
    }
    return summary


def _num(value, cast=int):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return cast(0)
