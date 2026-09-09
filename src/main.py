"""One complete scheduled run. Fails conservatively: analytics problems mean
no thumbnail mutations, and AI-generation problems never block metrics."""

import logging
import sys
from datetime import datetime, timezone

from . import history, queue as queue_mod
from .analytics import AnalyticsError, fetch_thumbnail_metrics
from .config import load_config
from .dashboard import build_dashboard_data
from .describer import DescriptionError, describe_image
from .image_generator import GenerationError, generate_candidate
from .models import ThumbnailMetrics, ThumbnailRecord
from .prompt_builder import build_prompt, choose_source
from .roblox_api import RobloxApi, RobloxApiError
from .selector import choose_changes, eligible_source_keys

log = logging.getLogger("thumbnail-manager")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    timestamp = now_iso()

    records = history.load_thumbnails()
    state = history.load_state()
    evaluation_status = "not evaluated"
    metrics_rows: list[ThumbnailMetrics] = []

    try:
        api = RobloxApi(cfg.roblox_api_key, cfg.roblox_universe_id)
    except RobloxApiError as exc:
        log.error("Cannot start: %s", exc)
        return 1

    # 1. Fetch the current active set from Roblox.
    try:
        remote_thumbnails = api.list_thumbnails()
        active_asset_ids = _active_asset_ids(remote_thumbnails)
        records = _sync_records_with_remote(records, active_asset_ids, state, timestamp)
        log.info("Roblox reports %d active thumbnails", len(active_asset_ids))
    except RobloxApiError as exc:
        log.error("Could not fetch Roblox thumbnail state: %s", exc)
        active_asset_ids = [r.roblox_asset_id for r in records
                            if r.status == "active" and r.roblox_asset_id]
        evaluation_status = "Roblox state unavailable; no changes made"

    tracked_asset_ids = sorted({r.roblox_asset_id for r in records if r.roblox_asset_id})

    # 2. Query analytics for every tracked thumbnail.
    analytics_ok = False
    try:
        by_asset = fetch_thumbnail_metrics(api, tracked_asset_ids)
        analytics_ok = True
        key_by_asset = {r.roblox_asset_id: r.thumbnail_key for r in records}
        status_by_asset = {r.roblox_asset_id: r.status for r in records}
        for asset_id, m in by_asset.items():
            m.thumbnail_key = key_by_asset.get(asset_id, "")
            m.status = ("active" if asset_id in active_asset_ids
                        else status_by_asset.get(asset_id, "inactive"))
            metrics_rows.append(m)
        history.append_metrics(timestamp, metrics_rows)
        log.info("Recorded metrics for %d thumbnails", len(metrics_rows))
    except AnalyticsError as exc:
        log.error("Analytics unavailable: %s — no performance-based decisions", exc)
        evaluation_status = "analytics unavailable; evaluation skipped"

    # 3. Evaluate the active set (only with trustworthy analytics).
    active_metrics = [m for m in metrics_rows if m.status == "active"]
    if analytics_ok and active_metrics:
        result = choose_changes(active_metrics, cfg.minimum_impressions, cfg.qptr_gap_decimal)
        evaluation_status = result.reason
        if result.eligible and result.deactivate:
            names = [m.thumbnail_key or m.roblox_asset_id for m in result.deactivate]
            if cfg.allow_thumbnail_deactivation:
                _apply_deactivation(api, cfg, records, result.deactivate,
                                    active_asset_ids, timestamp)
            else:
                evaluation_status = (
                    f"would deactivate {', '.join(names)} (deactivation disabled)"
                )
                log.info(evaluation_status)
        elif result.eligible:
            evaluation_status = "all active thumbnails within threshold"

    # 4. Fill open slots from the queue.
    if cfg.allow_thumbnail_uploads:
        _fill_slots(api, cfg, records, state, timestamp)

    # 5. Replenish the AI queue. Failures here never fail the run.
    if cfg.allow_ai_generation:
        try:
            _replenish_queue(cfg, records, metrics_rows, state)
        except Exception as exc:
            log.error("Queue replenishment failed (continuing): %s", exc)

    # 6. Mirror Roblox-hosted thumbnail images locally so the dashboard can
    # show them. Best-effort: image problems never fail the run.
    try:
        _download_missing_images(api, records)
    except Exception as exc:
        log.warning("Thumbnail image mirroring failed (continuing): %s", exc)

    # 7. Fill in missing descriptions with Gemini vision so every creative
    # can seed future candidates. Best-effort, never fails the run.
    if cfg.allow_ai_descriptions and cfg.ai_image_api_key:
        try:
            _describe_missing(cfg, records)
        except Exception as exc:
            log.warning("Description generation failed (continuing): %s", exc)

    # 8. Persist and publish.
    state["last_successful_run"] = timestamp
    history.save_thumbnails(records)
    history.save_state(state)
    build_dashboard_data(cfg, metrics_rows, evaluation_status, queue_mod.queue_size())
    log.info("Run complete. Evaluation: %s", evaluation_status)
    return 0


