import json
from fastapi import APIRouter, Body, HTTPException, Depends
from typing import Optional, List
from sqlalchemy.orm import Session
from fastapi import status

from app.schemas.schemas import ProviderConfigRequest, ProviderConfigResponse, ModelConfigurationSchema, ServiceStatus, TestProviderRequest, TestProviderResponse
from app.database.session import get_db
from app.repositories.model_manager_repository import ModelSettingsRepository
from app.provider.google.gemini import GeminiClient
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter()


def get_repository() -> ModelSettingsRepository:
    return ModelSettingsRepository()


@router.post("/models")
async def save_model_setting(
    config: ProviderConfigRequest = Body(...),
    db: Session = Depends(get_db),
    repo: ModelSettingsRepository = Depends(get_repository)
):
    logger.info(f"收到模型設定請求:'{config.provider}'")
    try:
        api_keys = json.dumps(config.api_keys, ensure_ascii=False)
        config_to_save = ModelConfigurationSchema(
            provider=config.provider,
            api_keys=api_keys,
            model=config.model,
            prompt=config.prompt
        )
        repo.save(db, config_to_save)
        return {
            "data_received": config.model_dump(by_alias=True)
        }
    except Exception as e:
        message = f"保存模型設定時發生意外錯誤:'{config.provider}'. Error: {e}"
        logger.error(message)
        raise HTTPException(status_code=500, detail=message)


@router.get("/models/{provider}", response_model=Optional[ProviderConfigResponse])
async def get_model_setting(
    provider: str,
    db: Session = Depends(get_db),
    repo: ModelSettingsRepository = Depends(get_repository)
):
    try:
        db_orm_config = repo.get_by_name(db, provider)

        if db_orm_config:
            api_keys_list = []
            if db_orm_config.api_keys:
                try:
                    api_keys_list = json.loads(db_orm_config.api_keys)
                except json.JSONDecodeError as je:
                    logger.warning(
                        f"Error decoding provider for '{provider}': {je}. Returning with empty API keys.")

            return ProviderConfigResponse(
                provider=db_orm_config.provider,
                api_keys=api_keys_list,
                model=db_orm_config.model,
                prompt=db_orm_config.prompt
            )
        else:
            return None
    except Exception as e:
        message = f"Failed to retrieve model setting for '{provider}'. Error: {e}"
        logger.error(message)
        raise HTTPException(status_code=500, detail=message)


@router.post("/test", response_model=TestProviderResponse)
async def test_model_interface(
    request_data: TestProviderRequest = Body(...)
):
    logger.info(
        f"收到測試API請求: Interface Name - '{request_data.provider}', API Keys count: {len(request_data.api_keys)}")
    if not request_data.api_keys:
        raise HTTPException(status_code=400, detail="未提供 API 金鑰進行測試。")

    # Gemini 通常使用單一 API Key。我們將使用列表中的第一個。
    api_key_to_test = request_data.api_keys[0]

    # 判斷是否測試 Gemini
    if "google" in request_data.provider.lower():
        try:
            gemini_client = GeminiClient(api_key=api_key_to_test)
            test_result: ServiceStatus = gemini_client.test_connection()

            # 將後端 Client 的測試結果封裝成 API 回應
            if test_result.success:
                return TestProviderResponse(
                    success=True,
                    message="Gemini API (Google) 測試成功。",
                    details=test_result.message,
                    testedInterface=request_data.provider
                )
            else:
                return TestProviderResponse(
                    success=False,
                    message=test_result.message or "測試失敗，但未提供具體原因。",
                    details="",  # 保持為空，前端只顯示 message
                    testedInterface=request_data.provider
                )

        except Exception as e:
            # 捕捉在創建 client 或測試過程中的其他意外錯誤
            logger.error(f"測試 Gemini 時發生意外錯誤。Error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "status": "Error",
                    "message": "測試 Gemini 時發生伺服器內部錯誤。",
                    "details": str(e),
                    "testedInterface": request_data.provider
                }
            )

    # TODO: 在此處實現其他類型API的測試邏輯，例如 OpenAI
    # elif "openai" in request_data.provider.lower():
    #     # ... OpenAI 測試邏輯 ...
    #     pass

    else:
        return {
            "message": f"API類型 '{request_data.provider}' 的測試邏輯尚未實現。",
            "testedInterface": request_data.provider,
            "status": "NotImplemented"
        }
