import uuid
from typing import Callable

from anyio import from_thread
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
from app.database.session import SessionLocal, traceback_without_db_details
from app.provider.base import ModelCapabilities
from app.provider.registry import UnsupportedModelError, check_request
from app.repositories.model_manager_repository import stored_prompt_template
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.services import audio_store
from app.services.api_keys import PlaintextApiKeyError, refuse_plaintext_api_keys, resolve_api_key
from app.utils.logger import setup_logger
from app.utils.paths import MissingUploadError, UnsafeUploadFilenameError, existing_upload_path
from app.websocket.manager import manager
from app.schemas.schemas import WebSocketTranscriptionRequest


logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = settings.temp_uploads_path
TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


QUEUED_TEXT = "排隊中，輪到時開始轉錄..."
"""任務派送之前送給畫面的狀態文字：任務開始之前一直顯示這句（#24 門檻 4）。

本機一次只轉錄一個檔案，後面的檔案要等前面的轉完；Gemini 也有同時轉錄的上限。"""

SUBMISSION_FAILED_TEXT = "提交任務失敗，任務沒有開始。請重新轉錄；一直失敗時，請到設定頁回報問題並附上日誌"
"""派送前出了非預期的錯誤（例如讀不到設定、應用程式正在關閉）時給使用者看的原因；原因只記在 log。"""


def start_transcription_task_sync(
        payload_str: str, file_uid: str, announce_queued: Callable[[str], None]) -> None:
    """解析 WS 請求並派發轉錄任務；在 threadpool 執行以免阻塞事件迴圈。

    派送之前先呼叫 ``announce_queued(task_uuid)`` 告訴畫面任務排進佇列了：任務一開始就會廣播進度，
    排隊中要比它早送到，才不會蓋掉進度。``announce_queued`` 丟出例外時不派送。

    請求被拒絕或派送前出錯時，任務都沒有派送：上傳檔不會變成任務，刪掉不留在電腦上
    （前端重新送出時會重新上傳）。

    Raises:
        UnsafeUploadFilenameError: filename 不是 temp_uploads 內的單純檔名。
        MissingUploadError: 上傳檔已經不在，例如被清掃掉，或另一個分頁已經送出同一個檔。
        UnsupportedModelError: 模型不屬於所選的供應商、模型不支援請求的處理模式（Flex），
            或填了模型不吃的提示詞或使用者文稿
            （:class:`~app.provider.registry.UnsupportedInputError`）。
        PlaintextApiKeyError: 請求帶了明文金鑰（#16 Q8b）。
    """
    request_data = WebSocketTranscriptionRequest.model_validate_json(
        payload_str)
    try:
        task_id, capabilities = _submit(request_data, file_uid, announce_queued)
    except BaseException:
        audio_store.discard_upload(request_data.filename, TEMP_UPLOADS_DIR)
        raise
    # 派送之後立刻登記，能不能強制終止照模型能力一起登記：取消時不必再查任務紀錄（可能還沒
    # 建立）或模型清單（模型可能已經拿掉）。不能先登記：還沒交給執行模式的任務查不到存活，
    # 這時按取消會被當成已經結束、清掉登記，任務之後就取消不了
    run_mode.get().register_task(file_uid, task_id, can_terminate=capabilities.can_terminate)
    logger.info(f"已為 file_uid: {file_uid} 啟動轉錄任務（queue={capabilities.queue}）。")


