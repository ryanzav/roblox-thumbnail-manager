import pytest

from src.roblox_api import RobloxApi, RobloxApiError


class FakeApi(RobloxApi):
    """RobloxApi with list_thumbnails scripted and sleeping disabled."""

    def __init__(self, pages):
        self._pages = list(pages)
        self._api_key = "k"
        self.universe_id = "1"
        self.calls = 0

    def list_thumbnails(self):
        self.calls += 1
        return self._pages[min(self.calls - 1, len(self._pages) - 1)]


def thumb(asset_id, moderation="Approved"):
    return {"assetId": asset_id, "moderationStatus": moderation,
            "personalizedConfigStatus": "Inactive"}


def test_returns_the_newly_appeared_thumbnail(monkeypatch):
    monkeypatch.setattr("src.roblox_api.time.sleep", lambda s: None)
    api = FakeApi([[thumb("1")], [thumb("1"), thumb("99")]])
    result = api.wait_for_new_thumbnail({"1"}, poll_seconds=0, timeout_seconds=5)
    assert str(result["assetId"]) == "99"


def test_ignores_thumbnails_that_existed_before(monkeypatch):
    monkeypatch.setattr("src.roblox_api.time.sleep", lambda s: None)
    api = FakeApi([[thumb("1"), thumb("2")]])
    with pytest.raises(RobloxApiError, match="never appeared"):
        api.wait_for_new_thumbnail({"1", "2"}, poll_seconds=0, timeout_seconds=0.05)


def test_moderation_rejection_raises_immediately(monkeypatch):
    monkeypatch.setattr("src.roblox_api.time.sleep", lambda s: None)
    api = FakeApi([[thumb("99", moderation="Rejected")]])
    with pytest.raises(RobloxApiError, match="rejected by moderation"):
        api.wait_for_new_thumbnail(set(), poll_seconds=0, timeout_seconds=5)


def test_still_pending_moderation_reports_the_asset(monkeypatch):
    monkeypatch.setattr("src.roblox_api.time.sleep", lambda s: None)
    api = FakeApi([[thumb("99", moderation="Pending")]])
    with pytest.raises(RobloxApiError, match="awaiting moderation"):
        api.wait_for_new_thumbnail(set(), poll_seconds=0, timeout_seconds=0.05)
