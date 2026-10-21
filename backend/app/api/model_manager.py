import json
from fastapi import APIRouter, Body, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import status

from app.schemas.schemas import ProviderConfigRequest, ProviderConfigResponse, ModelConfigurationSchema, ServiceStatus, ProviderTestRequest, ProviderTestResponse
from app.database.session import describe_db_error, get_db
from app.repositories.model_manager_repository import ModelSettingsRepository
from app.provider.google.gemini import GeminiClient
from app.services.api_keys import (
    mask_api_key,
    merge_api_keys,
    parse_stored_api_keys,
    resolve_api_keys,
)
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
        # 前端拿到的是遮罩值：送回遮罩值或空值時保留資料庫中原有的金鑰
        existing = await run_in_threadpool(repo.get_by_name, db, config.provider)
        stored_keys = parse_stored_api_keys(existing.api_keys) if existing else []
        api_keys = json.dumps(merge_api_keys(config.api_keys, stored_keys),
                              ensure_ascii=False)
        config_to_save = ModelConfigurationSchema(
            provider=config.provider,
            api_keys=api_keys,
            model=config.model,
            prompt=config.prompt
        )
        await run_in_threadpool(repo.save, db, config_to_save)
        return {"success": True}
    except Exception as e:
        logger.error(f"保存模型設定失敗 (provider={config.provider!r}): {describe_db_error(e)}")
        raise HTTPException(
            status_code=500, detail="設定沒有存進資料庫，請再試一次；一直失敗的話請回報問題。") from e


@router.get("/models/{provider}", response_model=Optional[ProviderConfigResponse])
async def get_model_setting(
    provider: str,
    db: Session = Depends(get_db),
    repo: ModelSettingsRepository = Depends(get_repository)
):
    try:
        db_orm_config = await run_in_threadpool(repo.get_by_name, db, provider)

        if db_orm_config:
            # 只回遮罩值：明文金鑰不離開後端
            api_keys_list = [mask_api_key(k)
                             for k in parse_stored_api_keys(db_orm_config.api_keys)]

            return ProviderConfigResponse(
                provider=db_orm_config.provider,
                api_keys=api_keys_list,
                model=db_orm_config.model,
                prompt=db_orm_config.prompt
            )
        else:
            return None
    except Exception as e:
        logger.error(f"讀取模型設定失敗 (provider={provider!r}): {describe_db_error(e)}")
        raise HTTPException(
            status_code=500, detail="讀不到資料庫裡的設定，請再試一次；一直失敗的話請回報問題。") from e


@router.post("/test", response_model=ProviderTestResponse)
async def test_model_interface(
    request_data: ProviderTestRequest = Body(...),
    db: Session = Depends(get_db),
):
    logger.info(
        f"收到測試API請求: Interface Name - '{request_data.provider}', API Keys count: {len(request_data.api_keys)}")
    if request_data.provider.lower() == "local":
        return ProviderTestResponse(
            success=True,
            message="本地模型（VibeVoice + Qwen3-ASR）無需連線測試。",
        )
    # 前端送的是遮罩值（或不送）：從資料庫取回實際金鑰
    api_keys = await run_in_threadpool(
        resolve_api_keys, db, request_data.provider, request_data.api_keys)
    if not api_keys:
        raise HTTPException(status_code=400, detail="未提供 API 金鑰進行測試。")

    # Gemini 通常使用單一 API Key。我們將使用列表中的第一個。
    api_key_to_test = api_keys[0]

    if "google" in request_data.provider.lower():
        try:
            gemini_client = GeminiClient(api_key=api_key_to_test)
            test_result: ServiceStatus = await run_in_threadpool(gemini_client.test_connection)

            if test_result.success:
                return ProviderTestResponse(
                    success=True,
                    message="Gemini API (Google) 測試成功。",
                )
            else:
                return ProviderTestResponse(
                    success=False,
                    message=test_result.message or "測試失敗，但未提供具體原因。",
                )

        except Exception as e:
            # 捕捉在創建 client 或測試過程中的其他意外錯誤
            logger.error(f"測試 Gemini 時發生意外錯誤。Error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "message": "測試 Gemini 時發生伺服器內部錯誤。",
                    "details": str(e),
                }
            ) from e

    else:
        return ProviderTestResponse(
            success=False,
            message=f"API類型 '{request_data.provider}' 的測試邏輯尚未實現。",
        )


@router.get("/default-prompt")
async def get_default_prompt():
    """回傳系統預設的 Prompt 模板與語言對照表"""
    from app.core.default_prompt import DEFAULT_PROMPT_TEMPLATE, LANG_MAP
    return {"template": DEFAULT_PROMPT_TEMPLATE, "lang_map": LANG_MAP}
