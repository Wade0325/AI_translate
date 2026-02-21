from pathlib import Path

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool

from app.celery.batch_task import batch_transcribe_task
from app.celery.models import BatchTranscriptionTaskParams, BatchFileItemParams
from app.core.config import get_settings
from app.utils.logger import setup_logger
from app.websocket.manager import manager
from app.schemas.schemas import WebSocketBatchRequest

logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = Path(settings.temp_uploads_dir)
TEMP_UPLOADS_DIR.mkdir(exist_ok=True)


def start_batch_celery_task(payload_str: str, batch_id: str) -> None:
    """
    同步函式：解析批次請求並啟動 Celery 批次轉錄任務。
    在獨立執行緒中執行以避免阻塞事件迴圈。
    """
    request_data = WebSocketBatchRequest.model_validate_json(payload_str)

    file_items = []
    for f in request_data.files:
        temp_file_path = TEMP_UPLOADS_DIR / f.filename
        if not temp_file_path.is_file():
            logger.error(f"批次任務檔案不存在: {f.filename}")
            continue

        file_items.append(BatchFileItemParams(
            file_path=str(temp_file_path),
            original_filename=f.original_filename,
            file_uid=f.file_uid,
        ))

    if not file_items:
        logger.error(f"批次任務 {batch_id} 沒有有效的檔案，取消任務")
        return

    task_params = BatchTranscriptionTaskParams(
        files=file_items,
        provider=request_data.provider,
        model=request_data.model,
        api_keys=request_data.api_keys,
        source_lang=request_data.source_lang,
        target_lang=request_data.target_lang,
        prompt=request_data.prompt,
        client_id=batch_id,
        batch_id=batch_id,
    )

    batch_transcribe_task.delay(task_params.model_dump())
    logger.info(f"已為 batch_id: {batch_id} 啟動 Celery 批次轉錄任務 ({len(file_items)} 個檔案)。")


@router.websocket("/ws/{batch_id}", name="WebSocket Batch Transcription")
async def batch_websocket_endpoint(
    websocket: WebSocket,
    batch_id: str,
):
    """
    批次轉錄的 WebSocket 端點。

    前端透過此端點提交批次轉錄請求，並接收所有檔案的即時進度更新。
    使用 Gemini Batch API，費用為標準 API 的 50%。

    通訊協定：
    - 連線後發送 JSON 格式的 WebSocketBatchRequest
    - 接收個別檔案的 PROCESSING / COMPLETED / FAILED 狀態
    - 接收整體批次的 BATCH_COMPLETED 狀態
    """
    await manager.connect(websocket, batch_id)
    try:
        payload_str = await websocket.receive_text()

        await run_in_threadpool(
            start_batch_celery_task, payload_str=payload_str, batch_id=batch_id
        )

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"批次 WebSocket 連線由客戶端關閉: {batch_id}")
        manager.disconnect(batch_id)
    except Exception as e:
        logger.error(
            f"批次 WebSocket 端點發生錯誤 (batch_id: {batch_id}): {e}",
            exc_info=True,
        )
        if batch_id in manager.active_connections:
            await manager.active_connections[batch_id].close()
            manager.disconnect(batch_id)
