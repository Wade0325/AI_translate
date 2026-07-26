from pathlib import Path

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect
)
from fastapi.concurrency import run_in_threadpool

from app.celery.cancellation import (
    clear_cancel_flag,
    get_task_id,
    register_task_id,
    request_cancel,
)
from app.celery.celery import celery_app
from app.celery.notifier import publish_status
from app.celery.task import transcribe_media_task
from app.celery.models import TranscriptionTaskParams
from app.core.config import get_settings
from app.database.session import SessionLocal
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.utils.logger import setup_logger
from app.websocket.manager import manager
from app.schemas.schemas import WebSocketTranscriptionRequest


logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = Path(settings.temp_uploads_dir)
TEMP_UPLOADS_DIR.mkdir(exist_ok=True)


def start_celery_task_sync(payload_str: str, file_uid: str) -> None:
    """解析 WS 請求並派發 Celery 任務；在 threadpool 執行以免阻塞事件迴圈。"""
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
        target_lang=request_data.target_lang,
        original_filename=request_data.original_filename,
        client_id=file_uid,
        file_uid=file_uid,
        prompt=request_data.prompt,
        multi_speaker=request_data.multi_speaker,
        service_tier=request_data.service_tier,
        session_id=request_data.session_id,
    )

    # local provider 路由到專用佇列，由主機端 GPU worker（local_worker.bat）消化
    queue = "local_asr" if task_params.provider.lower() == "local" else "celery"
    # 清掉上一次執行殘留的取消旗標（例如被 revoke 掉、沒機會自行清理的任務），
    # 否則同一檔案重跑會被誤取消
    clear_cancel_flag(file_uid)
    async_result = transcribe_media_task.apply_async(
        args=[task_params.model_dump()], queue=queue)
    register_task_id(file_uid, async_result.id)
    logger.info(f"已為 file_uid: {file_uid} 啟動 Celery 轉錄任務（queue={queue}）。")


@router.post("/transcription/{file_uid}/cancel", name="Cancel Transcription")
def cancel_transcription(file_uid: str, provider: str = ""):
    """取消單檔轉錄任務。

    - 佇列中：revoke 讓任務不會啟動（旗標另作保險，攔截廣播沒送達的情況）
    - local 執行中：solo pool 無法 terminate，GPU worker 靠合作式檢查點
      在數秒內自行中止並釋放模型
    - 其他 provider 執行中：gevent pool 支援 terminate，直接終止

    任務尚未派發（仍在上傳）時無事可取消，回報 not-started 讓前端稍後重試。
    """
    task_id = get_task_id(file_uid)
    if not task_id:
        return {"file_uid": file_uid, "cancelled": False, "reason": "not-started"}

    request_cancel(file_uid)
    # local worker 是 solo pool，不支援 terminate；送 terminate=True 會在
    # worker 端拋 NotImplementedError，因此僅對非 local 任務終止執行中行程
    terminate = provider.lower() != "local"
    celery_app.control.revoke(task_id, terminate=terminate)

    # 被 revoke/terminate 掉的任務不會再回報狀態：仍在 PROCESSING 的紀錄由此補寫。
    # local 執行中的任務會走 task.py 的 CANCELLED 分支自行更新，此處條件式更新不衝突。
    db = SessionLocal()
    try:
        TranscriptionLogRepository().mark_cancelled_if_processing(db, task_id)
    finally:
        db.close()

    publish_status(
        file_uid, task_id, "任務已取消",
        status_code="CANCELLED", file_uid=file_uid,
    )
    logger.info(f"已送出取消請求 file_uid={file_uid} task_id={task_id} "
                f"terminate={terminate}")
    return {"file_uid": file_uid, "cancelled": True}


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

        # 保持連線開啟以接收來自客戶端的訊息
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
