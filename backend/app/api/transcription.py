import uuid

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
from app.database.session import SessionLocal
from app.provider.registry import UnsupportedModelError, check_request
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.services import audio_store
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
        UnsupportedModelError: 模型不屬於所選的供應商，或填了模型不吃的提示詞或使用者文稿
            （:class:`~app.provider.registry.UnsupportedInputError`）。
    """
    request_data = WebSocketTranscriptionRequest.model_validate_json(
        payload_str)

    # 先驗證再碰檔案：不符的組合不能默默跑到別的供應商，模型不吃的輸入也不能默默丟掉
    try:
        provider, capabilities = check_request(
            request_data.provider, request_data.model,
            prompt=request_data.prompt, user_text=request_data.original_text,
            service_tier=request_data.service_tier)
    except UnsupportedModelError:
        # 被拒絕的請求不會變成任務：上傳檔不留在電腦上（前端重新送出時會重新上傳）
        audio_store.discard_upload(request_data.filename, TEMP_UPLOADS_DIR)
        raise

    temp_file_path = resolve_upload_path(request_data.filename, TEMP_UPLOADS_DIR)

    if temp_file_path.is_file():
        server_file_path = str(temp_file_path)
    else:
        logger.error(f"檔案不存在: {request_data.filename}")
        return

    # 前端不再送明文金鑰：缺少或只帶遮罩值時改用資料庫裡的金鑰
    with SessionLocal() as db:
        api_key = resolve_api_key(db, provider, request_data.api_keys)

    task_params = TranscriptionTaskParams(
        file_path=server_file_path,
        provider=provider,
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
    # 派送之後立刻登記，能不能強制終止照模型能力一起登記：取消時不必再查任務紀錄（可能還沒
    # 建立）或模型清單（模型可能已經拿掉）。不能先登記：還沒交給執行模式的任務查不到存活，
    # 這時按取消會被當成已經結束、清掉登記，任務之後就取消不了
    task_id = str(uuid.uuid4())
    mode.submit_transcription(task_id, task_params.model_dump(), queue)
    mode.register_task(file_uid, task_id, can_terminate=capabilities.can_terminate)
    logger.info(f"已為 file_uid: {file_uid} 啟動轉錄任務（queue={queue}）。")


@router.post("/transcription/{file_uid}/cancel", name="Cancel Transcription")
def cancel_transcription(file_uid: str):
    """取消單檔轉錄任務；要取消的任務與能不能強制終止都讀派送時的登記，不由前端告知。

    - 佇列中（紀錄還沒建立）：revoke 讓任務不會啟動，沒開始的任務照樣收尾
      （旗標另作保險，攔截撤銷沒送達的情況）
    - 執行中：模型能力允許強制終止的直接終止；不允許的（例如本機的 GPU worker）
      靠合作式檢查點在數秒內自行中止並釋放模型

    沒有登記的任務（還在上傳、還沒派送，或任務結束時已經清掉登記）時無事可取消，回報
    not-started 讓前端稍後重試。登記的任務已經結束（登記沒清掉，或正在收尾）時回報
    finished：不撤銷、不廣播已取消。
    """
    mode = run_mode.get()
    task = mode.registered_task(file_uid)
    if task is None:
        return {"file_uid": file_uid, "cancelled": False, "reason": "not-started"}
    task_id = task.task_id
    if mode.is_alive(task_id) is False:
        # 登記的任務已經結束，只是登記沒清掉（例如 worker 中途被終止）。Celery 回不知道
        # （None）時當成還在佇列裡
        mode.task_ended(file_uid, task_id)
        return _already_finished(file_uid)

    mode.request_cancel(file_uid)
    log_repo = TranscriptionLogRepository()
    with SessionLocal() as db:
        # 被 revoke/terminate 掉的任務不會再回報狀態：仍在 PROCESSING 的紀錄由此補寫。
        # 合作式停止的任務由任務生命週期自行記為 CANCELLED，此處條件式更新不衝突。
        if (not log_repo.mark_cancelled_if_processing(db, task_id)
                and log_repo.current_status(db, task_id) in _RESULT_RECORDED):
            # 任務已經記下完成或失敗、正在收尾：來不及取消了。不撤銷（強制終止會打斷收尾），
            # 也不廣播已取消，畫面才不會先跳已取消、再翻成完成；剛設的旗標一併清掉
            mode.task_ended(file_uid, task_id)
            return _already_finished(file_uid)
    mode.revoke(task_id, terminate=task.can_terminate)

    publish_status(
        file_uid, task_id, "任務已取消",
        status_code=TaskStatus.CANCELLED, file_uid=file_uid,
    )
    logger.info(f"已送出取消請求 file_uid={file_uid} task_id={task_id}")
    return {"file_uid": file_uid, "cancelled": True}


_RESULT_RECORDED = (TaskStatus.COMPLETED, TaskStatus.FAILED)
"""任務已經記下結果（完成或失敗）的紀錄狀態：這時才按取消已經來不及。"""


def _already_finished(file_uid: str) -> dict:
    return {"file_uid": file_uid, "cancelled": False, "reason": "finished"}


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
            if isinstance(e, UnsafeUploadFilenameError):
                # 錯誤訊息是固定的：可疑的檔名要另外記，排查只能靠使用者附上的 log（ADR-0005）。
                # 用 repr，換行等控制字元才不會在 log 裡偽造出別的行
                logger.warning(f"拒絕不合法的上傳檔名 (file_uid: {file_uid}): {e.filename!r}")
            else:
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
