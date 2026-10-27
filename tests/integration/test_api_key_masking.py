"""
整合測試：API 金鑰只留在後端
測試範圍：
  GET  /api/v1/setting/models/{provider}   回傳遮罩值
  POST /api/v1/setting/models              遮罩值／空值不覆蓋資料庫中的金鑰
  POST /api/v1/setting/test                遮罩值或沒帶金鑰時改用資料庫的金鑰
  WS   /api/v1/ws/{file_uid}、/api/v1/batch/ws/{batch_id}
  POST /api/v1/batch/{batch_id}/recover    任務缺少金鑰或只帶遮罩值時改用資料庫的金鑰

漏洞重現：設定 API 的 GET 原本回傳明文 api_keys，前端把它存進 localStorage、
每個任務再經 WebSocket 送回後端；任何能讀到回應的頁面都拿得到金鑰。

明文金鑰只在設定頁存檔時送進來：任務、批次恢復與 Test Connection 的請求帶明文就拒收，
錯誤訊息與 log 都不帶那把金鑰（#16 Q8b）。
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import batch, transcription
from app.database.models import BatchFile, BatchJob, ModelConfiguration
from app.provider import registry
from app.provider.base import ProviderInfo
from tests.support.fake_provider import FAKE_MODEL, FakeProvider
from tests.support.task_api import receive

REAL_KEY = "AIzaSyTEST-0123456789-abcdefghij-WXYZ"
REAL_KEY_MASKED = "AIza********WXYZ"
SECOND_KEY = "AIzaSyTEST-second-key-000000000-LMNO"
SECOND_KEY_MASKED = "AIza********LMNO"
SHORT_KEY = "short_key"  # 太短的金鑰整個遮掉，不露出前後碼


# ─── 共用 helper（stored_keys 在 tests/conftest.py）─────────────────────────

def _keys_in_db(db_session, provider: str) -> list[str]:
    db_session.expire_all()
    row = db_session.query(ModelConfiguration).filter_by(provider=provider).first()
    return json.loads(row.api_keys)


def _save(client: TestClient, provider: str, api_keys: list[str], **extra):
    response = client.post("/api/v1/setting/models", json={
        "provider": provider,
        "apiKeys": api_keys,
        "model": extra.pop("model", "gemini-2.5-flash"),
        **extra,
    })
    assert response.status_code == 200
    return response


# ─── GET：只回遮罩值 ─────────────────────────────────────────────────────────

class TestGetMasksKeys:
    def test_get_returns_masked_keys_only(self, client: TestClient, stored_keys):
        stored_keys("MaskGetProvider", [REAL_KEY, SHORT_KEY])

        response = client.get("/api/v1/setting/models/MaskGetProvider")

        assert response.status_code == 200
        assert response.json()["apiKeys"] == [REAL_KEY_MASKED, "********"]
        assert REAL_KEY not in response.text
        assert SHORT_KEY not in response.text


# ─── POST：遮罩值／空值保留原金鑰 ────────────────────────────────────────────

class TestSaveKeepsStoredKeys:
    PROVIDER = "MaskSaveProvider"

    def test_masked_keys_sent_back_keep_real_keys(self, client, db_session, stored_keys):
        stored_keys(self.PROVIDER, [REAL_KEY, SECOND_KEY])
        masked = client.get(f"/api/v1/setting/models/{self.PROVIDER}").json()["apiKeys"]

        _save(client, self.PROVIDER, masked, model="gemini-2.5-pro", prompt="new prompt")

        assert _keys_in_db(db_session, self.PROVIDER) == [REAL_KEY, SECOND_KEY]
        data = client.get(f"/api/v1/setting/models/{self.PROVIDER}").json()
        assert data["model"] == "gemini-2.5-pro"
        assert data["prompt"] == "new prompt"

    def test_blank_values_keep_real_keys(self, client, db_session, stored_keys):
        """前端沒有金鑰可送（例如只改 prompt）時送空字串，不能把金鑰清掉。"""
        stored_keys(self.PROVIDER, [REAL_KEY])
        _save(client, self.PROVIDER, [""])
        assert _keys_in_db(db_session, self.PROVIDER) == [REAL_KEY]

    def test_unmatched_mask_is_never_stored(self, client, db_session, stored_keys):
        stored_keys(self.PROVIDER, [REAL_KEY])
        _save(client, self.PROVIDER, ["AIza********0000"])
        assert _keys_in_db(db_session, self.PROVIDER) == [REAL_KEY]

    def test_new_key_is_added_next_to_masked_one(self, client, db_session, stored_keys):
        stored_keys(self.PROVIDER, [REAL_KEY])
        _save(client, self.PROVIDER, [REAL_KEY_MASKED, SECOND_KEY])
        assert _keys_in_db(db_session, self.PROVIDER) == [REAL_KEY, SECOND_KEY]

    def test_removing_one_masked_key_deletes_that_key(self, client, db_session, stored_keys):
        stored_keys(self.PROVIDER, [REAL_KEY, SECOND_KEY])
        _save(client, self.PROVIDER, [SECOND_KEY_MASKED])
        assert _keys_in_db(db_session, self.PROVIDER) == [SECOND_KEY]

    def test_replacing_key_with_new_value(self, client, db_session, stored_keys):
        stored_keys(self.PROVIDER, [REAL_KEY])
        _save(client, self.PROVIDER, [SECOND_KEY])
        assert _keys_in_db(db_session, self.PROVIDER) == [SECOND_KEY]

    def test_explicit_empty_list_clears_keys(self, client, db_session, stored_keys):
        """使用者把金鑰全部刪掉（前端過濾空白後送 []）仍然要能清除。"""
        stored_keys(self.PROVIDER, [REAL_KEY])
        _save(client, self.PROVIDER, [])
        assert _keys_in_db(db_session, self.PROVIDER) == []


# ─── Test Connection：後端自己拿金鑰 ─────────────────────────────────────────

class TestConnectionUsesStoredKey:
    """要金鑰的供應商（供應商清單的 requires_api_key）：交給供應商檢查的是資料庫裡的金鑰。"""
    PROVIDER = "KeyedFake"

    @pytest.fixture
    def keyed(self):
        """換上要 API 金鑰的假供應商，測試結束後拿掉。"""
        provider = FakeProvider()
        provider.info = ProviderInfo(label="要金鑰的假供應商", requires_api_key=True)
        previous = registry.register(self.PROVIDER, provider)
        yield provider
        registry.register(self.PROVIDER, previous)

    def _post_test(self, client, api_keys):
        return client.post("/api/v1/setting/test", json={
            "provider": self.PROVIDER,
            "apiKeys": api_keys,
            "model": FAKE_MODEL,
        })

    def test_masked_key_is_resolved_from_db(self, client, stored_keys, keyed):
        stored_keys(self.PROVIDER, [REAL_KEY])
        response = self._post_test(client, [REAL_KEY_MASKED])
        assert response.status_code == 200
        assert keyed.checked_keys == [REAL_KEY]

    def test_no_key_in_request_uses_db_key(self, client, stored_keys, keyed):
        stored_keys(self.PROVIDER, [REAL_KEY])
        response = self._post_test(client, [])
        assert response.status_code == 200
        assert keyed.checked_keys == [REAL_KEY]

    def test_no_key_anywhere_returns_400(self, client, keyed):
        response = self._post_test(client, [])
        assert response.status_code == 400
        assert keyed.checked_keys == []

    @pytest.mark.parametrize("api_keys", [[SECOND_KEY], [REAL_KEY_MASKED, SECOND_KEY]])
    def test_plain_key_is_refused(self, client, stored_keys, keyed, app_log, api_keys):
        """帶明文就拒收（#16 Q8b），不能默默改測資料庫裡的那把：測到的不是請求帶的金鑰。"""
        stored_keys(self.PROVIDER, [REAL_KEY])
        response = self._post_test(client, api_keys)
        assert response.status_code == 400
        assert "Settings" in response.json()["detail"]
        assert SECOND_KEY not in response.text
        assert keyed.checked_keys == []
        assert not any(SECOND_KEY in entry for entry in app_log)


