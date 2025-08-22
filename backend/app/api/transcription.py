import shutil
import uuid
from pathlib import Path
import yt_dlp
from pydantic import BaseModel, HttpUrl
from typing import Optional

from celery.result import AsyncResult
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body

from app.celery.task import transcribe_media_task
from app.celery.models import TranscriptionTaskParams
from app.celery.celery import celery_app
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()

# 將檔案儲存目錄移至更永久的位置，因為 Celery worker 需要訪問它
# 我們可以考慮未來將其移至雲端儲存，如 S3
PERSISTENT_STORAGE_DIR = Path(
    __file__).resolve().parents[2] / "persistent_uploads"
PERSISTENT_STORAGE_DIR.mkdir(exist_ok=True)

SUPPORTED_MIME_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp3",
    "audio/flac", "audio/opus", "audio/m4a", "audio/x-m4a", "audio/mp4",
    "audio/aac", "audio/webm", "video/mp4", "video/mpeg", "video/webm",
    "video/quicktime", "video/x-flv", "video/x-ms-wmv", "video/3gpp",
}


class YouTubeTranscribeRequest(BaseModel):
    youtube_url: HttpUrl
    source_lang: str
    provider: str
    model: str
    api_keys: str
    client_id: str
    file_uid: str
    prompt: Optional[str] = None


class TaskCreationResponse(BaseModel):
    task_uuid: str
    message: str


@router.post("/transcribe",
             response_model=TaskCreationResponse,
             tags=["Transcription"])
async def transcribe_media(
    file: UploadFile = File(..., description="要轉錄的音訊或視訊檔案"),
    source_lang: str = Form(..., description="來源語言代碼 (例如：zh-TW)"),
    provider: str = Form(..., description="模型提供商 (例如：google)"),
    model: str = Form(..., description="使用的模型名稱"),
    api_keys: str = Form(..., description="API 金鑰"),
    client_id: str = Form(..., description="WebSocket 客戶端 ID"),
    file_uid: str = Form(..., description="前端檔案唯一 ID"),
    prompt: Optional[str] = Form(None, description="用於指導模型的提示詞"),
):
    """
    接收音訊或視訊檔案，提交至背景進行非同步轉錄。
    """
    logger.info(
        f"API received transcription request: filename='{file.filename}', lang='{source_lang}', model='{model}'")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    if file.content_type not in SUPPORTED_MIME_TYPES:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file format: {file.content_type}.")

    # 待轉錄的暫存音檔改名為uuid方便追蹤
    file_path = PERSISTENT_STORAGE_DIR / \
        f"{uuid.uuid4()}{Path(file.filename).suffix}"
    logger.info(f"Saving uploaded file to: {file_path}")

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"File saved successfully: {file_path}")
    except Exception as e:
        logger.error(f"Could not save file: {e}")
        raise HTTPException(
            status_code=500, detail=f"Could not save file: {e}")
    finally:
        await file.close()

    task_params = TranscriptionTaskParams(
        file_path=str(file_path),
        provider=provider,
        model=model,
        api_keys=api_keys,
        source_lang=source_lang,
        prompt=prompt,
        original_filename=file.filename,
        client_id=client_id,
        file_uid=file_uid
    )

    task = transcribe_media_task.delay(task_params.model_dump())
    logger.info(f"Transcription task submitted to Celery with ID: {task.id}")

    return {"task_uuid": task.id, "message": "Transcription task has been submitted."}


@router.post("/upload-temp", tags=["Transcription"])
async def upload_temp_file(
    file: UploadFile = File(..., description="要上傳的檔案")
):
    """
    上傳檔案到臨時目錄，供 WebSocket 處理使用
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    # 確保 temp_uploads 目錄存在
    temp_dir = Path("temp_uploads")
    temp_dir.mkdir(exist_ok=True)

    # 保持原始檔名
    temp_file_path = temp_dir / file.filename

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


@router.post("/youtube",
             response_model=TaskCreationResponse,
             tags=["Transcription"])
async def transcribe_youtube(
    request: YouTubeTranscribeRequest = Body(...),
):
    """
    接收 YouTube 連結，下載音訊並提交至背景進行非同步轉錄。
    """
    logger.info(
        f"Received YouTube transcription request: URL='{request.youtube_url}'")

    # 注意：yt-dlp 的下載是同步阻塞的。在生產環境中，
    # 也可以考慮將下載本身也做成一個前置的 Celery 任務。
    # 但為了簡化目前流程，我們先在 API 端同步下載。
    download_path_base = PERSISTENT_STORAGE_DIR / f"{uuid.uuid4()}"
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        'outtmpl': str(download_path_base),
        'quiet': True,
    }

    logger.info(f"Starting YouTube audio download: {request.youtube_url}")
    video_title = "youtube_video"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(
                str(request.youtube_url), download=True)
            video_title = info_dict.get(
                'title', 'youtube_video') if info_dict else 'youtube_video'
        logger.info(f"YouTube audio downloaded successfully: {video_title}")
    except Exception as e:
        logger.error(f"Error downloading YouTube audio: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error downloading YouTube audio: {e}")

    final_audio_path = download_path_base.with_suffix('.mp3')
    if not final_audio_path.exists():
        raise HTTPException(
            status_code=500, detail="Downloaded file not found.")

    task_params = TranscriptionTaskParams(
        file_path=str(final_audio_path),
        provider=request.provider,
        model=request.model,
        api_keys=request.api_keys,
        source_lang=request.source_lang,
        prompt=request.prompt,
        original_filename=video_title,
        client_id=request.client_id,
        file_uid=request.file_uid,
        # segments_for_remapping 可以在 Celery 任務內部，
        # 透過 VAD 處理後生成，這裡不再由 API 傳遞
    )

    task = transcribe_media_task.delay(task_params.model_dump())
    logger.info(
        f"YouTube transcription task submitted to Celery with ID: {task.id}")

    return {"task_uuid": task.id, "message": "YouTube transcription task has been submitted."}


@router.get("/status/{task_uuid}", tags=["Transcription"])
async def get_task_status(task_uuid: str):
    """
    根據 Celery 任務 ID 查詢轉錄任務的狀態和結果。
    """
    task_result = AsyncResult(task_uuid, app=celery_app)

    response = {
        "task_id": task_uuid,
        "status": task_result.status,
        "result": None
    }

    if task_result.successful():
        response["result"] = task_result.get()
    elif task_result.failed():
        # task_result.result 是一個 Exception 物件
        # 我們將其轉換為字串以方便在 JSON 中顯示
        response["result"] = str(task_result.result)

    return response
