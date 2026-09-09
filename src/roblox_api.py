"""All Roblox-specific HTTP operations.

The thumbnail-personalization API is marked Experimental by Roblox, so every
endpoint detail is isolated here. Nothing outside this module should build a
Roblox URL or header.
"""

import logging
import time

import requests

from .imaging import mime_for_path

log = logging.getLogger(__name__)

BASE_URL = "https://apis.roblox.com"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 3


class RobloxApiError(Exception):
    pass


class RobloxApi:
    def __init__(self, api_key: str, universe_id: str, session: requests.Session | None = None):
        if not api_key or not universe_id:
            raise RobloxApiError("ROBLOX_API_KEY and ROBLOX_UNIVERSE_ID are required")
        self._api_key = api_key
        self.universe_id = universe_id
        self._session = session or requests.Session()

    # -- low-level -----------------------------------------------------------

    def _headers(self) -> dict:
        return {"x-api-key": self._api_key}

    def _request(self, method: str, path: str, *, json_body: dict | None = None,
                 files: dict | None = None, params: dict | None = None,
                 timeout: int = 60) -> dict:
        url = f"{BASE_URL}{path}"
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.request(
                    method, url, headers=self._headers(),
                    json=json_body, files=files, params=params, timeout=timeout,
                )
            except requests.RequestException as exc:
                # Never include headers/keys in the log line.
                last_error = exc
                log.warning("Roblox request error (%s %s), attempt %d: %s",
                            method, path, attempt, type(exc).__name__)
                time.sleep(2 ** attempt)
                continue

            if resp.status_code in RETRYABLE_STATUS:
                last_error = RobloxApiError(f"{method} {path} -> HTTP {resp.status_code}")
                log.warning("Roblox transient HTTP %d on %s %s, attempt %d",
                            resp.status_code, method, path, attempt)
                time.sleep(2 ** attempt)
                continue

            if not resp.ok:
                raise RobloxApiError(
                    f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:500]}"
                )
            if not resp.content:
                return {}
            return resp.json()

        raise RobloxApiError(f"{method} {path} failed after {MAX_RETRIES} retries") from last_error

    # -- thumbnail personalization ------------------------------------------

    def get_personalization(self) -> dict:
        return self._request(
            "GET",
            f"/thumbnail-personalization-api/v1/universes/{self.universe_id}/personalization",
        )

    def create_personalization(self, thumbnail_asset_ids: list[str]) -> dict:
        return self._request(
            "POST",
            f"/thumbnail-personalization-api/v1/universes/{self.universe_id}/personalization/create",
            json_body={"thumbnailAssetIds": thumbnail_asset_ids},
        )

    def update_personalization(self, thumbnail_asset_ids: list[str]) -> dict:
        return self._request(
            "POST",
            f"/thumbnail-personalization-api/v1/universes/{self.universe_id}/personalization/update",
            json_body={"thumbnailAssetIds": thumbnail_asset_ids},
        )

    def list_thumbnails(self) -> list[dict]:
        data = self._request(
            "GET",
            f"/thumbnail-personalization-api/v1/universes/{self.universe_id}/thumbnails",
        )
        return data.get("homepageThumbnails", data.get("thumbnails", data.get("data", [])))

    def upload_thumbnail(self, image_path: str) -> str:
        """Upload one image and return its operation id.

        The multipart field must be named `files` (plural). With any other
        name Roblox still answers 200 but registers nothing, returning an
        empty `fileToOperationIdDict`.
        """
        mime = mime_for_path(image_path)
        name = image_path.rsplit("/", 1)[-1]
        with open(image_path, "rb") as fh:
            response = self._request(
                "POST",
                f"/thumbnail-personalization-api/v1/universes/{self.universe_id}/thumbnails/uploads",
                files={"files": (name, fh, mime)},
                timeout=180,
            )
        operations = response.get("fileToOperationIdDict") or {}
        if not operations:
            raise RobloxApiError(f"Roblox registered no upload for {name}")
        return operations.get(name) or next(iter(operations.values()))

    def upload_status(self, operation_id: str | None = None) -> dict:
        """Upload processing status, optionally for one operation.

        Without operationIds the endpoint reports on nothing in particular
        (uploadStatus 2). With it, 1 means the upload is still processing.
        """
        params = {"operationIds": operation_id} if operation_id else None
        path = (f"/thumbnail-personalization-api/v1/universes/{self.universe_id}"
                f"/thumbnails/uploads/status")
        return self._request("GET", path, params=params)

    # uploadStatus values observed from the live API: 1 while the upload is
    # still processing, 2 once it has finished (success or moderation verdict).
    UPLOAD_PENDING = 1

    def wait_for_upload(self, operation_id: str, poll_seconds: int = 10,
                        timeout_seconds: int = 600) -> dict:
        """Wait for one upload operation to finish; return its thumbnail entry.

        The finished result carries `assetId`, `homepageThumbnailId` and
        `moderationStatus`. A newly uploaded thumbnail can take longer to
        surface in the thumbnails list than it takes this operation to
        complete, so the operation is the authoritative signal.
        """
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = self.upload_status(operation_id)
            if status.get("uploadStatus") != self.UPLOAD_PENDING:
                entry = (status.get("uploadThumbnailStatusDict") or {}).get(operation_id)
                if entry is None:
                    results = list((status.get("uploadThumbnailStatusDict") or {}).values())
                    entry = results[0] if results else None
                if entry is None:
                    raise RobloxApiError(
                        "Upload finished but Roblox reported no thumbnail for it")
                moderation = str(entry.get("moderationStatus", "")).lower()
                if moderation in {"rejected", "declined"}:
                    raise RobloxApiError(
                        f"Uploaded thumbnail {entry.get('assetId')} was rejected "
                        f"by moderation")
                return entry
            time.sleep(poll_seconds)
        raise RobloxApiError("Timed out waiting for thumbnail upload processing")

    # -- analytics -----------------------------------------------------------

    def query_metrics(self, body: dict) -> dict:
        return self._request(
            "POST",
            f"/analytics-query-api/v1/universes/{self.universe_id}/metrics",
            json_body=body,
        )

    def fetch_asset_image_urls(self, asset_ids: list[str]) -> dict[str, str]:
        """Resolve asset ids to CDN image URLs via the public thumbnails API.

        Uses no credentials — thumbnails.roblox.com is public — but lives here
        so all Roblox HTTP stays in one module."""
        urls: dict[str, str] = {}
        for i in range(0, len(asset_ids), 100):
            batch = asset_ids[i:i + 100]
            try:
                resp = self._session.get(
                    "https://thumbnails.roblox.com/v1/assets",
                    params={"assetIds": ",".join(batch), "size": "768x432", "format": "Png"},
                    timeout=60,
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                log.warning("Thumbnail image lookup failed: %s", type(exc).__name__)
                continue
            for item in resp.json().get("data", []):
                if item.get("state") == "Completed" and item.get("imageUrl"):
                    urls[str(item["targetId"])] = item["imageUrl"]
        return urls

    def download_image(self, url: str) -> bytes:
        resp = self._session.get(url, timeout=120)
        resp.raise_for_status()
        return resp.content

    def get_operation(self, operation_path: str) -> dict:
        """Fetch a long-running analytics operation by the path the metrics
        endpoint returned (e.g. 'v1/universes/.../operations/metrics/...')."""
        return self._request("GET", f"/analytics-query-api/{operation_path.lstrip('/')}")
