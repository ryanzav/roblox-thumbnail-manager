import random
from collections import Counter

from src.models import ThumbnailRecord
from src.prompt_builder import (COMPOSITION_VARIATIONS, LIGHTING_VARIATIONS,
                                STYLE_VARIATIONS, SUBJECT_VARIATIONS,
                                build_prompt)

SOURCE = ThumbnailRecord(thumbnail_key="thumb-001", description="A castle on a hill")


def subject_lines(prompt):
    return [l for l in prompt.splitlines() if l in SUBJECT_VARIATIONS]


def test_subject_count_varies_between_one_and_five():
    counts = Counter(len(subject_lines(build_prompt(SOURCE, random.Random(seed))))
                     for seed in range(300))
    assert set(counts) <= {1, 2, 3, 4, 5}
    assert set(counts) == {1, 2, 3, 4, 5}, f"only saw {sorted(counts)}"


def test_subjects_are_never_repeated_within_a_prompt():
    for seed in range(200):
        lines = subject_lines(build_prompt(SOURCE, random.Random(seed)))
        assert len(lines) == len(set(lines))


def test_every_subject_option_can_be_chosen():
    seen = set()
    for seed in range(300):
        seen.update(subject_lines(build_prompt(SOURCE, random.Random(seed))))
    assert seen == set(SUBJECT_VARIATIONS)


def test_the_other_categories_still_contribute_exactly_one_line_each():
    for seed in range(50):
        prompt = build_prompt(SOURCE, random.Random(seed))
        assert sum(l in STYLE_VARIATIONS for l in prompt.splitlines()) == 1
        assert sum(l in COMPOSITION_VARIATIONS for l in prompt.splitlines()) == 1
        assert sum(l in LIGHTING_VARIATIONS for l in prompt.splitlines()) == 1


def test_the_description_is_always_present():
    prompt = build_prompt(SOURCE, random.Random(1))
    assert "A castle on a hill" in prompt


def test_the_same_seed_reproduces_the_same_prompt():
    assert build_prompt(SOURCE, random.Random(7)) == build_prompt(SOURCE, random.Random(7))
