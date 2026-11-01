from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, cast

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    HTTPException,
)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from app.celery.models import BatchTranscriptionTaskParams, BatchFileItemParams
from app.api.transcription import SUBMISSION_FAILED, SUBMISSION_FAILED_TEXT, TASK_GONE
from app.runtime import run_mode
from app.core.batch_state import IN_PROGRESS, BatchState
from app.core.config import get_settings
from app.core.error_codes import ErrorCode, Failure, describe
from app.core.task_status import TaskStatus
from app.database.models import BatchFile
from app.database.session import SessionLocal, get_db, traceback_without_db_details
from app.provider.registry import UnsupportedModelError, check_request
from app.repositories.batch_job_repository import BatchJobRepository
from app.repositories.model_manager_repository import stored_prompt_template
from app.services import audio_store
from app.services.api_keys import PlaintextApiKeyError, refuse_plaintext_api_keys, resolve_api_key
from app.tasks import batch_core
from app.tasks.lifecycle import ended_status
from app.utils.logger import setup_logger
from app.utils.paths import MissingUploadError, UnsafeUploadFilenameError, existing_upload_path
from app.websocket.manager import manager
from app.schemas.schemas import (
    WebSocketBatchRequest,
    RecoverBatchRequest,
    RecoverFileResult,
    RecoverBatchResponse,
    BatchTaskFile,
    BatchTaskResponse,
)

logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = settings.temp_uploads_path
TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

batch_repo = BatchJobRepository()


SUBMITTING_TEXT = "正在送出批次..."
"""接回批次時，伺服器還在送出這個批次（驗證請求、派送）：給畫面看的狀態文字（#286）。"""

QUEUED_TEXT = "批次排隊中，輪到時開始處理..."
"""接回批次時，批次已經派送、還沒開始執行（還沒有批次紀錄）：給畫面看的狀態文字（#286）。"""

REATTACHED_TEXT = "重新連上了，批次還在處理中..."
"""接回批次時，批次已經開始、還沒送出給供應商（去靜音、上傳）：給畫面看的狀態文字，之後的進度照樣由
批次廣播（#286）。"""

SUBMITTED_TEXT = "批次已送出，等待處理中..."
"""接回批次時，批次已經送出給供應商：和送出時一樣，畫面把還在等的檔案改成批次等待，結果到任務頁取回
（#286）。"""

NOT_SUBMITTED = Failure(
    ErrorCode.SUBMIT_FAILED,
    "伺服器上沒有這個批次，批次沒有送出：可能是送出時連線就中斷了，或應用程式關閉了")
"""接回批次時，伺服器上找不到這個批次（沒有批次紀錄，這個行程也沒有收到它）時的錯誤碼與細節（#286）。"""


# ==================== Task Page Endpoints ====================

@router.get("/tasks", response_model=list[BatchTaskResponse])
def get_batch_tasks(db: Session = Depends(get_db)):
    """取得所有活躍的批次（Task 頁面用），自動歸檔超過 24 小時的已完成批次。

    每個批次附上任務頁要不要給「恢復」（:func:`~app.tasks.batch_core.recoverable`）。
    """
    archived = batch_repo.archive_old_completed(db)
    if archived > 0:
        logger.info(f"自動歸檔 {archived} 個超過 24 小時的已完成批次")

    jobs = batch_repo.get_active_tasks(db)
    files_of = batch_repo.files_of(db, [job.batch_id for job in jobs])
    results = []
    for job in jobs:
        # 每個檔案在 batch_files 各一列，建立批次時就有（#116）
        rows = files_of.get(job.batch_id, [])
        files = [BatchTaskFile(file_uid=row.file_uid, original_filename=row.original_filename)
                 for row in rows]

        elapsed = None
        if job.created_at:
            # created_at 以應用層本地時間寫入（models.py 的 datetime.now default），
            # 需用 now() 對齊（utcnow 會差 8 小時）
            elapsed = (datetime.now() - job.created_at).total_seconds()

        # 任務頁照它標「已中斷」、給「恢復」
        is_alive = batch_core.watched(job)

        results.append(BatchTaskResponse(
            batch_id=job.batch_id,
            status=job.status,
            file_count=job.file_count or len(files),
            is_alive=is_alive,
            created_at=job.created_at.isoformat() if job.created_at else None,
            elapsed_seconds=elapsed,
            files=files,
            session_id=job.session_id or job.batch_id,
            recoverable=batch_core.recoverable(job, rows, alive=is_alive),
        ))
    return results


