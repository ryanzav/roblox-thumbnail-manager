import json

from src import dashboard, history
from src.config import Config, DEFAULTS
from src.models import ThumbnailMetrics


def make_config():
    return Config(**DEFAULTS)


def test_build_dashboard_data(tmp_path, monkeypatch):
    metrics_csv = tmp_path / "metrics.csv"
    thumbs_csv = tmp_path / "thumbnails.csv"
    metrics_csv.write_text("timestamp,thumbnail_key\n2026-09-08T00:00:00Z,thumb-001\n")
    thumbs_csv.write_text("thumbnail_key,status\nthumb-001,active\n")
    monkeypatch.setattr(dashboard, "METRICS_CSV", metrics_csv)
    monkeypatch.setattr(dashboard, "THUMBNAILS_CSV", thumbs_csv)

    docs_data = tmp_path / "docs" / "data"
    metrics = [
        ThumbnailMetrics("thumb-001", "123", "active", impressions=5000, qualified_ptr=0.084),
        ThumbnailMetrics("thumb-002", "456", "inactive", impressions=100, qualified_ptr=0.09),
    ]
    dashboard.build_dashboard_data(make_config(), metrics, "evaluation performed", 8, docs_data)

    assert (docs_data / "metrics.csv").read_text() == metrics_csv.read_text()
    assert (docs_data / "thumbnails.csv").read_text() == thumbs_csv.read_text()

    latest = json.loads((docs_data / "latest.json").read_text())
    assert latest["active_count"] == 1
    assert latest["queue_size"] == 8
    # best qPTR must come from ACTIVE thumbnails only
    assert latest["best_qptr"] == 0.084
    assert latest["evaluation_status"] == "evaluation performed"


def test_build_dashboard_data_no_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "METRICS_CSV", tmp_path / "missing-metrics.csv")
    monkeypatch.setattr(dashboard, "THUMBNAILS_CSV", tmp_path / "missing-thumbs.csv")
    docs_data = tmp_path / "docs" / "data"
    dashboard.build_dashboard_data(make_config(), [], "not evaluated", 0, docs_data)
    latest = json.loads((docs_data / "latest.json").read_text())
    assert latest["active_count"] == 0
    assert latest["best_qptr"] is None
