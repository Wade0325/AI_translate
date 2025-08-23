import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()

TEMP_UPLOADS_DIR = Path("temp_uploads")

SUPPORTED_MIME_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp3",
    "audio/flac", "audio/opus", "audio/m4a", "audio/x-m4a", "audio/mp4",
    "audio/aac", "audio/webm", "video/mp4", "video/mpeg", "video/webm",
    "video/quicktime", "video/x-flv", "video/x-ms-wmv", "video/3gpp",
}


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

    # 保持原始檔名
    temp_file_path = TEMP_UPLOADS_DIR / file.filename

    try:
        # 保存檔案
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logger.info(f"臨時檔案已保存: {temp_file_path}")

        return {"filename": file.filename, "message": "檔案上傳成功"}

    except Exception as e:
        logger.error(f"保存檔案失敗: {e}")
        raise HTTPException(
            status_code=500, detail=f"Could not save file: {e}")
    finally:
        await file.close()