def _submit(request_data: WebSocketTranscriptionRequest, file_uid: str,
            announce_queued: Callable[[str], None]) -> tuple[str, ModelCapabilities]:
    """驗證請求、組出任務，告訴畫面排進佇列了，再交給執行模式；回傳任務 ID 與模型能力。"""
    # 先驗證再碰檔案：不符的組合不能默默跑到別的供應商，模型不吃的輸入也不能默默丟掉
    refuse_plaintext_api_keys(request_data.api_keys)
    provider, capabilities = check_request(
        request_data.provider, request_data.model,
        prompt=request_data.prompt, user_text=request_data.user_supplied_text,
        service_tier=request_data.service_tier)

    server_file_path = str(existing_upload_path(request_data.filename, TEMP_UPLOADS_DIR))

    # 請求不帶金鑰或只帶遮罩值（明文在上面已經拒收）：用資料庫裡的金鑰
    with SessionLocal() as db:
        api_key = resolve_api_key(db, provider, request_data.api_keys)
        # 提示詞範本也從設定讀（#144）：用派送這個檔案時設定頁存的範本，接上請求帶的補充說明
        prompt_template = stored_prompt_template(db, provider)

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
        prompt_template=prompt_template,
        multi_speaker=request_data.multi_speaker,
        service_tier=request_data.service_tier,
        session_id=request_data.session_id,
    )

    # 清掉上一次執行殘留的取消旗標（例如被 revoke 掉、沒機會自行清理的任務），
    # 否則同一檔案再開的任務會被誤取消
    mode = run_mode.get()
    mode.clear_cancel(file_uid)
    task_id = str(uuid.uuid4())
    announce_queued(task_id)
    mode.submit_transcription(task_id, task_params.model_dump(), capabilities.queue)
    return task_id, capabilities


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

    收到請求之後，畫面一定會收到下面其中一則，不會停在「正在提交任務」：

    - 排隊中（PROCESSING，帶 task_uuid）：任務派送了，之後的進度與結果由任務廣播。
    - 失敗（FAILED）之後關閉連線：任務沒有派送。請求被拒絕時給拒絕的原因（1008），
      派送前出了非預期的錯誤時給固定的訊息（1011），原因只記在 log。
    """
    await manager.connect(websocket, file_uid)
    try:
        payload_str = await websocket.receive_text()

        def announce_queued(task_uuid: str) -> None:
            # 在 threadpool 裡呼叫：交回事件迴圈送出，送完才派送
            from_thread.run(websocket.send_json, _status(
                file_uid, TaskStatus.PROCESSING, QUEUED_TEXT, task_uuid=task_uuid))

        try:
            await run_in_threadpool(start_transcription_task_sync, payload_str=payload_str,
                                    file_uid=file_uid, announce_queued=announce_queued)
        except (UnsafeUploadFilenameError, MissingUploadError, UnsupportedModelError,
                PlaintextApiKeyError) as e:
            # 檔名的錯誤訊息是固定的：檔名要另外記，排查只能靠使用者附上的 log（ADR-0005）。
            # 用 repr，換行等控制字元才不會在 log 裡偽造出別的行
            if isinstance(e, UnsafeUploadFilenameError):
                logger.warning(f"拒絕不合法的上傳檔名 (file_uid: {file_uid}): {e.filename!r}")
            elif isinstance(e, MissingUploadError):
                logger.error(f"檔案不存在 (file_uid: {file_uid}): {e.filename!r}")
            else:  # 訊息固定，不含金鑰或檔名
                logger.warning(f"拒絕轉錄請求 (file_uid: {file_uid}): {e}")
            await _not_submitted(websocket, file_uid, str(e), code=1008)
            return
        except WebSocketDisconnect:
            raise
        except Exception as e:
            # 例外不轉述（資料庫例外帶著 SQL 原文）：log 只記類型與原因，traceback 留著出錯的位置
            logger.error(f"提交轉錄任務失敗 (file_uid: {file_uid}):\n"
                         f"{traceback_without_db_details(e)}")
            await _not_submitted(websocket, file_uid, SUBMISSION_FAILED_TEXT, code=1011)
            return

        # 保持連線開啟以接收來自客戶端的訊息
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"WebSocket 連線由客戶端或伺服器關閉: {file_uid}")
        manager.disconnect(file_uid, websocket)
    except Exception as e:
        logger.error(f"WebSocket 端點發生錯誤 (file_uid: {file_uid}):\n"
                     f"{traceback_without_db_details(e)}")
        # 只關、只移除這條連線：重新轉錄的新連線可能已經登記在同一個 file_uid 底下（#203）
        await manager.close(file_uid, websocket)


def _status(file_uid: str, status_code: TaskStatus, status_text: str, *,
            task_uuid: str | None = None) -> dict:
    """端點自己送給畫面的狀態訊息，欄位和任務的狀態廣播（:func:`publish_status`）相同。"""
    message = {"client_id": file_uid, "file_uid": file_uid,
               "status_code": status_code, "status_text": status_text}
    if task_uuid:
        message["task_uuid"] = task_uuid
    return message


async def _not_submitted(websocket: WebSocket, file_uid: str, reason: str, *, code: int) -> None:
    """告訴畫面任務沒有送出與原因，再關掉這條連線。"""
    await websocket.send_json(_status(file_uid, TaskStatus.FAILED, reason))
    # 只關、只移除這條連線：重新轉錄的新連線可能已經登記在同一個 file_uid 底下（#203）
    await manager.close(file_uid, websocket, code=code)
