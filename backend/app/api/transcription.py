import uuid
from pathlib import Path
import yt_dlp
from pydantic import BaseModel, HttpUrl
from typing import Optional, Tuple

from celery.result import AsyncResult
from fastapi import (
    APIRouter, HTTPException, Body,
    WebSocket, WebSocketDisconnect
)
from fastapi.concurrency import run_in_threadpool

from app.celery.task import transcribe_media_task
from app.celery.models import TranscriptionTaskParams
from app.celery.celery import celery_app
from app.utils.logger import setup_logger
from app.websocket.manager import manager
from app.schemas.schemas import WebSocketTranscriptionRequest


logger = setup_logger(__name__)

router = APIRouter()

# 將檔案儲存目錄統一至 temp_uploads，方便管理
TEMP_UPLOADS_DIR = Path("temp_uploads")
TEMP_UPLOADS_DIR.mkdir(exist_ok=True)


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


def download_youtube_audio_sync(youtube_url: str, download_path_base: Path) -> Tuple[Path, str]:
    """
    一個同步函式，封裝了 yt-dlp 的下載邏輯。
    這個函式將在獨立的執行緒中執行，以避免阻塞事件迴圈。
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        'outtmpl': str(download_path_base),
        'quiet': True,
    }

    logger.info(f"在背景執行緒中開始下載 YouTube 音訊: {youtube_url}")
    video_title = "youtube_video"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(str(youtube_url), download=True)
        video_title = info_dict.get(
            'title', 'youtube_video') if info_dict else 'youtube_video'

    final_audio_path = download_path_base.with_suffix('.mp3')
    if not final_audio_path.exists():
        # 如果檔案不存在，拋出一個明確的錯誤
        raise FileNotFoundError("已下載的 YouTube 音訊檔案未找到。")

    logger.info(f"YouTube 音訊下載成功: {video_title}")
    return final_audio_path, video_title


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
        f"接收到 YouTube 轉錄請求: URL='{request.youtube_url}'")

    download_path_base = TEMP_UPLOADS_DIR / f"{uuid.uuid4()}"

    try:
        # 將阻塞的下載操作移至背景執行緒
        final_audio_path, video_title = await run_in_threadpool(
            download_youtube_audio_sync,
            youtube_url=str(request.youtube_url),
            download_path_base=download_path_base
        )
    except Exception as e:
        logger.error(f"下載 YouTube 音訊時發生錯誤: {e}")
        raise HTTPException(
            status_code=500, detail=f"下載 YouTube 音訊時發生錯誤: {e}")

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


def start_celery_task_sync(payload_str: str, file_uid: str) -> None:
    """
    一個同步函式，封裝了所有準備和啟動 Celery 任務的邏輯。
    這個函式將在獨立的執行緒中執行，以避免阻塞事件迴圈。
    """
    request_data = WebSocketTranscriptionRequest.model_validate_json(
        payload_str)

    file_path = TEMP_UPLOADS_DIR / request_data.filename

    if not file_path.is_file():
        logger.error(f"檔案不存在於 temp_uploads: {request_data.filename}")
        # 未來可考慮在此處透過 websocket 向客戶端發送錯誤訊息
        return

    server_file_path = str(file_path)

    task_params = TranscriptionTaskParams(
        file_path=server_file_path,
        provider=request_data.provider,
        model=request_data.model,
        api_keys=request_data.api_keys,
        source_lang=request_data.source_lang,
        original_filename=request_data.original_filename,
        client_id=file_uid,
        file_uid=file_uid,
        prompt=request_data.prompt,
        segments_for_remapping=request_data.segments_for_remapping
    )

    transcribe_media_task.delay(task_params.model_dump())
    logger.info(f"已為 file_uid: {file_uid} 啟動 Celery 轉錄任務。")


@router.websocket("/ws/{file_uid}", name="WebSocket Transcription")
async def websocket_endpoint(
    websocket: WebSocket,
    file_uid: str
):
    """
    為每個轉錄任務建立一個獨立的 WebSocket 連線，提供即時進度更新。
    """
    await manager.connect(websocket, file_uid)
    try:
        payload_str = await websocket.receive_text()

        await run_in_threadpool(start_celery_task_sync, payload_str=payload_str, file_uid=file_uid)

        # 保持連線開啟以接收來自客戶端的潛在訊息或 ping
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"WebSocket 連線由客戶端或伺服器關閉: {file_uid}")
        manager.disconnect(file_uid)
    except Exception as e:
        logger.error(
            f"WebSocket 端點發生錯誤 (file_uid: {file_uid}): {e}", exc_info=True)
        if file_uid in manager.active_connections:
            await manager.active_connections[file_uid].close()
            manager.disconnect(file_uid)


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
