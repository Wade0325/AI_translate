"""
整合測試：模型設定 API
測試範圍：
  POST /api/v1/setting/models
  GET  /api/v1/setting/models/{provider}
  POST /api/v1/setting/test
  GET  /api/v1/setting/default-prompt
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ─── 儲存模型設定 ─────────────────────────────────────────────────────────────

class TestSaveModelSetting:
    def test_create_new_setting(self, client: TestClient):
        """建立新的模型設定應回傳 200 及 data_received"""
        payload = {
            "provider": "TestProviderCreate",
            "apiKeys": ["key1", "key2"],
            "model": "gemini-2.5-flash",
            "prompt": "Custom prompt",
        }
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "data_received" in data
        assert data["data_received"]["provider"] == "TestProviderCreate"
        assert data["data_received"]["apiKeys"] == ["key1", "key2"]

    def test_create_setting_without_prompt(self, client: TestClient):
        """不提供 prompt（選填）應成功"""
        payload = {
            "provider": "TestNoPrompt",
            "apiKeys": ["key1"],
            "model": "gemini-2.5-flash",
        }
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["data_received"]["prompt"] is None

    def test_create_setting_empty_api_keys(self, client: TestClient):
        """空的 apiKeys 列表應被接受"""
        payload = {
            "provider": "TestEmptyKeys",
            "apiKeys": [],
            "model": "gemini-2.5-flash",
        }
        response = client.post("/api/v1/setting/models", json=payload)
        assert response.status_code == 200
        assert response.json()["data_received"]["apiKeys"] == []

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
        assert data["apiKeys"] == ["new_key1", "new_key2"]
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
        assert data["apiKeys"] == ["my_key"]
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
        assert data["apiKeys"] == ["rt_key"]

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


# ─── 測試 API 連線 ────────────────────────────────────────────────────────────

class TestProviderConnectionTest:
    def test_test_google_provider_success(self, client: TestClient):
        """Gemini API 測試成功時應回傳 success=True"""
        mock_status = MagicMock()
        mock_status.success = True
        mock_status.message = "連線成功"
        with patch("app.api.model_manager.GeminiClient") as mock_client_cls:
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

    def test_test_google_provider_failure(self, client: TestClient):
        """Gemini API 測試失敗時應回傳 success=False"""
        mock_status = MagicMock()
        mock_status.success = False
        mock_status.message = "無效的 API 金鑰"
        with patch("app.api.model_manager.GeminiClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.test_connection.return_value = mock_status
            mock_client_cls.return_value = mock_client

            response = client.post("/api/v1/setting/test", json={
                "provider": "google",
                "apiKeys": ["invalid_key"],
                "model": "gemini-2.5-flash",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_test_without_api_keys_returns_400(self, client: TestClient):
        """未提供 API keys 應回傳 400"""
        response = client.post("/api/v1/setting/test", json={
            "provider": "google",
            "apiKeys": [],
            "model": "gemini-2.5-flash",
        })
        assert response.status_code == 400

    def test_test_unimplemented_provider_returns_not_implemented(self, client: TestClient):
        """尚未實作的 provider 應回傳 success=False 且包含 NotImplemented 訊息"""
        response = client.post("/api/v1/setting/test", json={
            "provider": "openai",
            "apiKeys": ["sk-key"],
            "model": "gpt-4",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "NotImplemented" in data.get("details", "") or "尚未實現" in data.get("message", "")


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
