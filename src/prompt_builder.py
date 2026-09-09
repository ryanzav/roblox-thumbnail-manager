"""Builds AI generation prompts from a source thumbnail's description."""

import random

from .models import ThumbnailRecord

PROMPT_TEMPLATE = """Create a new Roblox game thumbnail inspired by this existing
thumbnail concept:

"{description}"

Create a visually distinct variation rather than a duplicate.
Preserve the game's visual identity while changing composition,
camera angle, subject emphasis, background arrangement, or
supporting elements. Make it attractive at Roblox thumbnail size.
16:9 composition. No text unless specifically requested."""


def build_prompt(source: ThumbnailRecord) -> str:
    return PROMPT_TEMPLATE.format(description=source.description.strip())


def choose_source(active_records: list[ThumbnailRecord],
                  qptr_by_key: dict[str, float] | None = None,
                  strategy: str = "weighted_random",
                  rng: random.Random | None = None) -> ThumbnailRecord | None:
    """Pick one active thumbnail with a usable description as the seed."""
    rng = rng or random.Random()
    usable = [r for r in active_records if r.description.strip()]
    if not usable:
        return None
    if strategy == "weighted_random" and qptr_by_key:
        weights = [max(qptr_by_key.get(r.thumbnail_key, 0.0), 0.0001) for r in usable]
        return rng.choices(usable, weights=weights, k=1)[0]
    return rng.choice(usable)
