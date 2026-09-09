"""The automated decision policy. Pure logic, no I/O."""

from .models import SelectionResult, ThumbnailMetrics


def choose_changes(active_thumbnails: list[ThumbnailMetrics],
                   minimum_impressions: int = 1000,
                   qptr_gap: float = 0.005) -> SelectionResult:
    """Decide which active thumbnails to deactivate.

    qptr_gap is a decimal rate (0.005 == 0.5 percentage points).
    A thumbnail exactly at the cutoff remains active.
    """
    if not active_thumbnails:
        return SelectionResult(eligible=False, reason="no active thumbnails")

    if any(not t.trustworthy for t in active_thumbnails):
        return SelectionResult(
            eligible=False,
            reason="missing metrics for at least one active thumbnail; gate closed",
        )

    if any(t.impressions < minimum_impressions for t in active_thumbnails):
        return SelectionResult(
            eligible=False,
            reason=f"waiting for all active thumbnails to reach {minimum_impressions} impressions",
        )

    best_qptr = max(t.qualified_ptr for t in active_thumbnails)
    cutoff = best_qptr - qptr_gap
    deactivate = [t for t in active_thumbnails if t.qualified_ptr < cutoff]

    return SelectionResult(
        eligible=True,
        reason="evaluation performed",
        best_qptr=best_qptr,
        cutoff=cutoff,
        deactivate=deactivate,
    )
