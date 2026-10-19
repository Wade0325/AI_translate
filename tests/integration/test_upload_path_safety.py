"""
整合測試：轉錄／批次／VAD 端點只接受 temp_uploads 內的單純檔名
測試範圍：
  WS   /api/v1/ws/{file_uid}
  WS   /api/v1/batch/ws/{batch_id}
  POST /api/v1/vad/test

漏洞重現：filename 帶絕對路徑或 ``..`` 時，``TEMP_UPLOADS_DIR / filename``
會指向上傳目錄外的檔案，任務就拿那個檔案去轉錄（之後還會被搬進 audio_store）。
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import batch, transcription, vad


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
def dispatched(uploads, monkeypatch, in_process_run_mode):
    """記錄派發的任務參數；參數指向上傳目錄外就直接拋錯。

    拋錯讓端點走例外分支關閉連線，漏洞存在時測試會失敗而不是卡在 receive。
    """
    root, _ = uploads
    calls = []

    def _submit_transcription(params, queue):
        if not _is_inside(params["file_path"], root):
            raise AssertionError(f"派發了上傳目錄外的檔案: {params['file_path']}")
        calls.append(params)
        return "task-id"

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
    }


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

    def test_plain_filename_is_dispatched(self, uploads, dispatched):
        root, _ = uploads
        transcription.start_transcription_task_sync(
            json.dumps(_single_payload("ok.mp3")), "uid-ok")
        assert len(dispatched) == 1
        assert dispatched[0]["file_path"] == str(root / "ok.mp3")


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


# ─── VAD 測試端點 ─────────────────────────────────────────────────────────────

class TestVadTest:
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

    def test_plain_filename_runs_vad(self, client: TestClient, uploads, monkeypatch):
        root, _ = uploads
        calls = []
        monkeypatch.setattr(vad, "run_vad_test", lambda path, **k: calls.append(path) or {})

        response = client.post("/api/v1/vad/test", json={"filename": "ok.mp3"})

        assert response.status_code == 200
        assert calls == [root / "ok.mp3"]
