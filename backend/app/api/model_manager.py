import json
from fastapi import APIRouter, Body, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel

from app.models.model_manager_model import InterfaceConfigRequest, InterfaceConfigResponse, ModelConfigurationSchema
from app.db.repository.model_manager_repository import ModelSettingsRepository
from app.models.gemini import GeminiClient

router = APIRouter()


def get_repository() -> ModelSettingsRepository:
    return ModelSettingsRepository()


@router.post("/model_setting")
async def save_model_setting(
    config: InterfaceConfigRequest = Body(...),
    repo: ModelSettingsRepository = Depends(get_repository)
):
    print(
        f"收到模型設定請求:'{config.interfaceName}'")
    try:
        api_keys_json_str = json.dumps(config.apiKeys)
        config_to_save = ModelConfigurationSchema(
            interface_name=config.interfaceName,
            api_keys_json=api_keys_json_str,
            model_name=config.modelName,
            prompt=config.prompt
        )
        repo.save(config_to_save)
        return {
            "data_received": config.dict()
        }
    except Exception as e:
        message = f"保存模型設定時發生意外錯誤:'{config.interfaceName}'. Error: {e}"
        print(message)
        raise HTTPException(status_code=500, detail=message)


@router.get("/model_setting/{interface_name}", response_model=Optional[InterfaceConfigResponse])
async def get_model_setting(interface_name: str):
    repository = ModelSettingsRepository()

    try:
        db_schema_config = repository.get_by_name(interface_name)

        if db_schema_config:
            api_keys_list = []
            if db_schema_config.api_keys_json:
                try:
                    api_keys_list = json.loads(db_schema_config.api_keys_json)
                except json.JSONDecodeError as je:
                    print(
                        f"Error decoding api_keys_json for '{interface_name}': {je}. Returning with empty API keys.")

            return InterfaceConfigResponse(
                interfaceName=db_schema_config.interface_name,
                apiKeys=api_keys_list,
                modelName=db_schema_config.model_name,
                prompt=db_schema_config.prompt
            )
        else:
            return None
    except Exception as e:
        message = f"Failed to retrieve model setting for '{interface_name}' via Repository. Error: {e}"
        print(message)
        raise HTTPException(status_code=500, detail=message)


class TestInterfaceRequest(BaseModel):
    interfaceName: str
    apiKeys: List[str]


@router.post("/test_model_interface")
async def test_model_interface(
    request_data: TestInterfaceRequest = Body(...)
):
    print(
        f"收到測試接口請求: Interface Name - '{request_data.interfaceName}', API Keys count: {len(request_data.apiKeys)}")

    if not request_data.apiKeys:
        raise HTTPException(status_code=400, detail="未提供 API 金鑰進行測試。")

    # Gemini 通常使用單一 API Key。我們將使用列表中的第一個。
    api_key_to_test = request_data.apiKeys[0]

    # 預設用於測試的 Gemini 模型名稱
    # 未來可以考慮從已儲存的設定中讀取模型名稱，或讓 TestInterfaceRequest 包含 modelName
    model_to_test_with = "gemini-2.5-flash-preview-05-20"

    # 判斷是否測試 Gemini
    # 這裡使用簡單的名稱包含檢查，更穩健的方式可能是基於明確的類型欄位
    if "google" in request_data.interfaceName.lower() or \
       "gemini" in request_data.interfaceName.lower():

        if not api_key_to_test:  # 再次確認 (雖然前面已檢查列表非空)
            return {
                "message": f"測試 Gemini ('{request_data.interfaceName}'): 未提供 API 金鑰。",
                "status": "Failed",
                "details": "測試 Gemini 需要 API 金鑰。"
            }

        # 為了安全，只印出部分 API Key
        masked_api_key = f"{'*' * (len(api_key_to_test) - 4)}{api_key_to_test[-4:]}" if len(
            api_key_to_test) > 4 else "****"
        print(
            f"嘗試使用 API 金鑰 '{masked_api_key}' 測試 Gemini (模型: {model_to_test_with})...")

        try:
            gemini_tester = GeminiClient(api_key=api_key_to_test)
            test_result = gemini_tester.test_connection(
                model_name=model_to_test_with)
        except Exception as client_init_error:
            # 捕獲 GeminiClient 初始化時可能發生的 configure 錯誤
            print(f"GeminiClient 初始化失敗: {client_init_error}")
            return {
                "message": f"測試 Gemini ('{request_data.interfaceName}') 失敗：無法初始化客戶端。",
                "status": "Failed",
                "testedInterface": request_data.interfaceName,
                "modelUsed": model_to_test_with,
                "details": f"Gemini 客戶端初始化錯誤: {str(client_init_error)}"
            }

        if test_result["success"]:
            response_snippet = ""
            if test_result.get("response"):
                response_snippet = test_result["response"][:100] + \
                    ("..." if len(test_result["response"]) > 100 else "")

            return {
                "message": f"Gemini API ({request_data.interfaceName} 使用模型 '{model_to_test_with}') 測試成功。",
                "status": "Success",
                "testedInterface": request_data.interfaceName,
                "modelUsed": model_to_test_with,
                "details": test_result["message"],
                "response_snippet": response_snippet
            }
        else:
            return {
                "message": f"Gemini API ({request_data.interfaceName} 使用模型 '{model_to_test_with}') 測試失敗。",
                "status": "Failed",
                "testedInterface": request_data.interfaceName,
                "modelUsed": model_to_test_with,
                "details": test_result["message"]
            }

    # TODO: 在此處實現其他類型接口的測試邏輯，例如 OpenAI
    # elif "openai" in request_data.interfaceName.lower():
    #     # ... OpenAI 測試邏輯 ...
    #     pass

    else:
        # 對於尚未實現測試邏輯的接口類型
        return {
            "message": f"接口類型 '{request_data.interfaceName}' 的測試邏輯尚未實現。",
            "testedInterface": request_data.interfaceName,
            "status": "NotImplemented"
        }