def _active_asset_ids(remote_thumbnails: list[dict]) -> list[str]:
    # The list endpoint returns every uploaded homepage thumbnail, but Roblox
    # serves at most 5 at a time: only entries whose personalizedConfigStatus
    # is Active are in the current rotation.
    ids = []
    for t in remote_thumbnails:
        asset_id = t.get("assetId", t.get("thumbnailAssetId", t.get("targetId")))
        state = str(t.get("personalizedConfigStatus",
                          t.get("state", t.get("status", "active")))).lower()
        if asset_id is not None and state in {"active", "enabled"}:
            ids.append(str(asset_id))
    return ids


def _sync_records_with_remote(records: list[ThumbnailRecord], active_asset_ids: list[str],
                              state: dict, timestamp: str) -> list[ThumbnailRecord]:
    """Reconcile the registry with the live active set; auto-register unknowns."""
    known = {r.roblox_asset_id for r in records if r.roblox_asset_id}
    for asset_id in active_asset_ids:
        if asset_id not in known:
            seq = state.get("next_thumbnail_sequence", 1)
            state["next_thumbnail_sequence"] = seq + 1
            records.append(ThumbnailRecord(
                thumbnail_key=f"thumb-{seq:03d}",
                roblox_asset_id=asset_id,
                activated_at=timestamp,
                status="active",
            ))
            log.info("Registered previously unknown active thumbnail %s", asset_id)
    for r in records:
        if r.roblox_asset_id in active_asset_ids:
            if r.status != "active":
                r.status = "active"
                r.activated_at = r.activated_at or timestamp
        elif r.status == "active":
            r.status = "inactive"
            r.deactivated_at = r.deactivated_at or timestamp
    return records


def _apply_deactivation(api: RobloxApi, cfg, records: list[ThumbnailRecord],
                        to_deactivate, active_asset_ids: list[str], timestamp: str) -> None:
    remove_ids = {m.roblox_asset_id for m in to_deactivate}
    keep_ids = [a for a in active_asset_ids if a not in remove_ids]
    try:
        hp_ids = api.homepage_thumbnail_ids()
        keep_hp = [hp_ids[a] for a in keep_ids if a in hp_ids]
        if len(keep_hp) != len(keep_ids):
            log.error("Could not resolve every thumbnail id; active set unchanged")
            return
        api.set_active_thumbnails(keep_hp)
    except RobloxApiError as exc:
        log.error("Deactivation update failed; active set unchanged: %s", exc)
        return
    active_asset_ids[:] = keep_ids
    for r in records:
        if r.roblox_asset_id in remove_ids:
            r.status = "inactive"
            r.deactivated_at = timestamp
    log.info("Deactivated %d thumbnails", len(remove_ids))


def _fill_slots(api: RobloxApi, cfg, records: list[ThumbnailRecord],
                state: dict, timestamp: str) -> None:
    active = [r for r in records if r.status == "active"]
    open_slots = cfg.target_active_thumbnails - len(active)
    if open_slots <= 0:
        return
    for candidate in queue_mod.list_candidates()[:open_slots]:
        pending = state.get("pending_upload") or {}
        # Any in-flight upload of this candidate must never be repeated, even
        # if its asset has not surfaced yet.
        resuming = pending.get("filename") == candidate["filename"]
        try:
            if resuming and not pending.get("asset_id"):
                # Uploaded by an earlier run that ended before the operation
                # finished; pick that operation back up rather than re-upload.
                log.info("%s was already uploaded; resuming its operation",
                         candidate["filename"])
                new_thumbnail = api.wait_for_upload(pending["operation_id"])
                asset_id = str(new_thumbnail.get("assetId", ""))
                state["pending_upload"]["asset_id"] = asset_id
            elif resuming:
                # A previous run uploaded this image and moderation had not
                # finished. Never upload it a second time.
                asset_id = str(pending["asset_id"])
                log.info("Resuming pending upload %s (asset %s)",
                         candidate["filename"], asset_id)
                new_thumbnail = next((t for t in api.list_thumbnails()
                                      if str(t.get("assetId", "")) == asset_id), None)
                entry = new_thumbnail
                moderation = str((entry or {}).get("moderationStatus", "")).lower()
                if moderation in {"rejected", "declined"}:
                    log.error("%s was rejected by moderation; dropping candidate",
                              candidate["filename"])
                    state["pending_upload"] = None
                    continue
                if moderation != "approved":
                    log.info("%s still awaiting moderation; will retry next run",
                             candidate["filename"])
                    continue
            else:
                # Snapshot before uploading so the new thumbnail can be identified
                # by difference — the upload response carries no reliable id.
                operation_id = api.upload_thumbnail(str(candidate["path"]))
                # Record the in-flight upload immediately: if this run ends
                # before moderation finishes, the next one must resume rather
                # than upload the same image again.
                state["pending_upload"] = {"filename": candidate["filename"],
                                           "asset_id": "",
                                           "operation_id": operation_id,
                                           "uploaded_at": timestamp}
                log.info("Uploaded %s; waiting for moderation", candidate["filename"])
                new_thumbnail = api.wait_for_upload(operation_id)
                asset_id = str(new_thumbnail.get("assetId", ""))
                state["pending_upload"]["asset_id"] = asset_id
                log.info("%s approved as asset %s", candidate["filename"], asset_id)

            # Activation is expressed in homepageThumbnailIds, so resolve the
            # whole intended active set — current actives plus the new upload.
            hp_ids = api.homepage_thumbnail_ids()
            current = [r.roblox_asset_id for r in records if r.status == "active"]
            desired = [hp_ids[a] for a in current if a in hp_ids]
            new_hp = new_thumbnail.get("homepageThumbnailId") or hp_ids.get(asset_id)
            if not new_hp:
                raise RobloxApiError(
                    f"No homepageThumbnailId for uploaded asset {asset_id}")
            api.set_active_thumbnails(desired + [new_hp])
            state["pending_upload"] = None
        except RobloxApiError as exc:
            log.error("Activation of %s failed; leaving it queued: %s",
                      candidate["filename"], exc)
            continue

        seq = state.get("next_thumbnail_sequence", 1)
        state["next_thumbnail_sequence"] = seq + 1
        key = f"thumb-{seq:03d}"
        final_name = key + candidate["path"].suffix
        queue_mod.archive_candidate(candidate, final_name)
        records.append(ThumbnailRecord(
            thumbnail_key=key,
            roblox_asset_id=asset_id,
            filename=final_name,
            description=candidate["description"],
            prompt=candidate["prompt"],
            source_thumbnail_id=candidate["source_thumbnail_id"],
            generated_at=candidate["generated_at"],
            activated_at=timestamp,
            status="active",
        ))
        log.info("Activated %s as %s (asset %s)", candidate["filename"], key, asset_id)


