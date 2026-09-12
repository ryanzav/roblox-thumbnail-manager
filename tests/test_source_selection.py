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


def test_below_impression_gate_is_never_a_source():
    keys = eligible_source_keys([tm("proven", 0.080, impressions=9000),
                                 tm("thin", 0.084, impressions=999)])
    assert keys == {"proven"}


def test_exactly_at_impression_gate_qualifies():
    assert eligible_source_keys([tm("edge", 0.08, impressions=1000)]) == {"edge"}


def test_thin_data_outlier_does_not_raise_the_bar():
    # A 20% qPTR on 100 impressions must not disqualify proven thumbnails.
    keys = eligible_source_keys([tm("outlier", 0.20, impressions=100),
                                 tm("best", 0.084, impressions=9000),
                                 tm("near", 0.080, impressions=9000)])
    assert keys == {"best", "near"}


def test_no_thumbnail_clears_the_gate():
    assert eligible_source_keys([tm("a", 0.08, impressions=500),
                                 tm("b", 0.09, impressions=10)]) == set()


def test_impression_gate_is_configurable():
    thumbs = [tm("a", 0.08, impressions=500)]
    assert eligible_source_keys(thumbs, minimum_impressions=1000) == set()
    assert eligible_source_keys(thumbs, minimum_impressions=100) == {"a"}


def test_gap_is_configurable():
    thumbs = [tm("best", 0.084), tm("other", 0.081)]
    assert eligible_source_keys(thumbs, qptr_gap=0.005) == {"best", "other"}
    assert eligible_source_keys(thumbs, qptr_gap=0.001) == {"best"}


def test_generated_records_do_not_inherit_the_source_description(tmp_path, monkeypatch):
    """A candidate's queue metadata carries the SEED text, not the new image's.

    Copying it onto the activated record left whole lineages sharing one
    ancestor's description, which then re-seeded every later prompt.
    """
    import json
    from src import queue as queue_mod

    (tmp_path / "candidate-001.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    (tmp_path / "candidate-001.json").write_text(json.dumps({
        "generated_at": "2026-09-12T00:00:00Z",
        "source_description": "the ancestor's scene",
        "source_thumbnail_id": "thumb-001",
    }))
    cand = queue_mod.list_candidates(tmp_path)[0]
    assert cand["source_description"] == "the ancestor's scene"
    assert "description" not in cand, "seed text must not masquerade as the image's own"


def test_legacy_queue_metadata_still_readable(tmp_path):
    """Older sidecars used "description" for the seed; keep reading them."""
    import json
    from src import queue as queue_mod

    (tmp_path / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "c.json").write_text(json.dumps({"description": "old seed"}))
    assert queue_mod.list_candidates(tmp_path)[0]["source_description"] == "old seed"
