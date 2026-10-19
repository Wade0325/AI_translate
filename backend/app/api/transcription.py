from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect
)
from fastapi.concurrency import run_in_threadpool

from app.celery.models import TranscriptionTaskParams
from app.runtime import run_mode
from app.runtime.run_mode import publish_status
from app.core.config import get_settings
from app.core.task_status import TaskStatus
from app.database.models import TranscriptionLog
from app.database.session import SessionLocal
from app.provider.registry import UnsupportedModelError, model_capabilities
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.services.api_keys import resolve_api_key
from app.utils.logger import setup_logger
from app.utils.paths import UnsafeUploadFilenameError, resolve_upload_path
from app.websocket.manager import manager
from app.schemas.schemas import WebSocketTranscriptionRequest


logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = settings.temp_uploads_path
TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def start_transcription_task_sync(payload_str: str, file_uid: str) -> None:
    """解析 WS 請求並派發轉錄任務；在 threadpool 執行以免阻塞事件迴圈。

    Raises:
        UnsafeUploadFilenameError: filename 不是 temp_uploads 內的單純檔名。
        UnsupportedModelError: 模型不屬於所選的供應商。
    """
    request_data = WebSocketTranscriptionRequest.model_validate_json(
        payload_str)

    # 先驗證再碰檔案：不符的組合不能默默跑到別的供應商
    capabilities = model_capabilities(request_data.provider, request_data.model)

    temp_file_path = resolve_upload_path(request_data.filename, TEMP_UPLOADS_DIR)

    if temp_file_path.is_file():
        server_file_path = str(temp_file_path)
    else:
        logger.error(f"檔案不存在: {request_data.filename}")
        return

    # 前端不再送明文金鑰：缺少或只帶遮罩值時改用資料庫裡的金鑰
    with SessionLocal() as db:
        api_key = resolve_api_key(db, request_data.provider, request_data.api_keys)

    task_params = TranscriptionTaskParams(
        file_path=server_file_path,
        provider=request_data.provider,
        model=request_data.model,
        api_keys=api_key,
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

    queue = capabilities.queue
    # 清掉上一次執行殘留的取消旗標（例如被 revoke 掉、沒機會自行清理的任務），
    # 否則同一檔案再開的任務會被誤取消
    mode = run_mode.get()
    mode.clear_cancel(file_uid)
    task_id = mode.submit_transcription(task_params.model_dump(), queue)
    mode.register_task(file_uid, task_id)
    logger.info(f"已為 file_uid: {file_uid} 啟動轉錄任務（queue={queue}）。")


@router.post("/transcription/{file_uid}/cancel", name="Cancel Transcription")
def cancel_transcription(file_uid: str):
    """取消單檔轉錄任務；供應商從任務紀錄查，不由前端告知。

    - 佇列中（紀錄還沒建立）：revoke 讓任務不會啟動（旗標另作保險，攔截廣播沒送達的情況）
    - 執行中：模型能力允許強制終止的直接終止；不允許的（例如本機的 GPU worker）
      靠合作式檢查點在數秒內自行中止並釋放模型

    任務尚未派發（仍在上傳）時無事可取消，回報 not-started 讓前端稍後重試。
    """
    mode = run_mode.get()
    task_id = mode.registered_task(file_uid)
    if not task_id:
        return {"file_uid": file_uid, "cancelled": False, "reason": "not-started"}

    mode.request_cancel(file_uid)
    log_repo = TranscriptionLogRepository()
    with SessionLocal() as db:
        mode.revoke(task_id, terminate=_can_terminate(log_repo.get(db, task_id)))
        # 被 revoke/terminate 掉的任務不會再回報狀態：仍在 PROCESSING 的紀錄由此補寫。
        # 合作式停止的任務由任務生命週期自行記為 CANCELLED，此處條件式更新不衝突。
        log_repo.mark_cancelled_if_processing(db, task_id)

    publish_status(
        file_uid, task_id, "任務已取消",
        status_code=TaskStatus.CANCELLED, file_uid=file_uid,
    )
    logger.info(f"已送出取消請求 file_uid={file_uid} task_id={task_id}")
    return {"file_uid": file_uid, "cancelled": True}


def _can_terminate(log: TranscriptionLog | None) -> bool:
    """依任務的供應商的模型能力決定；還在佇列（沒有紀錄）的任務 revoke 就不會啟動，不需要終止。"""
    if log is None:
        return False
    try:
        return model_capabilities(log.provider, log.model_used).can_terminate
    except UnsupportedModelError:
        return False


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

        try:
            await run_in_threadpool(start_transcription_task_sync, payload_str=payload_str, file_uid=file_uid)
        except (UnsafeUploadFilenameError, UnsupportedModelError) as e:
            logger.warning(f"拒絕轉錄請求 (file_uid: {file_uid}): {e}")
            await websocket.send_json({
                "client_id": file_uid,
                "file_uid": file_uid,
                "status_code": TaskStatus.FAILED,
                "status_text": str(e),
            })
            manager.disconnect(file_uid)
            await websocket.close(code=1008)
            return

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
