import pytest

from src.roblox_api import RobloxApi, RobloxApiError


class FakeApi(RobloxApi):
    """RobloxApi with upload_status scripted and sleeping disabled."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self._api_key = "k"
        self.universe_id = "1"
        self.calls = 0

    def upload_status(self, operation_id=None):
        self.calls += 1
        return self._statuses[min(self.calls - 1, len(self._statuses) - 1)]


def done(entry, op="op-1"):
    return {"uploadStatus": 2, "uploadThumbnailStatusDict": {op: entry}}


PENDING = {"uploadStatus": 1, "uploadThumbnailStatusDict": {}}


def test_returns_entry_once_upload_completes(monkeypatch):
    monkeypatch.setattr("src.roblox_api.time.sleep", lambda s: None)
    api = FakeApi([PENDING, done({"assetId": 99, "moderationStatus": "Approved"})])
    result = api.wait_for_upload("op-1", poll_seconds=0, timeout_seconds=5)
    assert result["assetId"] == 99


def test_moderation_rejection_raises(monkeypatch):
    monkeypatch.setattr("src.roblox_api.time.sleep", lambda s: None)
    api = FakeApi([done({"assetId": 99, "moderationStatus": "Rejected"})])
    with pytest.raises(RobloxApiError, match="rejected by moderation"):
        api.wait_for_upload("op-1", poll_seconds=0, timeout_seconds=5)


def test_still_pending_times_out(monkeypatch):
    monkeypatch.setattr("src.roblox_api.time.sleep", lambda s: None)
    api = FakeApi([PENDING])
    with pytest.raises(RobloxApiError, match="Timed out"):
        api.wait_for_upload("op-1", poll_seconds=0, timeout_seconds=0.05)


def test_finished_with_no_result_raises(monkeypatch):
    monkeypatch.setattr("src.roblox_api.time.sleep", lambda s: None)
    api = FakeApi([{"uploadStatus": 2, "uploadThumbnailStatusDict": {}}])
    with pytest.raises(RobloxApiError, match="no thumbnail"):
        api.wait_for_upload("op-1", poll_seconds=0, timeout_seconds=5)


class RecordingApi(RobloxApi):
    """Captures the multipart payload instead of sending it."""

    def __init__(self, response):
        self._api_key = "k"
        self.universe_id = "1"
        self._response = response
        self.sent = None

    def _request(self, method, path, *, json_body=None, files=None, params=None, timeout=60):
        self.sent = {"path": path, "files": files, "params": params}
        return self._response


def test_upload_uses_the_plural_files_field(tmp_path):
    img = tmp_path / "candidate-001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    api = RecordingApi({"fileToOperationIdDict": {"candidate-001.png": "op-123"}})
    assert api.upload_thumbnail(str(img)) == "op-123"
    # A singular "file" field is silently ignored by Roblox.
    assert list(api.sent["files"]) == ["files"]


def test_upload_registering_nothing_raises(tmp_path):
    img = tmp_path / "candidate-001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    api = RecordingApi({"fileToOperationIdDict": {}})
    with pytest.raises(RobloxApiError, match="registered no upload"):
        api.upload_thumbnail(str(img))


def test_upload_status_passes_operation_ids():
    api = RecordingApi({"uploadStatus": 1})
    api.upload_status("op-123")
    assert api.sent["params"] == {"operationIds": "op-123"}
