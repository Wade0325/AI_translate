from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.vad.test import run_vad_test
from app.utils.logger import setup_logger
from app.utils.paths import UnsafeUploadFilenameError, resolve_upload_path

logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = settings.temp_uploads_path


class VadTestRequest(BaseModel):
    """去靜音與切點預覽的請求（檔案需先上傳至 temp_uploads）。"""
    filename: str = Field(..., description="upload API 回傳的伺服器檔名")
    original_filename: str | None = Field(None, description="原始檔名（用於 artifact 目錄命名）")
    include_split: bool = Field(True, description="是否一併找切點（part1/part2）")


def _require_dev_tools() -> None:
    """預覽是開發者工具（#13 Q6）：沒開時不跑，使用者的資料夾不會留下預覽存的音檔。"""
    if not settings.dev_tools:
        raise HTTPException(
            status_code=404,
            detail="去靜音與切點預覽是開發者工具：在 .env 設定 DEV_TOOLS=true 並重新啟動後才能用")


@router.get("/enabled")
def vad_test_enabled():
    """轉錄頁要不要顯示去靜音與切點預覽的按鈕。"""
    return {"enabled": settings.dev_tools}


@router.post("/test", dependencies=[Depends(_require_dev_tools)])
async def vad_test(body: VadTestRequest):
    """
    只做去靜音與找切點的預覽，不轉錄。

    回傳語音佔比、有聲段的時間、切點，並將 wav 產物保存至 vad_artifacts/。
    """
    try:
        file_path = resolve_upload_path(body.filename, TEMP_UPLOADS_DIR)
    except UnsafeUploadFilenameError as e:
        logger.warning(f"去靜音與切點預覽拒絕不合法的上傳檔名: {body.filename!r}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"找不到檔案: {body.filename}")

    original_name = body.original_filename or body.filename
    # log 寫磁碟上的隨機名稱，不寫原檔名（#231 Q5）
    logger.info(f"去靜音與切點預覽開始: {body.filename}")

    result = await run_in_threadpool(
        run_vad_test,
        file_path,
        original_filename=original_name,
        include_split=body.include_split,
    )

    return result
