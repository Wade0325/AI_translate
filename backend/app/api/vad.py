from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.vad.test import run_vad_test
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = Path(settings.temp_uploads_dir)


class VadTestRequest(BaseModel):
    """VAD 切割測試請求（檔案需先上傳至 temp_uploads）。"""
    filename: str = Field(..., description="upload API 回傳的伺服器檔名")
    original_filename: str | None = Field(None, description="原始檔名（用於 artifact 目錄命名）")
    include_split: bool = Field(True, description="是否一併測試靜音分割（part1/part2）")


@router.post("/test")
async def vad_test(body: VadTestRequest):
    """
    僅執行 VAD 前處理測試，不呼叫 Gemini 轉錄。

    回傳語音佔比、片段時間戳、分割點，並將 wav 產物保存至 vad_artifacts/。
    """
    file_path = TEMP_UPLOADS_DIR / body.filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"找不到檔案: {body.filename}")

    original_name = body.original_filename or body.filename
    logger.info(f"VAD 測試開始: {original_name}")

    result = await run_in_threadpool(
        run_vad_test,
        file_path,
        original_filename=original_name,
        include_split=body.include_split,
    )

    return result
