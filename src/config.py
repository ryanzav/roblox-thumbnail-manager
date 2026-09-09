"""Configuration loading: config.json for policy, environment for secrets."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "minimum_impressions": 1000,
    "qptr_deactivation_gap_percentage_points": 0.5,
    "target_active_thumbnails": 5,
    "queue_target_size": 10,
    "queue_order": "fifo",
    "source_thumbnail_selection": "weighted_random",
    "allow_thumbnail_deactivation": False,
    "allow_thumbnail_uploads": False,
    "allow_ai_generation": False,
    "image_provider": "gemini",
    "image_model": "imagen-4.0-generate-001",
}


@dataclass
class Config:
    minimum_impressions: int
    qptr_deactivation_gap_percentage_points: float
    target_active_thumbnails: int
    queue_target_size: int
    queue_order: str
    source_thumbnail_selection: str
    allow_thumbnail_deactivation: bool
    allow_thumbnail_uploads: bool
    allow_ai_generation: bool
    image_provider: str
    image_model: str

    roblox_api_key: str = field(default="", repr=False)
    roblox_universe_id: str = ""
    ai_image_api_key: str = field(default="", repr=False)

    @property
    def qptr_gap_decimal(self) -> float:
        """0.5 percentage points expressed as a decimal rate (0.005)."""
        return self.qptr_deactivation_gap_percentage_points / 100.0


def load_config(path: Path | None = None) -> Config:
    load_dotenv(REPO_ROOT / ".env")

    path = path or REPO_ROOT / "config.json"
    raw = dict(DEFAULTS)
    if path.exists():
        raw.update(json.loads(path.read_text()))

    cfg = Config(**{k: raw[k] for k in DEFAULTS})
    cfg.roblox_api_key = os.environ.get("ROBLOX_API_KEY", "")
    cfg.roblox_universe_id = os.environ.get("ROBLOX_UNIVERSE_ID", "")
    cfg.ai_image_api_key = os.environ.get("AI_IMAGE_API_KEY", "")
    return cfg
