import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()

# 取得集中管理的設定
settings = get_settings()
TEMP_UPLOADS_DIR = Path(settings.temp_uploads_dir)

SUPPORTED_MIME_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp3",
    "audio/flac", "audio/opus", "audio/m4a", "audio/x-m4a", "audio/mp4",
    "audio/aac", "audio/webm", "video/mp4", "video/mpeg", "video/webm",
    "video/quicktime", "video/x-flv", "video/x-ms-wmv", "video/3gpp",
}


def _get_unique_filepath(directory: Path, filename: str) -> Path:
    """若檔名已存在，自動加上編號避免覆蓋，例如 file(1).mp3"""
    filepath = directory / filename
    if not filepath.exists():
        return filepath

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        new_name = f"{stem}({counter}){suffix}"
        filepath = directory / new_name
        if not filepath.exists():
            return filepath
        counter += 1


@router.post("/upload", tags=["Upload"])
async def upload_file(
    file: UploadFile = File(..., description="要上傳的檔案")
):
    """
    上傳檔案到臨時目錄，供後續處理使用
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    if file.content_type not in SUPPORTED_MIME_TYPES:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file format: {file.content_type}."
        )

    # 確保 temp_uploads 目錄存在
    TEMP_UPLOADS_DIR.mkdir(exist_ok=True)

    # 使用原始檔名，若有同名檔案則自動加編號
    original_filename = Path(file.filename).name
    temp_file_path = _get_unique_filepath(TEMP_UPLOADS_DIR, original_filename)

    try:
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        if temp_file_path.stat().st_size == 0:
            temp_file_path.unlink()
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        saved_filename = temp_file_path.name
        logger.info(f"臨時檔案已保存: {temp_file_path}")

        return {"filename": saved_filename, "message": "檔案上傳成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存檔案失敗: {e}")
        raise HTTPException(
            status_code=500, detail=f"Could not save file: {e}")
    finally:
        await file.close()
