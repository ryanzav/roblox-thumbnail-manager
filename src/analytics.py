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

# The Analytics Query API returns PER-DAY buckets, not a running total. Counts
# must therefore be summed across the window; taking values[-1] yields only the
# current (partial) day — for a 30-day window that is roughly a 7% slice, which
# silently pushed every creative under the impressions gate in selector.py.
SUM_FIELDS = {"impressions", "qualified_plays"}
# Point-in-time values where the newest bucket is the meaningful one.
LAST_VALUE_FIELDS = {"l7_qualified_ptr", "winning_segments"}
# Averaged across buckets, unweighted: each metric is merged independently so
# per-bucket impressions are not available here to weight by. This field is
# display-only and never used for ranking, so the approximation is harmless.
MEAN_FIELDS = {"average_session_minutes"}

# qualified_ptr is derived in _finalize() rather than read from the API.
# ThumbnailQualifiedPTR is a PER-BUCKET rate, so the newest bucket can describe
# a handful of impressions: thumb-010 reported 6.78% off a 59-impression day
# against 2.66% over 7.35M impressions. Ranking on that retires the wrong
# creatives. Roblox's own qPTR is plays / impressions (its CSV export reports
# 243 / 7,302 = 0.033279), so deriving over the summed window matches their
# definition and keeps numerator and denominator on the same span.

# Below this, a derived rate is noise and is left as None so `trustworthy`
# (models.py) keeps the creative out of ranking rather than ranking it at 0.0.
MIN_RATE_IMPRESSIONS = 50


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

    _finalize(results)
    return results


def _merge_metric(results: dict[str, ThumbnailMetrics], metric: str, data: dict) -> None:
    """Fold one metric's datapoints into the per-asset result map.

    The Analytics Query API returns grouped time series in per-day buckets, so
    counts are summed over the requested window and averages are averaged
    across buckets. qualified_ptr is deliberately NOT read from the API here:
    ThumbnailQualifiedPTR is a per-bucket rate, so the newest bucket can
    describe a trivial sample. It is derived in _finalize() from the summed
    counts instead, so numerator and denominator always describe the same
    window.
    """
    field = METRIC_FIELD[metric]
    for group in _iter_groups(data):
        asset_id = _group_asset_id(group)
        if asset_id is None or asset_id not in results:
            continue
        points = group.get("dataPoints", group.get("datapoints", []))
        values = [p.get("value") for p in points if p.get("value") is not None]
        if not values:
            continue

        if field in SUM_FIELDS:
            value = int(sum(values))
        elif field in LAST_VALUE_FIELDS:
            value = int(values[-1]) if field == "winning_segments" else float(values[-1])
        elif field in MEAN_FIELDS:
            value = float(sum(values) / len(values))
        else:
            # qualified_ptr lands here and is intentionally skipped; see
            # _finalize(). Any unrecognised field is ignored rather than
            # guessed at.
            continue

        setattr(results[asset_id], field, value)


def _finalize(results: dict[str, ThumbnailMetrics]) -> None:
    """Derive qualified_ptr from the summed counts.

    This is Roblox's own definition - its CSV export reports 243 qualified
    plays over 7,302 impressions as 0.033279 - applied across the same window
    the counts cover, so numerator and denominator always agree.

    Left as None when the sample is too small to rank on, so a quiet creative is
    treated as "unknown" rather than as a genuine 0% performer.
    """
    for metrics in results.values():
        impressions = metrics.impressions
        plays = metrics.qualified_plays
        if impressions is None or plays is None:
            continue
        if impressions < MIN_RATE_IMPRESSIONS:
            metrics.qualified_ptr = None
            continue
        metrics.qualified_ptr = plays / impressions


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
