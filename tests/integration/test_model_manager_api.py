"""
整合測試：模型設定 API
測試範圍：
  POST /api/v1/setting/models
  GET  /api/v1/setting/models/{provider}
  POST /api/v1/setting/test
  GET  /api/v1/setting/default-prompt
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.provider import registry
from app.provider.local import weights
from app.services.api_keys import mask_api_key
from tests.support.fake_provider import FAKE_MODEL, FakeProvider


# ─── 儲存模型設定 ─────────────────────────────────────────────────────────────

class TestSaveModelSetting:
    def test_create_new_setting(self, client: TestClient):
        """建立新的模型設定應回傳 200 且 success=True"""
        payload = {
            "provider": "TestProviderCreate",
            "apiKeys": ["key1", "key2"],
            "model": "gemini-2.5-flash",
            "prompt": "Custom prompt",
        }
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_create_setting_without_prompt(self, client: TestClient):
        """不提供 prompt（選填）應成功"""
        payload = {
            "provider": "TestNoPrompt",
            "apiKeys": ["key1"],
            "model": "gemini-2.5-flash",
        }
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_create_setting_empty_api_keys(self, client: TestClient):
        """空的 apiKeys 列表應被接受"""
        payload = {
            "provider": "TestEmptyKeys",
            "apiKeys": [],
            "model": "gemini-2.5-flash",
        }
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_update_existing_setting(self, client: TestClient):
        """更新已存在的設定應覆蓋舊值"""
        provider = "TestUpdateProvider"
        client.post("/api/v1/setting/models", json={
            "provider": provider,
            "apiKeys": ["old_key"],
            "model": "old-model",
        })
        response = client.post("/api/v1/setting/models", json={
            "provider": provider,
            "apiKeys": ["new_key1", "new_key2"],
            "model": "new-model",
            "prompt": "New prompt",
        })
        assert response.status_code == 200

        get_resp = client.get(f"/api/v1/setting/models/{provider}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["model"] == "new-model"
        # GET 只回遮罩值（明文金鑰不離開後端）
        assert data["apiKeys"] == [mask_api_key("new_key1"), mask_api_key("new_key2")]
        assert data["prompt"] == "New prompt"

    def test_missing_provider_returns_422(self, client: TestClient):
        """缺少 provider 應回傳 422"""
        payload = {"apiKeys": ["key1"], "model": "model"}
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 422

    def test_missing_model_returns_422(self, client: TestClient):
        """缺少 model 應回傳 422"""
        payload = {"provider": "Google", "apiKeys": ["key1"]}
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 422

    def test_missing_api_keys_returns_422(self, client: TestClient):
        """缺少 apiKeys 應回傳 422"""
        payload = {"provider": "Google", "model": "model"}
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 422


# ─── 讀取模型設定 ─────────────────────────────────────────────────────────────

class TestGetModelSetting:
    def test_get_existing_setting(self, client: TestClient):
        """取得已存在的設定應回傳完整資料"""
        provider = "TestGetProvider"
        client.post("/api/v1/setting/models", json={
            "provider": provider,
            "apiKeys": ["my_key"],
            "model": "my-model",
            "prompt": "My prompt",
        })
        response = client.get(f"/api/v1/setting/models/{provider}")
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == provider
        assert data["apiKeys"] == [mask_api_key("my_key")]
        assert data["model"] == "my-model"
        assert data["prompt"] == "My prompt"

    def test_get_nonexistent_setting_returns_null(self, client: TestClient):
        """取得不存在的設定應回傳 200 和 null"""
        response = client.get("/api/v1/setting/models/NonExistentProvider99")
        assert response.status_code == 200
        assert response.json() is None

    def test_get_after_create_roundtrip(self, client: TestClient):
        """建立後立即取得，應回傳相同資料"""
        provider = "TestRoundtrip"
        payload = {
            "provider": provider,
            "apiKeys": ["rt_key"],
            "model": "rt-model",
            "prompt": "rt prompt",
        }
        client.post("/api/v1/setting/models", json=payload)
        resp = client.get(f"/api/v1/setting/models/{provider}")
        data = resp.json()
        assert data["provider"] == provider
        assert data["apiKeys"] == [mask_api_key("rt_key")]

    def test_api_keys_deserialized_as_list(self, client: TestClient):
        """API keys 應以 list 形式回傳（JSON deserialize 後）"""
        provider = "TestKeysList"
        client.post("/api/v1/setting/models", json={
            "provider": provider,
            "apiKeys": ["k1", "k2", "k3"],
            "model": "model",
        })
        resp = client.get(f"/api/v1/setting/models/{provider}")
        data = resp.json()
        assert isinstance(data["apiKeys"], list)
        assert len(data["apiKeys"]) == 3


# ─── 供應商名稱不分大小寫（#97） ──────────────────────────────────────────────

class TestProviderNameIgnoresCase:
    """設定存在「Google」「Local」底下（舊版前端與空資料庫的預設資料都這樣存）；畫面改用
    模型能力端點的「google」「local」之後，讀到、存回的仍是同一份設定。"""

    def test_settings_saved_under_one_spelling_are_read_under_another(self, client: TestClient):
        client.post("/api/v1/setting/models", json={
            "provider": "CaseReadProvider",
            "apiKeys": ["my_key"],
            "model": "my-model",
            "prompt": "My prompt",
        })

        data = client.get("/api/v1/setting/models/casereadprovider").json()

        assert (data["apiKeys"], data["model"], data["prompt"]) == (
            [mask_api_key("my_key")], "my-model", "My prompt")

    def test_saving_under_another_spelling_updates_the_same_settings(self, client: TestClient):
        key = "AIzaSyTEST-case-insensitive-000000-ABCD"
        client.post("/api/v1/setting/models", json={
            "provider": "CaseSaveProvider", "apiKeys": [key], "model": "old-model"})

        # 畫面送回的是遮罩值：要對得上原本那份設定裡的金鑰，不能被當成沒有金鑰
        client.post("/api/v1/setting/models", json={
            "provider": "casesaveprovider", "apiKeys": [mask_api_key(key)], "model": "new-model"})

        data = client.get("/api/v1/setting/models/CaseSaveProvider").json()
        assert data["model"] == "new-model"
        assert data["apiKeys"] == [mask_api_key(key)]


# ─── 測試 API 連線 ────────────────────────────────────────────────────────────

def press_test(client: TestClient, provider: str, model: str, api_keys=()):
    """按下設定頁的「測試」：apiKeys 是畫面上的金鑰（遮罩值），不用金鑰的供應商不帶。"""
    return client.post("/api/v1/setting/test", json={
        "provider": provider, "apiKeys": list(api_keys), "model": model})


@pytest.fixture
def fake():
    """換上不用 API 金鑰的假供應商「fake」，測試結束後拿掉。"""
    provider = FakeProvider()
    previous = registry.register("fake", provider)
    yield provider
    registry.register("fake", previous)


class TestCheckFollowsTheProviderList:
    """要不要金鑰照供應商清單的 requires_api_key，怎麼檢查交給供應商（#145）。"""

    def test_provider_without_api_key_is_tested_without_one(self, client: TestClient, fake):
        fake.ready_message = "顯卡與模型權重都在"

        response = press_test(client, "fake", FAKE_MODEL)

        assert response.status_code == 200
        assert response.json() == {"success": True, "message": "顯卡與模型權重都在"}

    def test_says_why_the_provider_cannot_transcribe_yet(self, client: TestClient, fake):
        fake.not_ready = ValueError("模型權重尚未下載")

        response = press_test(client, "fake", FAKE_MODEL)

        assert response.status_code == 200
        assert response.json() == {"success": False, "message": "模型權重尚未下載"}

    def test_model_must_belong_to_the_provider(self, client: TestClient, fake):
        # 檢查的是這個模型的權重之類，別的供應商的模型不能默默換成預設模型來檢查
        response = press_test(client, "fake", "moss-align")

        assert response.status_code == 200
        assert response.json() == {"success": False, "message": "模型 moss-align 不屬於供應商 fake"}


