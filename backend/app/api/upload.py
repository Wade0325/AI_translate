import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.upload_formats import Rejected, check_upload, limits
from app.utils.audio import EXTRACTED_AUDIO_SUFFIX, AudioExtraction, extract_audio, has_video
from app.utils.logger import setup_logger
from app.utils.paths import resolve_upload_path

logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = settings.temp_uploads_path

# 影片抽不出音訊時給使用者看的原因（顯示在轉錄頁的檔案卡上）
_EXTRACTION_FAILED = {
    AudioExtraction.NO_AUDIO: "這個影片沒有聲音，沒有可以轉錄的內容",
    AudioExtraction.FAILED: "沒辦法從這個影片抽出聲音：檔案可能損壞，或用了不支援的編碼。"
                            "請確認影片能正常播放；一直失敗的話請回報問題",
}


_PLAIN_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,10}")


def stored_name(filename: str) -> str:
    """上傳檔在暫存區的名稱：隨機名稱加上原本的副檔名（#231 Q5）。

    原檔名常有人名、會議名稱，只留在請求與任務紀錄裡：暫存檔、轉成的 wav、切出的段、log，以及送到
    Gemini 的檔案名稱，都由這個隨機名稱衍生。副檔名照留（ffmpeg 與 MIME 類型要靠它），但只收英數字。
    """
    suffix = Path(filename).suffix
    return uuid.uuid4().hex + (suffix if _PLAIN_SUFFIX.fullmatch(suffix) else "")


@router.get("/upload/limits", tags=["Upload"])
def upload_limits():
    """轉錄頁收哪些格式、最大多大（app/core/upload_formats.py）；前端照這份清單檢查與說明。"""
    return limits()


@router.post("/upload", tags=["Upload"])
async def upload_file(
    file: UploadFile = File(..., description="要上傳的檔案")
):
    """
    上傳檔案到臨時目錄，供後續處理使用。

    收不收照 :func:`app.core.upload_formats.check_upload`（只看副檔名與大小）；不收時回 400，``detail``
    是給使用者看的原因。影片（以及副檔名是音檔、裡面卻有影像的檔案）在這裡就抽出音訊，回傳的是
    抽出的音訊（FLAC）的檔名，影片本身刪掉：之後的任務、保留音檔與供應商都只碰得到音訊（#258）。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="檔案沒有檔名，請重新選擇檔案")

    # 檔案已經整個收進 Starlette 的暫存檔，大小是收到的位元組數；畫面上傳前就照同一個上限擋了
    checked = check_upload(Path(file.filename).name, _received_size(file))
    if isinstance(checked, Rejected):
        raise HTTPException(status_code=400, detail=checked.reason)

    TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    temp_file_path = resolve_upload_path(stored_name(Path(file.filename).name), TEMP_UPLOADS_DIR)

    def _write_to_disk(src, dst: Path) -> None:
        # "x"：隨機名稱不會撞名；萬一撞了寧可失敗，也不蓋掉別的上傳檔
        with dst.open("xb") as buffer:
            shutil.copyfileobj(src, buffer)

    try:
        await run_in_threadpool(_write_to_disk, file.file, temp_file_path)
        logger.info(f"臨時檔案已保存: {temp_file_path}")
    except Exception as e:
        # 例外的文字可能帶著使用者電腦上的路徑：原因只記在 log，回應給固定訊息
        logger.error(f"保存檔案失敗: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500,
            detail="檔案沒有存進電腦，請確認磁碟空間足夠後再上傳一次；一直失敗的話請回報問題。",
        ) from e
    finally:
        await file.close()

    # 副檔名是音檔、裡面卻有影像（例如改了副檔名的 MP4）也抽：不能讓影片原檔送到供應商
    if checked.kind == "video" or await run_in_threadpool(has_video, temp_file_path):
        temp_file_path = await _audio_of(temp_file_path)
    return {"filename": temp_file_path.name}


def _received_size(file: UploadFile) -> int:
    """收到的位元組數：Starlette 解析上傳時記在 ``size``；沒記的話量暫存檔。"""
    if file.size is not None:
        return file.size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    return size


async def _audio_of(video: Path) -> Path:
    """從存好的影片抽出音訊，回傳音訊的路徑；影片不論成功與否都刪掉。抽不出來時回 400。"""
    audio = resolve_upload_path(stored_name(f"audio{EXTRACTED_AUDIO_SUFFIX}"), TEMP_UPLOADS_DIR)
    try:
        extraction = await run_in_threadpool(extract_audio, video, audio)
    finally:
        video.unlink(missing_ok=True)
    if extraction is not AudioExtraction.EXTRACTED:
        raise HTTPException(status_code=400, detail=_EXTRACTION_FAILED[extraction])
    return audio
