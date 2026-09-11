from src.analytics import MIN_RATE_IMPRESSIONS, fetch_thumbnail_metrics


class StubApi:
    """Serves canned per-day buckets for each metric."""

    def __init__(self, buckets):
        self.buckets = buckets

    def query_metrics(self, body):
        groups = [
            {"breakdowns": [{"dimension": "ThumbnailAsset", "value": asset}],
             "dataPoints": [{"time": f"2026-09-{d:02d}T00:00:00Z", "value": v}
                            for d, v in enumerate(values, start=1)]}
            for asset, values in self.buckets.get(body["metric"], {}).items()
        ]
        return {"done": True, "response": {"values": groups}}


def test_counts_are_summed_not_taken_from_the_last_bucket():
    # Buckets are per-day and non-monotonic, so the newest one is a single
    # partial day - summing is the only way to describe the window.
    api = StubApi({
        "ThumbnailImpressions": {"1": [12490, 48770, 65871, 36611, 20300]},
        "ThumbnailQualifiedPlays": {"1": [400, 1500, 2000, 1100, 711]},
    })
    m = fetch_thumbnail_metrics(api, ["1"])["1"]
    assert m.impressions == 184042
    assert m.qualified_plays == 5711


def test_qptr_is_derived_over_the_same_window_as_the_counts():
    api = StubApi({
        "ThumbnailImpressions": {"1": [7302]},
        "ThumbnailQualifiedPlays": {"1": [243]},
    })
    m = fetch_thumbnail_metrics(api, ["1"])["1"]
    # Roblox's own export reports this pair as 0.0332786.
    assert round(m.qualified_ptr, 7) == 0.0332786


def test_a_noisy_final_bucket_cannot_inflate_the_rate():
    # thumb-010's real shape: heavy traffic, then a 59-impression day whose
    # per-bucket qPTR was 6.78%. Ranking must use the window rate, not that.
    api = StubApi({
        "ThumbnailImpressions": {"1": [131704, 47837, 59]},
        "ThumbnailQualifiedPlays": {"1": [3600, 1210, 4]},
        "ThumbnailQualifiedPTR": {"1": [0.0275, 0.0253, 0.0678]},
    })
    m = fetch_thumbnail_metrics(api, ["1"])["1"]
    expected = 4814 / 179600
    assert abs(m.qualified_ptr - expected) < 1e-12
    assert m.qualified_ptr < 0.03


def test_tiny_samples_are_left_unknown_rather_than_ranked():
    api = StubApi({
        "ThumbnailImpressions": {"1": [MIN_RATE_IMPRESSIONS - 1]},
        "ThumbnailQualifiedPlays": {"1": [3]},
    })
    m = fetch_thumbnail_metrics(api, ["1"])["1"]
    assert m.qualified_ptr is None
    assert not m.trustworthy


def test_zero_plays_is_a_real_zero_rate_when_the_sample_is_large():
    api = StubApi({
        "ThumbnailImpressions": {"1": [5000]},
        "ThumbnailQualifiedPlays": {"1": [0]},
    })
    m = fetch_thumbnail_metrics(api, ["1"])["1"]
    assert m.qualified_ptr == 0.0


def test_l7_rate_and_segments_take_the_newest_bucket():
    api = StubApi({
        "ThumbnailL7QualifiedPTR": {"1": [0.02, 0.03, 0.031]},
        "ThumbnailWinningSegments": {"1": [1, 2, 5]},
    })
    m = fetch_thumbnail_metrics(api, ["1"])["1"]
    assert m.l7_qualified_ptr == 0.031
    assert m.winning_segments == 5


def test_session_length_is_averaged_across_buckets():
    api = StubApi({"ThumbnailAverageSessionLengthMinutes": {"1": [10.0, 11.0, 12.0]}})
    m = fetch_thumbnail_metrics(api, ["1"])["1"]
    assert abs(m.average_session_minutes - 11.0) < 1e-9