@router.post("/{batch_id}/dismiss")
def dismiss_batch_task(batch_id: str, db: Session = Depends(get_db)):
    """用戶手動忽略/歸檔一個批次。"""
    success = batch_repo.mark_as_retrieved(db, batch_id)
    if not success:
        raise HTTPException(status_code=404, detail="找不到這個批次")
    return {"success": True}


# ==================== Recovery REST Endpoints ====================

@router.post("/{batch_id}/recover", response_model=RecoverBatchResponse)
def recover_batch(batch_id: str, body: RecoverBatchRequest, db: Session = Depends(get_db)):
    """
    恢復指定批次的結果。

    - 批次已經結束：回傳完成的檔案的結果，從任務紀錄與片段讀出
    - 其他情況：派送復原入口接手批次（batches.get 只能在 worker 中運行），接著輪詢到批次結束
    """
    job = batch_repo.get_job(db, batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到這個批次")

    # ============================================================
    # 快速路徑：批次已經結束 → 直接從 DB 回傳
    # ============================================================
    completed = batch_core.completed_results(db, job)
    if completed is not None:
        logger.info(f"恢復批次 {batch_id}: 從 DB 讀取完成的結果 (status={job.status})")
        file_results = [RecoverFileResult(
            file_uid=row.file_uid,
            original_filename=row.original_filename,
            status=TaskStatus.COMPLETED,
            result=result,
        ) for row, result in completed]
        batch_repo.mark_as_retrieved(db, batch_id)
        return RecoverBatchResponse(batch_id=batch_id, files=file_results)

    # ============================================================
    # 復原路徑：派送背景任務從 Gemini 取得結果
    # ============================================================
    refusal = batch_core.recovery_refusal(db, job)
    if refusal is not None:
        raise HTTPException(status_code=400, detail=refusal)

    # 請求不帶金鑰或只帶遮罩值：用資料庫裡的 Google 金鑰；帶明文就拒收（#16 Q8b）
    try:
        api_key = resolve_api_key(db, "Google", body.api_keys)
    except PlaintextApiKeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="需要 Gemini 的 API 金鑰才能查詢批次的結果，請先到 Settings 設定",
        )

    logger.info(f"恢復批次 {batch_id}: 派送背景任務從 Gemini 取得結果 (當前狀態={job.status})")
    # 派送背景任務非同步處理，結果稍後透過 WebSocket 通知前端；批次剛好完成了就不派送，
    # 之後再取回就走快速路徑
    batch_core.start_recovery(db, batch_id, api_key)

    # 立刻回傳空結果；前端應透過 WebSocket 或重新查詢 /tasks 取得最新狀態
    return RecoverBatchResponse(batch_id=batch_id, files=[])


# ==================== Original Endpoints ====================

@dataclass(frozen=True)
class Dispatched:
    """送出批次的結果：派送了的話是執行它的任務 id，以及被拒檔案的 FAILED 訊息。"""

    run_id: Optional[str]
    """執行這個批次的任務 id；整批都沒有派送時是 None。"""
    rejected: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Submission:
    """這個行程收到的一個批次：還在送出時 ``run_id`` 是 None，派送之後是執行它的任務 id。"""

    run_id: Optional[str] = None


class Submissions:
    """這個行程收到、送出中或已經派送的批次，以 batch_id 為 key（#286）。

    批次紀錄要等批次開始執行才建立（:func:`app.tasks.batch_core.run_batch`），在那之前只有這裡知道
    批次送出了：接回批次時靠它分清楚「還在送出、還在排隊」與「沒有送出」。整批沒有派送時拿掉。

    只記在這個行程的記憶體裡，和批次的連線一樣（:class:`~app.websocket.manager.ConnectionManager`）：
    免安裝模式的批次也在這個行程裡執行，應用程式重新啟動之後，還在排隊的批次已經收尾、有了紀錄
    （:func:`~app.tasks.batch_core.abandon_batch`），或跟著行程停了、不會再執行。只在 event loop
    裡讀寫，不必上鎖。最多記 :attr:`LIMIT` 個：更早的批次早就開始執行、有了紀錄。
    """

    LIMIT = 256

    def __init__(self) -> None:
        self._submissions: OrderedDict[str, Submission] = OrderedDict()

    def submitting(self, batch_id: str) -> None:
        self._remember(batch_id, Submission())

    def dispatched(self, batch_id: str, run_id: Optional[str]) -> None:
        """派送了（``run_id`` 是執行它的任務 id）；整批沒有派送（None）時拿掉。"""
        if run_id is None:
            self._submissions.pop(batch_id, None)
        else:
            self._remember(batch_id, Submission(run_id))

    def get(self, batch_id: str) -> Optional[Submission]:
        return self._submissions.get(batch_id)

    def _remember(self, batch_id: str, submission: Submission) -> None:
        self._submissions[batch_id] = submission
        self._submissions.move_to_end(batch_id)
        while len(self._submissions) > self.LIMIT:
            self._submissions.popitem(last=False)