@pytest.fixture
def local_machine(monkeypatch):
    """免安裝模式的這台電腦：有沒有顯卡（gpu 是名稱，None 是沒有）、下載了哪些模型權重
    由測試決定；預設是有顯卡、預設模型的權重都已下載。"""
    machine = SimpleNamespace(
        gpu="Test GPU", downloaded={weights.MOSS_MODEL_ID, weights.ALIGNER_MODEL_ID})
    monkeypatch.setattr(get_settings(), "app_mode", "standalone")
    monkeypatch.setattr(weights, "cuda_status", lambda: (machine.gpu is not None, machine.gpu))
    monkeypatch.setattr(weights, "repo_is_ready", lambda repo: repo in machine.downloaded)
    return machine


class TestLocalTestChecksGpuAndWeights:
    """本機的「測試」：不必有金鑰，和轉錄前的檢查一樣查顯卡與所選模型的模型權重（#145）。"""

    def test_ready_names_the_gpu_and_the_model(self, client: TestClient, local_machine):
        response = press_test(client, "local", "moss-align")

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "本機已就緒：顯卡 Test GPU，MOSS-Transcribe-Diarize 的模型權重都已下載",
        }

    def test_names_the_weights_the_chosen_model_still_lacks(
            self, client: TestClient, local_machine):
        # 預設模型的權重都在，但「MOSS + Qwen3-ASR」另外要 Qwen3-ASR 的權重
        data = press_test(client, "local", "moss-qwen3-asr").json()

        assert data["success"] is False
        assert "Qwen/Qwen3-ASR-1.7B-hf" in data["message"]

    def test_not_ready_without_an_nvidia_gpu(self, client: TestClient, local_machine):
        local_machine.gpu = None

        data = press_test(client, "local", "moss-align").json()

        assert data["success"] is False
        assert "NVIDIA GPU" in data["message"]

    def test_docker_mode_says_it_cannot_check_the_gpu_worker(
            self, client: TestClient, local_machine, monkeypatch):
        # Docker 模式的本機轉錄在主機端的 GPU worker 執行：API 這一端的顯卡與權重不算數，
        # 不能說成可以轉錄，也不能說成沒有顯卡
        monkeypatch.setattr(get_settings(), "app_mode", "docker")

        data = press_test(client, "local", "moss-align").json()

        assert data["success"] is False
        assert "Docker 模式" in data["message"]


