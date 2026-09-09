from datetime import datetime, timezone

from src.analytics import fetch_thumbnail_metrics


class CapturingApi:
    """Records the query bodies instead of calling Roblox."""

    def __init__(self):
        self.bodies = []

    def query_metrics(self, body):
        self.bodies.append(body)
        return {"done": True, "response": {"values": []}}


def test_window_includes_today(monkeypatch):
    # A day bucket ending at today 00:00 excludes today entirely, which hid
    # every thumbnail whose traffic only started today.
    api = CapturingApi()
    fetch_thumbnail_metrics(api, ["123"])
    now = datetime.now(timezone.utc)
    for body in api.bodies:
        end = datetime.strptime(body["endTime"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        assert end > now, f"endTime {body['endTime']} excludes today"


def test_window_spans_the_lookback(monkeypatch):
    api = CapturingApi()
    fetch_thumbnail_metrics(api, ["123"], lookback_days=7)
    body = api.bodies[0]
    start = datetime.strptime(body["startTime"], "%Y-%m-%dT%H:%M:%SZ")
    end = datetime.strptime(body["endTime"], "%Y-%m-%dT%H:%M:%SZ")
    assert 7 <= (end - start).days <= 9


def test_every_metric_is_queried():
    api = CapturingApi()
    fetch_thumbnail_metrics(api, ["123"])
    assert {b["metric"] for b in api.bodies} == {
        "ThumbnailImpressions", "ThumbnailQualifiedPTR", "ThumbnailQualifiedPlays",
        "ThumbnailAverageSessionLengthMinutes", "ThumbnailL7QualifiedPTR",
        "ThumbnailWinningSegments"}
