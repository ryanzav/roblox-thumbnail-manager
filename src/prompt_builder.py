"""Builds AI generation prompts from a source thumbnail's description."""

import random

from .models import ThumbnailRecord

# Base template with variation placeholders
PROMPT_TEMPLATE = """Create an incredibly cute, high quality Roblox game thumbnail.
{description}
Make it attractive at Roblox thumbnail size.
16:9 composition. No text unless specifically requested.
{variation}"""

# Style variations to add diversity
STYLE_VARIATIONS = [
    "Use vibrant, saturated colors to make it pop.",
    "Use a pastel color palette for a softer aesthetic.",
    "Use bold, contrasting colors for maximum visual impact.",
    "Use warm tones to create an inviting atmosphere.",
    "Use cool tones for a mysterious, adventurous feel.",
]

# Composition variations
COMPOSITION_VARIATIONS = [
    "Position the main subject in the center for balance.",
    "Use the rule of thirds with the subject off-center.",
    "Frame the subject with environmental elements around it.",
    "Create depth with foreground, subject, and background layers.",
    "Use dynamic diagonal composition for movement and energy.",
]

# Lighting variations
LIGHTING_VARIATIONS = [
    "Use bright, cheerful lighting throughout.",
    "Add dramatic shadows for depth and interest.",
    "Use soft, diffused lighting for a calm feel.",
    "Include glowing elements or light effects.",
    "Use backlighting to create silhouettes and depth.",
]

# Subject variations
SUBJECT_VARIATIONS = [
    "Beautiful butterflies in the distance.",
    "A beautiful rainbow is visible in the distance.",
    "A beautiful butterfly hovers nearby.",
    "A very cute yellow chick and baby owl look friendly.",
    "Delicious looking frosted donut with sprinkles are laid across the landscape.",
]

def build_prompt(source: ThumbnailRecord, rng: random.Random | None = None) -> str:
    """Build a prompt with randomized stylistic variations for diversity."""
    rng = rng or random.Random()
    
    # Select one variation from each category for diversity
    style = rng.choice(STYLE_VARIATIONS)
    composition = rng.choice(COMPOSITION_VARIATIONS)
    lighting = rng.choice(LIGHTING_VARIATIONS)
    # One to five subject lines, sampled without replacement so a prompt never
    # repeats the same element, and shuffled so ordering carries no bias.
    count = rng.randint(1, min(5, len(SUBJECT_VARIATIONS)))
    subject = "\n".join(rng.sample(SUBJECT_VARIATIONS, count))
    
    variation = f"{subject}\n{style}\n{composition}\n{lighting}"
    
    return PROMPT_TEMPLATE.format(
        description=source.description.strip(),
        variation=variation
    )


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
