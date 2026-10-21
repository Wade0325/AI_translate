import json
from fastapi import APIRouter, Body, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from typing import Optional
from sqlalchemy.orm import Session

from app.schemas.schemas import ProviderConfigRequest, ProviderConfigResponse, ModelConfigurationSchema, ProviderTestRequest, ProviderTestResponse
from app.database.session import describe_db_error, get_db
from app.repositories.model_manager_repository import ModelSettingsRepository
from app.provider import registry
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
async def check_provider_ready(
    request_data: ProviderTestRequest = Body(...),
    db: Session = Depends(get_db),
):
    """設定頁的「測試」：確認現在能用這個供應商的這個模型轉錄。

    要不要 API 金鑰照供應商清單的 ``requires_api_key``；怎麼確認由供應商決定（本機查顯卡與
    模型權重，Gemini 用金鑰連一次 API），見 :func:`app.provider.registry.check_ready`。
    """
    logger.info(
        f"收到設定頁的測試請求: provider='{request_data.provider}', model='{request_data.model}', "
        f"API Keys count: {len(request_data.api_keys)}")
    try:
        api_key = ""
        if registry.requires_api_key(request_data.provider):
            # 前端送的是遮罩值（或不送）：從資料庫取回實際金鑰，用第一把測試
            api_keys = await run_in_threadpool(
                resolve_api_keys, db, request_data.provider, request_data.api_keys)
            if not api_keys:
                raise HTTPException(status_code=400, detail="未提供 API 金鑰進行測試。")
            api_key = api_keys[0]
        message = await run_in_threadpool(
            registry.check_ready, request_data.provider, request_data.model, api_key)
    except ValueError as e:
        # 供應商不存在、模型不屬於它，或還不能轉錄（缺顯卡、缺模型權重、金鑰無效）
        return ProviderTestResponse(success=False, message=str(e))
    return ProviderTestResponse(success=True, message=message)


@router.get("/default-prompt")
async def get_default_prompt():
    """回傳系統預設的 Prompt 模板與語言對照表"""
    from app.core.default_prompt import DEFAULT_PROMPT_TEMPLATE, LANG_MAP
    return {"template": DEFAULT_PROMPT_TEMPLATE, "lang_map": LANG_MAP}
