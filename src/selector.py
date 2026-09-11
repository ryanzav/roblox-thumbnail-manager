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
                   qptr_gap: float = 0.005,
                   deactivate_bottom_n: int = 3) -> SelectionResult:
    """Decide which active thumbnails to deactivate.

    Deactivates thumbnails based on two criteria:
    1. Range criterion: thumbnails whose qPTR is more than qptr_gap below the best
    2. Bottom N criterion: the lowest-performing deactivate_bottom_n thumbnails
       (if there are enough active thumbnails)

    qptr_gap is a decimal rate (0.005 == 0.5 percentage points).
    A thumbnail exactly at the cutoff remains active (range criterion only).
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
    
    # Deactivate thumbnails below the range cutoff
    deactivate = [t for t in active_thumbnails if t.qualified_ptr < cutoff]
    
    # Additionally deactivate the bottom N performers if there are enough actives
    # Only apply bottom-N criterion if we have more than the minimum needed
    if len(active_thumbnails) > deactivate_bottom_n:
        # Sort by qPTR (ascending) to find the worst performers
        sorted_by_qptr = sorted(active_thumbnails, key=lambda t: t.qualified_ptr)
        bottom_n_candidates = sorted_by_qptr[:deactivate_bottom_n]
        
        # Add bottom-N thumbnails to deactivation list if not already there
        for thumb in bottom_n_candidates:
            if thumb not in deactivate:
                deactivate.append(thumb)

    return SelectionResult(
        eligible=True,
        reason="evaluation performed",
        best_qptr=best_qptr,
        cutoff=cutoff,
        deactivate=deactivate,
    )