class TestProviderConnectionTest:
    def test_test_google_provider_success(self, client: TestClient):
        """Gemini API 測試成功時應回傳 success=True"""
        mock_status = MagicMock()
        mock_status.success = True
        mock_status.message = "連線成功"
        with patch("app.provider.google.provider.GeminiClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.test_connection.return_value = mock_status
            mock_client_cls.return_value = mock_client

            response = client.post("/api/v1/setting/test", json={
                "provider": "google",
                "apiKeys": ["fake_api_key"],
                "model": "gemini-2.5-flash",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_client_cls.assert_called_once_with(api_key="fake_api_key")

    def test_test_google_provider_failure(self, client: TestClient):
        """Gemini API 測試失敗時應回傳 success=False"""
        mock_status = MagicMock()
        mock_status.success = False
        mock_status.message = "無效的 API 金鑰"
        with patch("app.provider.google.provider.GeminiClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.test_connection.return_value = mock_status
            mock_client_cls.return_value = mock_client

            response = client.post("/api/v1/setting/test", json={
                "provider": "google",
                "apiKeys": ["invalid_key"],
                "model": "gemini-2.5-flash",
            })
        assert response.status_code == 200
        assert response.json() == {"success": False, "message": "無效的 API 金鑰"}

    def test_test_without_api_keys_returns_400(self, client: TestClient):
        """未提供 API keys 應回傳 400"""
        response = client.post("/api/v1/setting/test", json={
            "provider": "google",
            "apiKeys": [],
            "model": "gemini-2.5-flash",
        })
        assert response.status_code == 400

    def test_provider_not_on_the_provider_list_is_unsupported(self, client: TestClient):
        # 供應商照供應商清單（registry）找，不再依名稱分支（#145）
        response = press_test(client, "openai", "gpt-4", ["sk-key"])

        assert response.status_code == 200
        assert response.json() == {"success": False, "message": "不支援的供應商：openai"}


# ─── 預設 Prompt ──────────────────────────────────────────────────────────────

class TestDefaultPromptEndpoint:
    def test_get_default_prompt_returns_template(self, client: TestClient):
        """應回傳包含 template 和 lang_map 的 JSON"""
        response = client.get("/api/v1/setting/default-prompt")
        assert response.status_code == 200
        data = response.json()
        assert "template" in data
        assert "lang_map" in data

    def test_template_is_nonempty_string(self, client: TestClient):
        response = client.get("/api/v1/setting/default-prompt")
        data = response.json()
        assert isinstance(data["template"], str)
        assert len(data["template"]) > 0

    def test_lang_map_contains_japanese(self, client: TestClient):
        response = client.get("/api/v1/setting/default-prompt")
        data = response.json()
        assert "ja-JP" in data["lang_map"]

    def test_template_contains_lrc(self, client: TestClient):
        response = client.get("/api/v1/setting/default-prompt")
        data = response.json()
        assert "LRC" in data["template"]