# ─── 任務：缺少金鑰或只帶遮罩值時改用資料庫的金鑰 ───────────────────────────

@pytest.fixture
def task_env(tmp_path, monkeypatch, test_engine, in_process_run_mode):
    """WS 派發流程的測試環境：上傳目錄、測試資料庫、記錄派發參數。"""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "ok.mp3").write_bytes(b"audio")
    for module in (transcription, batch):
        monkeypatch.setattr(module, "TEMP_UPLOADS_DIR", uploads)
        monkeypatch.setattr(module, "SessionLocal",
                            sessionmaker(autocommit=False, autoflush=False, bind=test_engine))

    calls = []
    monkeypatch.setattr(in_process_run_mode, "submit_transcription",
                        lambda task_id, params, queue: calls.append(params))
    monkeypatch.setattr(in_process_run_mode, "submit_batch",
                        lambda params: calls.append(params) or "task-id")
    return calls


def _single_payload(**overrides) -> str:
    payload = {
        "filename": "ok.mp3",
        "original_filename": "ok.mp3",
        "provider": "Google",
        "model": "gemini-2.5-flash",
        "source_lang": "ja-JP",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _batch_payload(**overrides) -> str:
    payload = {
        "files": [{"filename": "ok.mp3", "original_filename": "ok.mp3", "file_uid": "uid-1"}],
        "provider": "Google",
        "model": "gemini-2.5-flash",
        "source_lang": "ja-JP",
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestTaskKeyResolution:
    @pytest.mark.parametrize("overrides", [
        {},                                  # 前端不再送 api_keys
        {"api_keys": ""},
        {"api_keys": REAL_KEY_MASKED},
    ])
    def test_single_task_uses_db_key(self, task_env, stored_keys, overrides):
        stored_keys("Google", [REAL_KEY])
        transcription.start_transcription_task_sync(_single_payload(**overrides), "uid-key")
        assert task_env[0]["api_keys"] == REAL_KEY

    def test_single_task_masked_value_picks_matching_key(self, task_env, stored_keys):
        stored_keys("Google", [REAL_KEY, SECOND_KEY])
        transcription.start_transcription_task_sync(
            _single_payload(api_keys=SECOND_KEY_MASKED), "uid-key")
        assert task_env[0]["api_keys"] == SECOND_KEY

    @pytest.mark.parametrize("overrides", [
        {},
        {"api_keys": ""},
        {"api_keys": REAL_KEY_MASKED},
    ])
    def test_batch_task_uses_db_key(self, task_env, stored_keys, overrides):
        stored_keys("Google", [REAL_KEY])
        batch.start_batch_task_sync(_batch_payload(**overrides), "batch-key")
        assert task_env[0]["api_keys"] == REAL_KEY


class TestPlainKeyRefused:
    """任務的請求帶明文金鑰就拒收（#16 Q8b）：不派發、刪掉上傳檔，錯誤訊息與 log 都不帶金鑰。
    設定頁存檔照常收明文（上面的 TestSaveKeepsStoredKeys）。"""

    def test_single_task(self, client, task_env, stored_keys, app_log, tmp_path):
        stored_keys("Google", [REAL_KEY])

        with client.websocket_connect("/api/v1/ws/uid-plain") as ws:
            ws.send_text(_single_payload(api_keys=SECOND_KEY))
            message = receive(ws)

        assert message["status_code"] == "FAILED"
        assert message["file_uid"] == "uid-plain"
        assert "Settings" in message["status_text"]
        assert SECOND_KEY not in json.dumps(message)
        assert task_env == []
        assert not (tmp_path / "uploads" / "ok.mp3").exists()
        assert not any(SECOND_KEY in entry for entry in app_log)

    def test_batch_task(self, client, task_env, stored_keys, app_log, tmp_path):
        stored_keys("Google", [REAL_KEY])

        with client.websocket_connect("/api/v1/batch/ws/batch-plain") as ws:
            ws.send_text(_batch_payload(api_keys=SECOND_KEY))
            message = receive(ws)

        assert message["status_code"] == "FAILED"
        assert message["file_uid"] == "uid-1"
        assert "Settings" in message["status_text"]
        assert SECOND_KEY not in json.dumps(message)
        assert task_env == []
        assert not (tmp_path / "uploads" / "ok.mp3").exists()
        assert not any(SECOND_KEY in entry for entry in app_log)


class TestRecoverUsesStoredKey:
    BATCH_ID = "batch-recover-key"

    @pytest.fixture
    def polling_job(self, db_session):
        """送出了、還在輪詢的批次，有一個送出的檔案。"""
        db_session.add(BatchJob(batch_id=self.BATCH_ID, gemini_job_name="batches/123",
                                status="POLLING"))
        db_session.flush()
        db_session.add(BatchFile(task_uuid=uuid.uuid4(), batch_id=self.BATCH_ID, seq=0,
                                 file_uid="recover-key.wav", original_filename="recover-key.wav",
                                 request_index=0, status="PROCESSING"))
        db_session.commit()
        yield
        db_session.query(BatchFile).filter_by(batch_id=self.BATCH_ID).delete()
        db_session.query(BatchJob).filter_by(batch_id=self.BATCH_ID).delete()
        db_session.commit()

    @pytest.fixture
    def recovered(self, monkeypatch, in_process_run_mode):
        calls = []
        monkeypatch.setattr(in_process_run_mode, "submit_recover",
                            lambda batch_id, api_key: calls.append((batch_id, api_key)) or "task-id")
        return calls

    @pytest.mark.parametrize("body", [{}, {"api_keys": REAL_KEY_MASKED}])
    def test_recover_without_plain_key_uses_db_key(
            self, client, stored_keys, polling_job, recovered, body):
        stored_keys("Google", [REAL_KEY])
        response = client.post(f"/api/v1/batch/{self.BATCH_ID}/recover", json=body)
        assert response.status_code == 200
        assert recovered == [(self.BATCH_ID, REAL_KEY)]

    def test_recover_with_plain_key_is_refused(
            self, client, stored_keys, polling_job, recovered, app_log):
        stored_keys("Google", [REAL_KEY])
        response = client.post(f"/api/v1/batch/{self.BATCH_ID}/recover",
                               json={"api_keys": SECOND_KEY})
        assert response.status_code == 400
        assert "Settings" in response.json()["detail"]
        assert SECOND_KEY not in response.text
        assert recovered == []
        assert not any(SECOND_KEY in entry for entry in app_log)

    def test_recover_without_any_key_explains_what_to_do(self, client, polling_job, recovered):
        response = client.post(f"/api/v1/batch/{self.BATCH_ID}/recover", json={})
        assert response.status_code == 400
        assert "Settings" in response.json()["detail"]
        assert recovered == []
