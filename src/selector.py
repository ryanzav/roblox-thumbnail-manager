"""The automated decision policy. Pure logic, no I/O."""

from .models import SelectionResult, ThumbnailMetrics


def eligible_source_keys(active_thumbnails: list[ThumbnailMetrics],
                         qptr_gap: float = 0.005,
                         minimum_impressions: int = 1000) -> set[str]:
    """Keys of the top-performing active thumbnails: the best qPTR and every
    thumbnail within qptr_gap of it.

    This is the same cutoff the deactivation rule uses, so new creatives are
    only bred from thumbnails good enough to keep.

    A thumbnail must clear the same impression gate to qualify: below
    minimum_impressions its qPTR is not trustworthy enough to call it a
    winner, and thumbnails without metrics never qualify. The best qPTR is
    measured among qualifying thumbnails only, so a thin-data outlier cannot
    raise the bar and starve the pool.
    """
    qualified = [t for t in active_thumbnails
                 if t.trustworthy and t.impressions >= minimum_impressions]
    if not qualified:
        return set()
    best_qptr = max(t.qualified_ptr for t in qualified)
    cutoff = best_qptr - qptr_gap
    return {t.thumbnail_key for t in qualified if t.qualified_ptr >= cutoff}


def choose_changes(active_thumbnails: list[ThumbnailMetrics],
                   minimum_impressions: int = 1000,
                   qptr_gap: float = 0.005) -> SelectionResult:
    """Decide which active thumbnails to deactivate.

    qptr_gap is a decimal rate (0.005 == 0.5 percentage points).
    A thumbnail exactly at the cutoff remains active.
    """
    if not active_thumbnails:
        return SelectionResult(eligible=False, reason="no active thumbnails")

    unmeasured = [t for t in active_thumbnails if not t.trustworthy]
    if unmeasured:
        names = ", ".join(sorted(t.thumbnail_key or t.roblox_asset_id
                                 for t in unmeasured))
        return SelectionResult(
            eligible=False,
            reason=f"gate closed: Roblox reports no analytics for {names}",
        )

    below = [t for t in active_thumbnails if t.impressions < minimum_impressions]
    if below:
        names = ", ".join(f"{t.thumbnail_key or t.roblox_asset_id} "
                          f"({t.impressions:,})" for t in
                          sorted(below, key=lambda t: t.impressions))
        return SelectionResult(
            eligible=False,
            reason=f"waiting for {minimum_impressions:,} impressions: {names}",
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
