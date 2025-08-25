import os
from pathlib import Path
from typing import Optional, List, Dict

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect
)
from fastapi.concurrency import run_in_threadpool

from app.celery.task import transcribe_media_task
from app.celery.models import TranscriptionTaskParams
from app.utils.logger import setup_logger
from app.websocket.manager import manager
from app.schemas.schemas import WebSocketTranscriptionRequest


logger = setup_logger(__name__)

router = APIRouter()

# 從環境變數或預設值取得上傳目錄
TEMP_UPLOADS_DIR = Path(os.getenv("TEMP_UPLOADS_DIR", "temp_uploads"))
TEMP_UPLOADS_DIR.mkdir(exist_ok=True)


def start_celery_task_sync(payload_str: str, file_uid: str) -> None:
    """
    一個同步函式，封裝了所有準備和啟動 Celery 任務的邏輯。
    這個函式將在獨立的執行緒中執行，以避免阻塞事件迴圈。
    """
    request_data = WebSocketTranscriptionRequest.model_validate_json(
        payload_str)

    temp_file_path = TEMP_UPLOADS_DIR / request_data.filename

    if temp_file_path.is_file():
        server_file_path = str(temp_file_path)
    else:
        logger.error(f"檔案不存在: {request_data.filename}")
        return

    task_params = TranscriptionTaskParams(
        file_path=server_file_path,
        provider=request_data.provider,
        model=request_data.model,
        api_keys=request_data.api_keys,
        source_lang=request_data.source_lang,
        target_lang=request_data.target_lang,  # 新增: 傳遞目標語言
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
