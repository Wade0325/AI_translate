from datetime import datetime

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
from app.runtime import run_mode
from app.core.batch_state import IN_PROGRESS
from app.core.config import get_settings
from app.core.task_status import TaskStatus
from app.database.session import SessionLocal, get_db
from app.provider.registry import UnsupportedModelError, check_request
from app.repositories.batch_job_repository import BatchJobRepository
from app.repositories.model_manager_repository import stored_prompt_template
from app.services import audio_store
from app.services.api_keys import resolve_api_key
from app.tasks import batch_core
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

        is_alive = None
        if job.status in IN_PROGRESS:
            alive = run_mode.get().is_alive(job.celery_task_id)
            if alive is not None:
                is_alive = alive
            elif job.updated_at and (datetime.now() - job.updated_at).total_seconds() > 300:
                # 查不出來（PENDING）、派出看著它的任務（或改狀態）之後又超過 5 分鐘：極大概率已死。
                # 從派出的時候算，剛派出去、還排在佇列裡的復原不算停住。任務頁照它標「已中斷」、給「恢復」
                is_alive = False

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
        raise HTTPException(status_code=404, detail="找不到此批次任務")
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
        raise HTTPException(status_code=404, detail="找不到此批次任務")

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

    # 前端不再保存明文金鑰：請求沒帶（或只帶遮罩值）時改用資料庫裡的 Google 金鑰
    api_key = resolve_api_key(db, "Google", body.api_keys)
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

def start_batch_task_sync(payload_str: str, batch_id: str) -> list[dict]:
    """
    同步函式：解析批次請求並派發批次轉錄任務。
    在獨立執行緒中執行以避免阻塞事件迴圈。

    檔名不合法（不是 temp_uploads 內的單純檔名）或上傳檔已經不在的檔案不派發，其餘照常，
    一個都不剩時整批不派發；模型不屬於所選供應商、不支援批次或不吃提示詞時也整批不派發。
    回傳被拒檔案的 FAILED 訊息，由 WS 端點送回前端。
    """
    request_data = WebSocketBatchRequest.model_validate_json(payload_str)

    try:
        # 批次層級與各檔案的提示詞串在一起檢查：任一個填了，串起來就不是空白
        all_prompts = "".join(p or "" for p in (
            request_data.prompt, *(f.prompt for f in request_data.files)))
        provider, _ = check_request(request_data.provider, request_data.model,
                                    prompt=all_prompts, batch=True)
    except UnsupportedModelError as e:
        logger.warning(f"批次 {batch_id} 被拒: {e}")
        # 被拒絕的批次不會執行：上傳檔不留在電腦上（前端重新送出時會重新上傳）
        for f in request_data.files:
            audio_store.discard_upload(f.filename, TEMP_UPLOADS_DIR)
        return [{
            "client_id": batch_id,
            "file_uid": f.file_uid,
            "status_code": TaskStatus.FAILED,
            "status_text": str(e),
        } for f in request_data.files]

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
        return rejected

    # 前端不再送明文金鑰：缺少或只帶遮罩值時改用資料庫裡的金鑰
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

    run_mode.get().submit_batch(task_params.model_dump())
    logger.info(f"已為 batch_id: {batch_id} 啟動批次轉錄任務 ({len(file_items)} 個檔案)。")
    return rejected


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

        rejected = await run_in_threadpool(
            start_batch_task_sync, payload_str=payload_str, batch_id=batch_id
        )
        for message in rejected:
            await websocket.send_json(message)

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
