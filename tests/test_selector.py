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
    # best 8.4% -> cutoff 7.9%
    best = tm("best", 5000, 0.084)
    keep_above = tm("k1", 5000, 0.0791)
    keep_exact = tm("k2", 5000, 0.0790)
    remove = tm("r", 5000, 0.0789)
    result = choose_changes([best, keep_above, keep_exact, remove])
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
    result = choose_changes([
        tm("a", 8900, 0.084), tm("b", 7400, 0.080), tm("c", 5800, 0.076),
        tm("d", 3400, 0.077), tm("e", 1200, 0.082),
    ])
    assert result.eligible
    assert {t.thumbnail_key for t in result.deactivate} == {"c", "d"}
