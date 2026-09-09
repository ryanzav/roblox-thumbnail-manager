"""All Roblox-specific HTTP operations.

The thumbnail-personalization API is marked Experimental by Roblox, so every
endpoint detail is isolated here. Nothing outside this module should build a
Roblox URL or header.
"""

import logging
import time

import requests

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
                 files: dict | None = None, timeout: int = 60) -> dict:
        url = f"{BASE_URL}{path}"
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.request(
                    method, url, headers=self._headers(),
                    json=json_body, files=files, timeout=timeout,
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
        return data.get("thumbnails", data.get("data", []))

    def upload_thumbnail(self, image_path: str) -> dict:
        with open(image_path, "rb") as fh:
            return self._request(
                "POST",
                f"/thumbnail-personalization-api/v1/universes/{self.universe_id}/thumbnails/uploads",
                files={"file": (image_path.rsplit("/", 1)[-1], fh, "image/png")},
                timeout=180,
            )

    def upload_status(self) -> dict:
        return self._request(
            "GET",
            f"/thumbnail-personalization-api/v1/universes/{self.universe_id}/thumbnails/uploads/status",
        )

    def wait_for_upload(self, poll_seconds: int = 15, timeout_seconds: int = 600) -> dict:
        """Poll upload processing until it settles or times out."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = self.upload_status()
            state = str(status.get("status", status.get("state", ""))).lower()
            if state and state not in {"pending", "processing", "inprogress", "in_progress"}:
                return status
            time.sleep(poll_seconds)
        raise RobloxApiError("Timed out waiting for thumbnail upload processing")

    # -- analytics -----------------------------------------------------------

    def query_metrics(self, body: dict) -> dict:
        return self._request(
            "POST",
            f"/analytics-query-api/v1/universes/{self.universe_id}/metrics",
            json_body=body,
        )