def _download_missing_images(api: RobloxApi, records: list[ThumbnailRecord]) -> None:
    missing = [r for r in records if r.roblox_asset_id
               and (not r.filename or not (queue_mod.ARCHIVE_DIR / r.filename).exists())]
    if not missing:
        return
    urls = api.fetch_asset_image_urls([r.roblox_asset_id for r in missing])
    queue_mod.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for r in missing:
        url = urls.get(r.roblox_asset_id)
        if not url:
            continue
        try:
            image = api.download_image(url)
        except Exception as exc:
            log.warning("Could not download image for %s: %s", r.thumbnail_key, exc)
            continue
        filename = r.filename or f"{r.thumbnail_key}.png"
        (queue_mod.ARCHIVE_DIR / filename).write_bytes(image)
        r.filename = filename
        log.info("Mirrored image for %s", r.thumbnail_key)


def _describe_missing(cfg, records: list[ThumbnailRecord]) -> None:
    for r in records:
        if r.description.strip() or not r.filename:
            continue
        image_path = queue_mod.ARCHIVE_DIR / r.filename
        if not image_path.exists():
            continue
        try:
            r.description = describe_image(cfg, str(image_path))
            log.info("Described %s: %s", r.thumbnail_key, r.description[:80])
        except DescriptionError as exc:
            log.warning("Could not describe %s: %s", r.thumbnail_key, exc)


def _replenish_queue(cfg, records: list[ThumbnailRecord],
                     metrics_rows: list[ThumbnailMetrics], state: dict) -> None:
    active_records = [r for r in records if r.status == "active"]
    deficit = queue_mod.candidates_needed(
        len(active_records), queue_mod.queue_size(), cfg.target_active_thumbnails)
    if deficit <= 0:
        return
    qptr_by_key = {m.thumbnail_key: m.qualified_ptr for m in metrics_rows
                   if m.qualified_ptr is not None}

    # Breed only from the top performers: the best active qPTR and everything
    # within the same gap the deactivation rule uses.
    active_metrics = [m for m in metrics_rows if m.status == "active"]
    winners = eligible_source_keys(active_metrics, cfg.qptr_gap_decimal,
                                   cfg.minimum_impressions)
    if not winners:
        log.warning("No active thumbnail has %d+ impressions with trustworthy "
                    "metrics; skipping generation this run", cfg.minimum_impressions)
        return
    active_records = [r for r in active_records if r.thumbnail_key in winners]
    log.info("Generating from top performers: %s", ", ".join(sorted(winners)))
    generated = 0
    for _ in range(deficit):
        source = choose_source(active_records, qptr_by_key,
                               cfg.source_thumbnail_selection)
        if source is None:
            log.warning("No active thumbnail has a description; cannot generate")
            return
        seq = state.get("next_candidate_sequence", 1)
        state["next_candidate_sequence"] = seq + 1
        stem = f"candidate-{seq:03d}"
        prompt = build_prompt(source)
        try:
            filename = generate_candidate(cfg, prompt, stem,
                                          description=source.description,
                                          source_thumbnail_id=source.thumbnail_key)
            log.info("Generated %s from %s", filename, source.thumbnail_key)
            generated += 1
        except GenerationError as exc:
            log.error("Generation failed for %s: %s", stem, exc)
            break
    log.info("Generated %d new candidates", generated)


if __name__ == "__main__":
    sys.exit(run())
