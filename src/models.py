"""Shared data models."""

from dataclasses import dataclass, field


@dataclass
class ThumbnailMetrics:
    """One analytics snapshot for one thumbnail."""

    thumbnail_key: str
    roblox_asset_id: str
    status: str
    impressions: int | None = None
    qualified_plays: int | None = None
    qualified_ptr: float | None = None  # decimal, e.g. 0.084 for 8.4%
    l7_qualified_ptr: float | None = None
    average_session_minutes: float | None = None
    winning_segments: int | None = None

    @property
    def trustworthy(self) -> bool:
        """A metric row is usable for ranking only when impressions and qPTR exist."""
        return self.impressions is not None and self.qualified_ptr is not None


@dataclass
class ThumbnailRecord:
    """One row of data/thumbnails.csv — the canonical creative registry."""

    thumbnail_key: str
    roblox_asset_id: str = ""
    filename: str = ""
    description: str = ""
    prompt: str = ""
    source_thumbnail_id: str = ""
    generated_at: str = ""
    activated_at: str = ""
    deactivated_at: str = ""
    status: str = "queued"


@dataclass
class SelectionResult:
    """Outcome of one evaluation of the active set."""

    eligible: bool
    reason: str
    best_qptr: float | None = None
    cutoff: float | None = None
    deactivate: list[ThumbnailMetrics] = field(default_factory=list)
