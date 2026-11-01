import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.utils.logger import setup_logger
from app.utils.paths import resolve_upload_path

logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = settings.temp_uploads_path

SUPPORTED_MIME_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp3",
    "audio/flac", "audio/opus", "audio/m4a", "audio/x-m4a", "audio/mp4",
    "audio/aac", "audio/webm", "video/mp4", "video/mpeg", "video/webm",
    "video/quicktime", "video/x-flv", "video/x-ms-wmv", "video/3gpp",
}


_PLAIN_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,10}")


def stored_name(filename: str) -> str:
    """上傳檔在暫存區的名稱：隨機名稱加上原本的副檔名（#231 Q5）。

    原檔名常有人名、會議名稱，只留在請求與任務紀錄裡：暫存檔、轉成的 wav、切出的段、log，以及送到
    Gemini 的檔案名稱，都由這個隨機名稱衍生。副檔名照留（ffmpeg 與 MIME 類型要靠它），但只收英數字。
    """
    suffix = Path(filename).suffix
    return uuid.uuid4().hex + (suffix if _PLAIN_SUFFIX.fullmatch(suffix) else "")


@router.post("/upload", tags=["Upload"])
async def upload_file(
    file: UploadFile = File(..., description="要上傳的檔案")
):
    """
    上傳檔案到臨時目錄，供後續處理使用
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="檔案沒有檔名，請重新選擇檔案")

    if file.content_type not in SUPPORTED_MIME_TYPES:
        # 訊息會顯示在轉錄頁的檔案卡上（錯誤碼 UPLOAD_FAILED 的細節）
        raise HTTPException(
            status_code=400,
            detail=f"不支援這種檔案格式（{file.content_type or '瀏覽器沒有告知類型'}），"
                   "請改用常見的音訊或影片格式，例如 MP3、WAV、M4A、MP4",
        )

    TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    temp_file_path = resolve_upload_path(stored_name(Path(file.filename).name), TEMP_UPLOADS_DIR)

    def _write_to_disk(src, dst: Path) -> int:
        # "x"：隨機名稱不會撞名；萬一撞了寧可失敗，也不蓋掉別的上傳檔
        with dst.open("xb") as buffer:
            shutil.copyfileobj(src, buffer)
        return dst.stat().st_size

    try:
        size = await run_in_threadpool(_write_to_disk, file.file, temp_file_path)

        if size == 0:
            temp_file_path.unlink()
            raise HTTPException(status_code=400, detail="檔案是空的（0 位元組），請確認檔案沒有損壞")

        saved_filename = temp_file_path.name
        logger.info(f"臨時檔案已保存: {temp_file_path}")

        return {"filename": saved_filename}

    except HTTPException:
        raise
    except Exception as e:
        # 例外的文字可能帶著使用者電腦上的路徑：原因只記在 log，回應給固定訊息
        logger.error(f"保存檔案失敗: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500,
            detail="檔案沒有存進電腦，請確認磁碟空間足夠後再上傳一次；一直失敗的話請回報問題。",
        ) from e
    finally:
        await file.close()
