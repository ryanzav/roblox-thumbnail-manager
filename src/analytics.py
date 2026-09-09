"""Query Roblox Analytics and normalize results into ThumbnailMetrics."""

import logging
import time
from datetime import datetime, timedelta, timezone

from .models import ThumbnailMetrics
from .roblox_api import RobloxApi, RobloxApiError

log = logging.getLogger(__name__)

METRICS = [
    "ThumbnailImpressions",
    "ThumbnailQualifiedPTR",
    "ThumbnailQualifiedPlays",
    "ThumbnailAverageSessionLengthMinutes",
    "ThumbnailL7QualifiedPTR",
    "ThumbnailWinningSegments",
]

METRIC_FIELD = {
    "ThumbnailImpressions": "impressions",
    "ThumbnailQualifiedPTR": "qualified_ptr",
    "ThumbnailQualifiedPlays": "qualified_plays",
    "ThumbnailAverageSessionLengthMinutes": "average_session_minutes",
    "ThumbnailL7QualifiedPTR": "l7_qualified_ptr",
    "ThumbnailWinningSegments": "winning_segments",
}

INT_FIELDS = {"impressions", "qualified_plays", "winning_segments"}


class AnalyticsError(Exception):
    pass


def fetch_thumbnail_metrics(api: RobloxApi, asset_ids: list[str],
                            lookback_days: int = 30) -> dict[str, ThumbnailMetrics]:
    """Return {roblox_asset_id: ThumbnailMetrics} for every asset we can read.

    Raises AnalyticsError when the analytics API cannot be queried at all —
    callers must treat that as "make no performance-based decision".
    """
    # Day buckets are half-open: an endTime of today 00:00 excludes today
    # entirely, hiding every thumbnail whose traffic only started today.
    # End on tomorrow 00:00 so the current day is included.
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=1)
    start = now - timedelta(days=lookback_days)

    results: dict[str, ThumbnailMetrics] = {
        asset_id: ThumbnailMetrics(thumbnail_key="", roblox_asset_id=asset_id, status="")
        for asset_id in asset_ids
    }

    any_success = False
    for metric in METRICS:
        body = {
            "metric": metric,
            "granularity": "OneDay",
            "startTime": start.strftime("%Y-%m-%dT00:00:00Z"),
            "endTime": end.strftime("%Y-%m-%dT00:00:00Z"),
            "breakdown": ["ThumbnailAsset"],
        }
        try:
            data = api.query_metrics(body)
            data = _resolve_operation(api, data)
        except RobloxApiError as exc:
            log.error("Analytics query failed for %s: %s", metric, exc)
            continue
        any_success = True
        _merge_metric(results, metric, data)

    if not any_success:
        raise AnalyticsError("Every analytics query failed")
    return results


def _merge_metric(results: dict[str, ThumbnailMetrics], metric: str, data: dict) -> None:
    """Fold one metric's datapoints into the per-asset result map.

    The Analytics Query API returns grouped time series; we keep the most
    recent non-null value per asset (rates) or the sum (counts).
    """
    field = METRIC_FIELD[metric]
    for group in _iter_groups(data):
        asset_id = _group_asset_id(group)
        if asset_id is None or asset_id not in results:
            continue
        values = [
            p.get("value") for p in group.get("dataPoints", group.get("datapoints", []))
            if p.get("value") is not None
        ]
        if not values:
            continue
        if field in INT_FIELDS and field != "winning_segments":
            value = int(sum(values))
        elif field == "winning_segments":
            value = int(values[-1])
        else:
            value = float(values[-1])
        setattr(results[asset_id], field, value)


def _resolve_operation(api: RobloxApi, data: dict) -> dict:
    """The metrics endpoint returns a long-running operation envelope:
    {"path": ..., "done": bool, "response": {...}}. Poll until done."""
    for _ in range(10):
        if data.get("done") or "path" not in data:
            break
        time.sleep(3)
        data = api.get_operation(data["path"])
    if "path" in data and not data.get("done"):
        raise RobloxApiError("Analytics operation did not complete in time")
    return data


def _iter_groups(data: dict):
    # Unwrap the operation envelope, then tolerate a few plausible shapes
    # since the API is experimental.
    if isinstance(data.get("response"), dict):
        data = data["response"]
    for key in ("values", "breakdownDataPoints", "groups", "data"):
        groups = data.get(key)
        if isinstance(groups, list):
            return groups
    return []


def _group_asset_id(group: dict) -> str | None:
    breakdown = group.get("breakdowns", group.get(
        "breakdownValue", group.get("breakdown", group.get("dimensionValues"))))
    if isinstance(breakdown, list):
        for item in breakdown:
            if isinstance(item, dict) and item.get("value") is not None:
                return str(item["value"])
        return None
    if isinstance(breakdown, dict):
        value = breakdown.get("ThumbnailAsset", breakdown.get("value"))
        return str(value) if value is not None else None
    if breakdown is not None:
        return str(breakdown)
    return None
