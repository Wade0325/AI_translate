"""
整合測試：轉錄／批次／VAD 端點只接受 temp_uploads 內的單純檔名
測試範圍：
  WS   /api/v1/ws/{file_uid}
  WS   /api/v1/batch/ws/{batch_id}
  POST /api/v1/vad/test

漏洞重現：filename 帶絕對路徑或 ``..`` 時，``TEMP_UPLOADS_DIR / filename``
會指向上傳目錄外的檔案，任務就拿那個檔案去轉錄（之後還會被搬進 audio_store）。

被拒的檔名與找不到的上傳檔名都要用 repr 記進 log：排查只能靠使用者附上的 log（ADR-0005）。
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import batch, transcription, vad
from tests.support.task_api import receive


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """三個端點的 TEMP_UPLOADS_DIR 都指向 tmp_path/uploads；secret.txt 在上傳目錄之外。"""
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "ok.mp3").write_bytes(b"audio")
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    for module in (transcription, batch, vad):
        monkeypatch.setattr(module, "TEMP_UPLOADS_DIR", root)
    return root, secret


def _is_inside(path: str, root) -> bool:
    return Path(path).resolve().parent == root.resolve()


@pytest.fixture
def dispatched(uploads, monkeypatch, in_process_run_mode, task_db):
    """記錄派發的任務參數；參數指向上傳目錄外就直接拋錯。

    拋錯讓端點走例外分支關閉連線，漏洞存在時測試會失敗而不是卡在 receive。派發時會從資料庫讀
    提示詞範本（#144），資料庫指到測試的 sqlite（task_db）。
    """
    root, _ = uploads
    calls = []

    def _submit_transcription(task_id, params, queue):
        if not _is_inside(params["file_path"], root):
            raise AssertionError(f"派發了上傳目錄外的檔案: {params['file_path']}")
        calls.append(params)

    def _submit_batch(params):
        for f in params["files"]:
            if not _is_inside(f["file_path"], root):
                raise AssertionError(f"派發了上傳目錄外的檔案: {f['file_path']}")
        calls.append(params)
        return "task-id"

    monkeypatch.setattr(in_process_run_mode, "submit_transcription", _submit_transcription)
    monkeypatch.setattr(in_process_run_mode, "submit_batch", _submit_batch)
    return calls


def _single_payload(filename: str) -> dict:
    return {
        "filename": filename,
        "original_filename": "a.mp3",
        "provider": "Google",
        "model": "gemini-2.5-flash",
        "api_keys": "plain-key-for-test",
        "source_lang": "ja-JP",
    }


def _batch_payload(files: list[dict]) -> dict:
    return {
        "files": files,
        "provider": "Google",
        "model": "gemini-2.5-flash",
        "api_keys": "plain-key-for-test",
        "source_lang": "ja-JP",
    }


def _traversal_names(root, secret):
    return {
        "absolute": str(secret),
        "dotdot": "../secret.txt",
        "absolute_via_uploads": str(root / ".." / "secret.txt"),
        # 帶換行：照字面寫進 log 會多出一行假的 log
        "forged_log_line": "../a.wav\n2026-10-20 12:00:00 - INFO - 偽造的一行",
    }


def _logged_as_repr(app_log, filename: str) -> bool:
    """log 有沒有用 repr 記下這個檔名：換行等控制字元跳脫成看得見的字，混不進假的 log 行。"""
    return any(repr(filename) in message for message in app_log)


# 「被拒的檔名記進 log」測的幾種可疑檔名
LOGGED_KINDS = ["absolute", "dotdot", "forged_log_line"]

# 帶換行、但不含路徑的檔名：通過檔名檢查，上傳目錄裡卻沒有這個檔（#153）
MISSING_WITH_FORGED_LOG_LINE = "a.wav\n2026-10-20 12:00:00 - INFO - 偽造的一行"


# ─── 單檔 WS ─────────────────────────────────────────────────────────────────

class TestSingleTranscription:
    @pytest.mark.parametrize("kind", ["absolute", "dotdot", "absolute_via_uploads"])
    def test_rejects_path_outside_uploads(self, client: TestClient, uploads, dispatched, kind):
        root, secret = uploads
        filename = _traversal_names(root, secret)[kind]

        with client.websocket_connect("/api/v1/ws/uid-traversal") as ws:
            ws.send_json(_single_payload(filename))
            message = ws.receive_json()

        assert message["status_code"] == "FAILED"
        assert message["file_uid"] == "uid-traversal"
        assert "檔案名稱不合法" in message["status_text"]
        assert dispatched == []
        assert secret.exists()

    @pytest.mark.parametrize("kind", LOGGED_KINDS)
    def test_rejected_filename_is_logged(self, client: TestClient, uploads, app_log, kind):
        filename = _traversal_names(*uploads)[kind]

        with client.websocket_connect("/api/v1/ws/uid-traversal") as ws:
            ws.send_json(_single_payload(filename))
            ws.receive_json()

        assert _logged_as_repr(app_log, filename)

    def test_missing_upload_is_logged(self, client: TestClient, uploads, app_log):
        with client.websocket_connect("/api/v1/ws/uid-missing") as ws:
            ws.send_json(_single_payload(MISSING_WITH_FORGED_LOG_LINE))
            receive(ws)

        assert _logged_as_repr(app_log, MISSING_WITH_FORGED_LOG_LINE)

    def test_plain_filename_is_dispatched(self, uploads, dispatched):
        root, _ = uploads
        transcription.start_transcription_task_sync(
            json.dumps(_single_payload("ok.mp3")), "uid-ok")
        assert len(dispatched) == 1
        assert dispatched[0]["file_path"] == str(root / "ok.mp3")

    @pytest.mark.parametrize("kind", ["absolute", "dotdot", "absolute_via_uploads"])
    def test_rejected_request_does_not_delete_files_outside_uploads(
            self, client: TestClient, uploads, dispatched, kind):
        # 被拒絕的請求會刪掉它的上傳檔：檔名指向上傳目錄外時一律不動
        root, secret = uploads
        payload = {**_single_payload(_traversal_names(root, secret)[kind]), "provider": "Local"}

        with client.websocket_connect("/api/v1/ws/uid-rejected-traversal") as ws:
            ws.send_json(payload)
            message = ws.receive_json()

        assert message["status_code"] == "FAILED"
        assert dispatched == []
        assert secret.exists()


# ─── 批次 WS ─────────────────────────────────────────────────────────────────

class TestBatchTranscription:
    @pytest.mark.parametrize("kind", ["absolute", "dotdot", "absolute_via_uploads"])
    def test_rejects_path_outside_uploads(self, client: TestClient, uploads, dispatched, kind):
        root, secret = uploads
        filename = _traversal_names(root, secret)[kind]
        payload = _batch_payload([
            {"filename": filename, "original_filename": "s.txt", "file_uid": "uid-bad"},
        ])

        with client.websocket_connect("/api/v1/batch/ws/batch-traversal") as ws:
            ws.send_json(payload)
            message = ws.receive_json()

        assert message["status_code"] == "FAILED"
        assert message["file_uid"] == "uid-bad"
        assert "檔案名稱不合法" in message["status_text"]
        assert dispatched == []

    @pytest.mark.parametrize("kind", ["absolute", "dotdot", "absolute_via_uploads"])
    def test_rejected_batch_does_not_delete_files_outside_uploads(
            self, client: TestClient, uploads, dispatched, kind):
        # 被拒絕的批次會刪掉它的上傳檔：檔名指向上傳目錄外時一律不動
        root, secret = uploads
        payload = {**_batch_payload([
            {"filename": _traversal_names(root, secret)[kind], "original_filename": "s.txt",
             "file_uid": "uid-bad"},
        ]), "provider": "Local"}

        with client.websocket_connect("/api/v1/batch/ws/batch-rejected-traversal") as ws:
            ws.send_json(payload)
            message = ws.receive_json()

        assert message["status_code"] == "FAILED"
        assert dispatched == []
        assert secret.exists()

    @pytest.mark.parametrize("kind", LOGGED_KINDS)
    def test_rejected_filename_is_logged(self, client: TestClient, uploads, app_log, kind):
        filename = _traversal_names(*uploads)[kind]
        payload = _batch_payload([
            {"filename": filename, "original_filename": "s.txt", "file_uid": "uid-bad"},
        ])

        with client.websocket_connect("/api/v1/batch/ws/batch-traversal") as ws:
            ws.send_json(payload)
            ws.receive_json()

        assert _logged_as_repr(app_log, filename)

    def test_missing_upload_is_logged(self, client: TestClient, uploads, app_log):
        payload = _batch_payload([
            {"filename": MISSING_WITH_FORGED_LOG_LINE, "original_filename": "a.wav",
             "file_uid": "uid-missing"},
        ])

        with client.websocket_connect("/api/v1/batch/ws/batch-missing") as ws:
            ws.send_json(payload)
            receive(ws)

        assert _logged_as_repr(app_log, MISSING_WITH_FORGED_LOG_LINE)

    def test_valid_files_still_dispatched_when_one_is_rejected(
            self, client: TestClient, uploads, dispatched):
        root, secret = uploads
        payload = _batch_payload([
            {"filename": "ok.mp3", "original_filename": "ok.mp3", "file_uid": "uid-ok"},
            {"filename": str(secret), "original_filename": "s.txt", "file_uid": "uid-bad"},
        ])

        with client.websocket_connect("/api/v1/batch/ws/batch-mixed") as ws:
            ws.send_json(payload)
            message = ws.receive_json()

        assert message["status_code"] == "FAILED"
        assert message["file_uid"] == "uid-bad"
        assert len(dispatched) == 1
        assert [f["file_uid"] for f in dispatched[0]["files"]] == ["uid-ok"]
        assert dispatched[0]["files"][0]["file_path"] == str(root / "ok.mp3")


# ─── 去靜音與切點預覽的端點 ───────────────────────────────────────────────────

class TestVadTest:
    @pytest.fixture(autouse=True)
    def dev_tools(self, monkeypatch):
        """去靜音與切點預覽是開發者工具，要開了才跑（#13 Q6）。"""
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "dev_tools", True)

    @pytest.mark.parametrize("kind", ["absolute", "dotdot", "absolute_via_uploads"])
    def test_rejects_path_outside_uploads(self, client: TestClient, uploads, monkeypatch, kind):
        root, secret = uploads
        calls = []
        monkeypatch.setattr(vad, "run_vad_test", lambda *a, **k: calls.append(a) or {})

        response = client.post("/api/v1/vad/test", json={
            "filename": _traversal_names(root, secret)[kind],
        })

        assert response.status_code == 400
        assert "檔案名稱不合法" in response.json()["detail"]
        assert calls == []

    @pytest.mark.parametrize("kind", LOGGED_KINDS)
    def test_rejected_filename_is_logged(self, client: TestClient, uploads, app_log, kind):
        filename = _traversal_names(*uploads)[kind]

        client.post("/api/v1/vad/test", json={"filename": filename})

        assert _logged_as_repr(app_log, filename)

    def test_plain_filename_runs_vad(self, client: TestClient, uploads, monkeypatch):
        root, _ = uploads
        calls = []
        monkeypatch.setattr(vad, "run_vad_test", lambda path, **k: calls.append(path) or {})

        response = client.post("/api/v1/vad/test", json={"filename": "ok.mp3"})

        assert response.status_code == 200
        assert calls == [root / "ok.mp3"]
