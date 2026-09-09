from src.models import ThumbnailMetrics
from src.selector import eligible_source_keys


def tm(key, qptr, impressions=5000, status="active"):
    return ThumbnailMetrics(thumbnail_key=key, roblox_asset_id=key, status=status,
                            impressions=impressions, qualified_ptr=qptr)


def test_only_best_and_within_gap_are_sources():
    # best 8.4% -> cutoff 7.9%
    keys = eligible_source_keys([
        tm("best", 0.084),
        tm("near", 0.0791),
        tm("edge", 0.0790),
        tm("weak", 0.0789),
        tm("worst", 0.072),
    ])
    assert keys == {"best", "near", "edge"}


def test_single_thumbnail_is_its_own_winner():
    assert eligible_source_keys([tm("only", 0.03)]) == {"only"}


def test_unmeasured_thumbnails_are_never_sources():
    measured = tm("measured", 0.08)
    unmeasured = ThumbnailMetrics(thumbnail_key="unmeasured", roblox_asset_id="x",
                                  status="active", impressions=None, qualified_ptr=None)
    assert eligible_source_keys([measured, unmeasured]) == {"measured"}


def test_no_metrics_returns_empty_set():
    unmeasured = ThumbnailMetrics(thumbnail_key="a", roblox_asset_id="x",
                                  status="active", impressions=None, qualified_ptr=None)
    assert eligible_source_keys([unmeasured]) == set()
    assert eligible_source_keys([]) == set()


def test_low_impressions_still_eligible_as_source():
    # The gate governs deactivation, not breeding: a promising new thumbnail
    # can seed candidates before it reaches 1,000 impressions.
    keys = eligible_source_keys([tm("old", 0.080, impressions=9000),
                                 tm("new", 0.084, impressions=200)])
    assert keys == {"new", "old"}


def test_gap_is_configurable():
    thumbs = [tm("best", 0.084), tm("other", 0.081)]
    assert eligible_source_keys(thumbs, qptr_gap=0.005) == {"best", "other"}
    assert eligible_source_keys(thumbs, qptr_gap=0.001) == {"best"}