submissions = Submissions()


def start_batch_task_sync(payload_str: str, batch_id: str) -> Dispatched:
    """
    同步函式：解析批次請求並派發批次轉錄任務。
    在獨立執行緒中執行以避免阻塞事件迴圈。

    檔名不合法（不是 temp_uploads 內的單純檔名）或上傳檔已經不在的檔案不派發，其餘照常，
    一個都不剩時整批不派發；模型不屬於所選供應商、不支援批次或不吃提示詞，或請求帶了明文
    金鑰（#16 Q8b）時也整批不派發。回傳執行它的任務 id（整批沒有派發時是 None）與被拒檔案的
    FAILED 訊息，由 WS 端點送回前端。

    派送前出了非預期的錯誤（例如讀不到設定）時往上拋：整批都沒有派送，上傳檔不會變成任務，
    刪掉不留在電腦上。
    """
    request_data = WebSocketBatchRequest.model_validate_json(payload_str)
    try:
        return _submit_batch(request_data, batch_id)
    except BaseException:
        for f in request_data.files:
            audio_store.discard_upload(f.filename, TEMP_UPLOADS_DIR)
        raise


def _submit_batch(request_data: WebSocketBatchRequest, batch_id: str) -> Dispatched:
    """驗證請求、組出批次並派送（見 :func:`start_batch_task_sync`）。"""
    try:
        refuse_plaintext_api_keys(request_data.api_keys)
        # 批次層級與各檔案的提示詞串在一起檢查：任一個填了，串起來就不是空白
        all_prompts = "".join(p or "" for p in (
            request_data.prompt, *(f.prompt for f in request_data.files)))
        provider, _ = check_request(request_data.provider, request_data.model,
                                    prompt=all_prompts, batch=True)
    except (PlaintextApiKeyError, UnsupportedModelError) as e:
        logger.warning(f"批次 {batch_id} 被拒: {e}")
        # 被拒絕的批次不會執行：上傳檔不留在電腦上（前端重新送出時會重新上傳）
        for f in request_data.files:
            audio_store.discard_upload(f.filename, TEMP_UPLOADS_DIR)
        return Dispatched(None, [{
            "client_id": batch_id,
            "file_uid": f.file_uid,
            "status_code": TaskStatus.FAILED,
            "status_text": str(e),
            **describe(e).fields(),
        } for f in request_data.files])

    file_items = []
    rejected = []
    for f in request_data.files:
        try:
            temp_file_path = existing_upload_path(f.filename, TEMP_UPLOADS_DIR)
        except (UnsafeUploadFilenameError, MissingUploadError) as e:
            if isinstance(e, UnsafeUploadFilenameError):
                logger.warning(f"批次拒絕不合法的上傳檔名 (file_uid: {f.file_uid}): {f.filename!r}")
            else:
                logger.error(f"批次的檔案不存在 (file_uid: {f.file_uid}): {f.filename!r}")
            # 沒送出的檔案也回失敗狀態，使用者才知道它沒有送出
            rejected.append({
                "client_id": batch_id,
                "file_uid": f.file_uid,
                "status_code": TaskStatus.FAILED,
                "status_text": str(e),
                **describe(e).fields(),
            })
            continue

        file_items.append(BatchFileItemParams(
            file_path=str(temp_file_path),
            original_filename=f.original_filename,
            file_uid=f.file_uid,
            source_lang=f.source_lang,
            target_lang=f.target_lang,
            prompt=f.prompt,
            multi_speaker=f.multi_speaker,
        ))

    if not file_items:
        logger.error(f"批次 {batch_id} 沒有有效的檔案，不派送")
        return Dispatched(None, rejected)

    # 請求不帶金鑰或只帶遮罩值（明文在上面已經拒收）：用資料庫裡的金鑰
    with SessionLocal() as db:
        api_key = resolve_api_key(db, provider, request_data.api_keys)
        # 提示詞範本也從設定讀（#144）：整個批次共用派送時設定頁存的範本，接上每個檔案的補充說明
        prompt_template = stored_prompt_template(db, provider)

    task_params = BatchTranscriptionTaskParams(
        files=file_items,
        provider=provider,
        model=request_data.model,
        api_keys=api_key,
        source_lang=request_data.source_lang,
        target_lang=request_data.target_lang,
        prompt=request_data.prompt,
        prompt_template=prompt_template,
        multi_speaker=request_data.multi_speaker,
        client_id=batch_id,
        batch_id=batch_id,
        session_id=request_data.session_id or batch_id,
    )

    run_id = run_mode.get().submit_batch(task_params.model_dump())
    logger.info(f"已為 batch_id: {batch_id} 啟動批次轉錄任務 ({len(file_items)} 個檔案)。")
    return Dispatched(run_id, rejected)


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
    - 整批沒有派送時（派送前出了非預期的錯誤），收到一則沒有 file_uid 的 FAILED，接著連線關閉

    送出時連線斷了，畫面從接回批次的端點（:func:`batch_reattach_endpoint`）接著收；這裡送的被拒檔案與
    整批沒有派送的訊息，送給這個批次現在登記的連線，接回的連線也收得到（#286）。
    """
    await manager.connect(websocket, batch_id)
    try:
        payload_str = await websocket.receive_text()

        submissions.submitting(batch_id)
        try:
            dispatched = await run_in_threadpool(
                start_batch_task_sync, payload_str=payload_str, batch_id=batch_id
            )
        except Exception as e:
            submissions.dispatched(batch_id, None)
            # 整批沒有派送：送一則沒有 file_uid 的失敗，畫面把這批還在處理中的檔案都標成失敗，
            # 不會停在「批次已送出」。例外不轉述（資料庫例外帶著 SQL 原文），log 只記類型與原因
            logger.error(f"提交批次失敗 (batch_id: {batch_id}):\n"
                         f"{traceback_without_db_details(e)}")
            await manager.send_personal_message(_batch_status(
                batch_id, TaskStatus.FAILED, SUBMISSION_FAILED_TEXT, failure=SUBMISSION_FAILED),
                batch_id)
            # 只關、只移除這條連線：同一個 batch_id 的新連線可能已經登記上來（#203）
            await manager.close(batch_id, websocket, code=1011)
            return
        submissions.dispatched(batch_id, dispatched.run_id)
        for message in dispatched.rejected:
            await manager.send_personal_message(message, batch_id)

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"批次 WebSocket 連線由客戶端關閉: {batch_id}")
        manager.disconnect(batch_id, websocket)
    except Exception as e:
        logger.error(f"批次 WebSocket 端點發生錯誤 (batch_id: {batch_id}):\n"
                     f"{traceback_without_db_details(e)}")
        # 只關、只移除這條連線：同一個 batch_id 的新連線可能已經登記上來（#203）
        await manager.close(batch_id, websocket)


@router.websocket("/ws/{batch_id}/reattach", name="WebSocket Reattach Batch")
async def batch_reattach_endpoint(websocket: WebSocket, batch_id: str):
    """送出批次之後連線中斷，接回這個批次（#286）。

    連線斷了不會停止批次：批次照樣在伺服器上跑。batch_id 是畫面送出時自己產生的，所以連線在伺服器
    回應之前就斷了也接得回來。畫面重新連上這裡，先收到批次現在的狀態（:func:`batch_state`），之後和
    送出批次的那條連線一樣收這個批次的廣播。

    連線先登記、再查狀態：查完之後才宣告的進度、檔案的結束與送出給供應商，一定送得到這條連線。查狀態
    時出錯就以 1011 關閉，畫面稍後再連一次。
    """
    await manager.connect(websocket, batch_id)
    try:
        submission = submissions.get(batch_id)
        for message in await run_in_threadpool(batch_state, batch_id, submission):
            await websocket.send_json(message)
        # 保持連線開啟，收批次之後的廣播；畫面送來的只有心跳
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"接回批次的 WebSocket 連線關閉: {batch_id}")
        manager.disconnect(batch_id, websocket)
    except Exception as e:
        logger.error(f"接回批次時發生錯誤 (batch_id: {batch_id}):\n"
                     f"{traceback_without_db_details(e)}")
        # 只關、只移除這條連線：同一個批次可能已經有新的連線登記上來（#203）
        await manager.close(batch_id, websocket, code=1011)


def batch_state(batch_id: str, submission: Optional[Submission]) -> list[dict]:
    """這個批次現在的狀態，寫成和批次廣播一樣的狀態訊息；接回批次時依序送給畫面。

    ``submission`` 是這個行程收到這個批次的紀錄（:class:`Submissions`），沒有收到時是 None。

    還沒有批次紀錄（批次還沒開始執行）時只有一則批次層級的訊息：

    - 還在送出：處理中「正在送出批次...」；之後被拒的檔案或整批沒有派送的訊息，也送到接回的連線。
    - 已經派送，執行它的任務還在（或不知道）：處理中「批次排隊中...」。
    - 都不是：失敗，錯誤碼 SUBMIT_FAILED，批次沒有送出。不會當成已經送出或完成。

    有批次紀錄時，先補上斷線期間已經結束的檔案（每個檔案一則，照任務紀錄補上結束時的宣告，見
    :func:`~app.tasks.lifecycle.ended_status`），還有沒結束的檔案時再看批次：

    - 已經送出給供應商：「批次已送出」（BATCH_SUBMITTED），和送出時一樣，結果到任務頁取回。
    - 還沒送出、看著它的任務還在（或不知道）：處理中「重新連上了...」，之後的進度照樣由批次廣播。
    - 還沒送出、看著它的任務已經不在了（例如上傳時應用程式重新啟動，啟動時還沒收尾）：還沒結束的
      檔案各記一則失敗，錯誤碼 INTERRUPTED，和接回單檔任務時伺服器上已經沒有這個任務一樣。
    """
    with SessionLocal() as db:
        job = batch_repo.get_job(db, batch_id)
        if job is None:
            return [_unrecorded(batch_id, submission)]
        rows = batch_repo.files(db, batch_id)
        ended = [(row, ended_status(db, row.task_uuid)) for row in rows]
        # 讀出來的值：型別檢查把 Column 的屬性看成欄位本身，不是它的值
        status = cast(str, job.status)
        submitted = bool(cast(Optional[str], job.gemini_job_name))
        alive = (batch_core.watched(job) if status in IN_PROGRESS
                 else run_mode.get().is_alive(cast(Optional[str], job.celery_task_id) or ""))
    messages = [_file_status(batch_id, row, status) for row, status in ended if status is not None]
    remaining = [row for row, status in ended if status is None]
    if not remaining:
        return messages
    if submitted:
        return [*messages, _batch_status(batch_id, TaskStatus.BATCH_SUBMITTED, SUBMITTED_TEXT)]
    if alive is False or status == BatchState.FAILED:
        return [*messages, *(_file_status(batch_id, row, {
            "status_code": TaskStatus.FAILED, "status_text": f"任務失敗: {TASK_GONE.detail}",
            **TASK_GONE.fields()}) for row in remaining)]
    return [*messages, _batch_status(batch_id, TaskStatus.PROCESSING, REATTACHED_TEXT)]


def _unrecorded(batch_id: str, submission: Optional[Submission]) -> dict:
    """還沒有批次紀錄的批次，接回時的那一則（見 :func:`batch_state`）。"""
    if submission is not None:
        if submission.run_id is None:
            return _batch_status(batch_id, TaskStatus.PROCESSING, SUBMITTING_TEXT)
        # 免安裝模式查得準；Docker 模式的 Celery 在任務排隊時回不知道（None），當成還在
        if run_mode.get().is_alive(submission.run_id) is not False:
            return _batch_status(batch_id, TaskStatus.PROCESSING, QUEUED_TEXT)
    return _batch_status(batch_id, TaskStatus.FAILED, f"批次沒有送出: {NOT_SUBMITTED.detail}",
                         failure=NOT_SUBMITTED)


def _file_status(batch_id: str, row: BatchFile, status: dict) -> dict:
    """批次裡一個檔案的狀態訊息，欄位和任務生命週期替批次裡的檔案廣播的相同。"""
    return {"client_id": batch_id, "batch_id": batch_id, "file_uid": cast(str, row.file_uid),
            "task_uuid": str(row.task_uuid), **status}


def _batch_status(batch_id: str, status_code: TaskStatus, status_text: str, *,
                  failure: Optional[Failure] = None) -> dict:
    """端點自己送給畫面的批次層級狀態訊息（沒有 file_uid）；失敗時帶錯誤碼與細節。"""
    message = {"client_id": batch_id, "status_code": status_code, "status_text": status_text}
    if failure is not None:
        message.update(failure.fields())
    return message
