from src.models import ThumbnailMetrics
from src.selector import choose_changes


def tm(key, impressions, qptr):
    return ThumbnailMetrics(
        thumbnail_key=key, roblox_asset_id=key, status="active",
        impressions=impressions, qualified_ptr=qptr,
    )


def test_no_active_thumbnails():
    result = choose_changes([])
    assert not result.eligible
    assert result.deactivate == []


def test_all_above_gate_allows_evaluation():
    result = choose_changes([tm("a", 1000, 0.08), tm("b", 5000, 0.081)])
    assert result.eligible


def test_one_below_gate_blocks_deactivation():
    result = choose_changes([tm("a", 8400, 0.084), tm("b", 999, 0.01)])
    assert not result.eligible
    assert result.deactivate == []


def test_cutoff_boundaries():
    """The range criterion alone, with the bottom-N rule switched off.

    Both rules apply together in production; isolating this one is the only
    way to pin the 0.5-point boundary, since bottom-N would retire these
    regardless of how close they are.
    """
    # best 8.4% -> cutoff 7.9%
    best = tm("best", 5000, 0.084)
    keep_above = tm("k1", 5000, 0.0791)
    keep_exact = tm("k2", 5000, 0.0790)
    remove = tm("r", 5000, 0.0789)
    result = choose_changes([best, keep_above, keep_exact, remove],
                            deactivate_bottom_n=0)
    assert result.eligible
    keys = {t.thumbnail_key for t in result.deactivate}
    assert keys == {"r"}


def test_exact_cutoff_stays_active():
    result = choose_changes([tm("best", 2000, 0.084), tm("edge", 2000, 0.084 - 0.005)])
    assert result.deactivate == []


def test_missing_metrics_closes_gate():
    good = tm("a", 5000, 0.08)
    missing = ThumbnailMetrics(thumbnail_key="b", roblox_asset_id="b",
                               status="active", impressions=None, qualified_ptr=None)
    result = choose_changes([good, missing])
    assert not result.eligible
    assert result.deactivate == []


def test_multiple_weak_removed():
    """Range criterion in isolation: everything more than 0.5 points back."""
    result = choose_changes([
        tm("a", 8900, 0.084), tm("b", 7400, 0.080), tm("c", 5800, 0.076),
        tm("d", 3400, 0.077), tm("e", 1200, 0.082),
    ], deactivate_bottom_n=0)
    assert result.eligible
    assert {t.thumbnail_key for t in result.deactivate} == {"c", "d"}


def test_bottom_three_are_retired_even_when_tightly_grouped():
    """The bottom-N rule ignores closeness, so a near-leader is still cut.

    With five active thumbnails all within 0.05 points, the range criterion
    would keep every one; bottom-N retires three anyway.
    """
    result = choose_changes([
        tm("a", 5000, 0.0840), tm("b", 5000, 0.0839), tm("c", 5000, 0.0838),
        tm("d", 5000, 0.0837), tm("e", 5000, 0.0836),
    ])
    assert result.eligible
    assert {t.thumbnail_key for t in result.deactivate} == {"c", "d", "e"}


def test_the_two_criteria_are_unioned_without_duplicates():
    result = choose_changes([
        tm("best", 5000, 0.084), tm("near", 5000, 0.0835), tm("mid", 5000, 0.083),
        tm("weak", 5000, 0.070), tm("worst", 5000, 0.060),
    ])
    assert result.eligible
    # weak and worst fail both rules; mid is added by bottom-N alone.
    assert {t.thumbnail_key for t in result.deactivate} == {"mid", "weak", "worst"}
    assert len(result.deactivate) == 3, "a thumbnail failing both rules is listed once"


def test_bottom_n_does_not_empty_a_small_active_set():
    """With no more actives than N, the bottom-N rule is skipped entirely,
    so the range criterion decides alone and the set is never wiped out."""
    result = choose_changes([
        tm("a", 5000, 0.084), tm("b", 5000, 0.0838), tm("c", 5000, 0.0836),
    ])
    assert result.eligible
    assert result.deactivate == []


def test_gate_message_names_thumbnails_without_analytics():
    missing = ThumbnailMetrics(thumbnail_key="thumb-002", roblox_asset_id="x",
                               status="active", impressions=None, qualified_ptr=None)
    result = choose_changes([tm("thumb-001", 5000, 0.03), missing])
    assert not result.eligible
    assert "thumb-002" in result.reason
    assert "no analytics" in result.reason


def test_gate_message_names_thumbnails_below_the_impression_gate():
    result = choose_changes([tm("thumb-001", 5000, 0.03), tm("thumb-011", 12, 0.02)])
    assert not result.eligible
    assert "thumb-011" in result.reason
    assert "12" in result.reason
