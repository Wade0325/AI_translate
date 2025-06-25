from fastapi.testclient import TestClient  # 類型提示
from typing import Dict, Any

# client fixture 會從 conftest.py 自動注入


def test_create_model_setting(client: TestClient):
    """測試成功創建一個新的模型設定。"""
    payload = {
        "interfaceName": "TestCreate",
        "apiKeys": ["key1", "key2"],
        "modelName": "TestModelAlpha",
        "prompt": "Prompt for creating."
    }
    response = client.post("/settings/model_setting", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Model setting for 'TestCreate' saved/updated successfully via Repository."
    assert data["data_received"]["interfaceName"] == "TestCreate"
    assert data["data_received"]["apiKeys"] == ["key1", "key2"]

    # 額外驗證：嘗試獲取剛創建的設定
    get_response = client.get("/settings/model_setting/TestCreate")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["interfaceName"] == "TestCreate"
    assert get_data["modelName"] == "TestModelAlpha"
    assert get_data["prompt"] == "Prompt for creating."
    assert get_data["apiKeys"] == ["key1", "key2"]


def test_get_model_setting_exists(client: TestClient):
    """測試獲取一個已存在的模型設定。"""
    # 先創建一個設定
    interface_name = "TestGetExisting"
    payload = {
        "interfaceName": interface_name,
        "apiKeys": ["key_existing"],
        "modelName": "ModelExisting",
        "prompt": "Prompt for existing."
    }
    client.post("/settings/model_setting", json=payload)  # 忽略返回值，只關心它被創建

    response = client.get(f"/settings/model_setting/{interface_name}")
    assert response.status_code == 200
    data = response.json()
    assert data["interfaceName"] == interface_name
    assert data["modelName"] == "ModelExisting"
    assert data["apiKeys"] == ["key_existing"]
    assert data["prompt"] == "Prompt for existing."


def test_get_model_setting_not_exists(client: TestClient):
    """測試獲取一個不存在的模型設定。"""
    interface_name = "TestDoesNotExist"
    response = client.get(f"/settings/model_setting/{interface_name}")
    # 我們的 API 對於未找到的情況返回 200 和 null body (Pydantic Optional 會轉為 None)
    assert response.status_code == 200
    assert response.json() is None


def test_update_model_setting(client: TestClient):
    """測試更新一個已存在的模型設定。"""
    interface_name = "TestUpdate"
    initial_payload = {
        "interfaceName": interface_name,
        "apiKeys": ["initial_key"],
        "modelName": "InitialModel",
        "prompt": "Initial prompt."
    }
    client.post("/settings/model_setting", json=initial_payload)

    updated_payload = {
        "interfaceName": interface_name,  # 相同的 interfaceName
        "apiKeys": ["updated_key1", "updated_key2"],
        "modelName": "UpdatedModel",
        "prompt": "Updated prompt."
    }
    response = client.post("/settings/model_setting", json=updated_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == f"Model setting for '{interface_name}' saved/updated successfully via Repository."
    assert data["data_received"]["modelName"] == "UpdatedModel"

    # 驗證更新是否生效
    get_response = client.get(f"/settings/model_setting/{interface_name}")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["modelName"] == "UpdatedModel"
    assert get_data["apiKeys"] == ["updated_key1", "updated_key2"]
    assert get_data["prompt"] == "Updated prompt."


def test_create_model_setting_no_prompt(client: TestClient):
    """測試創建模型設定時不提供 prompt (因為它是可選的)。"""
    payload = {
        "interfaceName": "TestNoPrompt",
        "apiKeys": ["key_no_prompt"],
        "modelName": "ModelNoPrompt"
        # prompt 欄位被省略
    }
    response = client.post("/settings/model_setting", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["data_received"]["interfaceName"] == "TestNoPrompt"
    # Pydantic 預設 Optional 為 None
    assert data["data_received"]["prompt"] is None

    get_response = client.get("/settings/model_setting/TestNoPrompt")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["prompt"] is None


def test_create_model_setting_empty_apikeys(client: TestClient):
    """測試創建模型設定時提供空的 apiKeys 列表。"""
    payload: Dict[str, Any] = {
        "interfaceName": "TestEmptyKeys",
        "apiKeys": [],  # 空列表
        "modelName": "ModelEmptyKeys",
        "prompt": "Prompt for empty keys."
    }
    response = client.post("/settings/model_setting", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["data_received"]["apiKeys"] == []

    get_response = client.get("/settings/model_setting/TestEmptyKeys")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["apiKeys"] == []

# 注意：對於無效輸入（例如，缺少 interfaceName），FastAPI 會自動返回 422 Unprocessable Entity。
# 您也可以為這些情況編寫測試，但它們更多是測試 FastAPI 和 Pydantic 的行為。
# 例如：
# def test_create_model_setting_missing_interface_name(client: TestClient):
#     payload = {
#         # "interfaceName": "TestMissing", # 故意遺漏
#         "apiKeys": ["key1"],
#         "modelName": "TestModelMissing"
#     }
#     response = client.post("/settings/model_setting", json=payload)
#     assert response.status_code == 422 # Unprocessable Entity
