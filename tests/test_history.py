import csv

from src import history
from src.models import ThumbnailMetrics, ThumbnailRecord


def test_append_metrics_creates_header_and_rows(tmp_path):
    path = tmp_path / "metrics.csv"
    rows = [ThumbnailMetrics("thumb-001", "123", "active",
                             impressions=8421, qualified_plays=707,
                             qualified_ptr=0.08396, l7_qualified_ptr=0.0825,
                             average_session_minutes=14.7, winning_segments=12)]
    history.append_metrics("2026-09-08T00:17:00Z", rows, path)
    with open(path) as fh:
        parsed = list(csv.DictReader(fh))
    assert len(parsed) == 1
    assert parsed[0]["thumbnail_key"] == "thumb-001"
    assert parsed[0]["impressions"] == "8421"
    assert parsed[0]["qualified_ptr"] == "0.08396"


def test_append_metrics_is_append_only(tmp_path):
    path = tmp_path / "metrics.csv"
    r1 = [ThumbnailMetrics("a", "1", "active", impressions=100, qualified_ptr=0.05)]
    r2 = [ThumbnailMetrics("a", "1", "active", impressions=200, qualified_ptr=0.06)]
    history.append_metrics("2026-09-08T00:00:00Z", r1, path)
    history.append_metrics("2026-09-08T06:00:00Z", r2, path)
    with open(path) as fh:
        parsed = list(csv.DictReader(fh))
    assert [p["impressions"] for p in parsed] == ["100", "200"]


def test_missing_metrics_written_as_blank_not_zero(tmp_path):
    path = tmp_path / "metrics.csv"
    rows = [ThumbnailMetrics("a", "1", "active")]
    history.append_metrics("2026-09-08T00:00:00Z", rows, path)
    with open(path) as fh:
        parsed = list(csv.DictReader(fh))
    assert parsed[0]["impressions"] == ""
    assert parsed[0]["qualified_ptr"] == ""


def test_thumbnails_roundtrip_with_commas_and_quotes(tmp_path):
    path = tmp_path / "thumbnails.csv"
    records = [ThumbnailRecord(
        thumbnail_key="thumb-001", roblox_asset_id="123", filename="thumb-001.png",
        description='Butterfly, hills, and a "rainbow"',
        prompt="Create a variation...", status="active",
    )]
    history.save_thumbnails(records, path)
    loaded = history.load_thumbnails(path)
    assert loaded == records


def test_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    history.save_state({"next_thumbnail_sequence": 27}, path)
    assert history.load_state(path)["next_thumbnail_sequence"] == 27


def test_load_state_default(tmp_path):
    assert history.load_state(tmp_path / "missing.json")["next_thumbnail_sequence"] == 1
