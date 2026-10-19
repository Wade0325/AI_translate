from datetime import datetime
import json

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
from app.core.config import get_settings
from app.core.task_status import TaskStatus
from app.database.session import SessionLocal, get_db
from app.provider.registry import UnsupportedModelError, check_request
from app.repositories.batch_job_repository import BatchJobRepository
from app.services.api_keys import resolve_api_key
from app.utils.logger import setup_logger
from app.utils.paths import UnsafeUploadFilenameError, resolve_upload_path
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
    """取得所有活躍的批次（Task 頁面用），自動歸檔超過 24 小時的已完成批次。"""
    archived = batch_repo.archive_old_completed(db)
    if archived > 0:
        logger.info(f"自動歸檔 {archived} 個超過 24 小時的已完成批次")

    jobs = batch_repo.get_active_tasks(db)
    results = []
    for job in jobs:
        files = []
        if job.file_mapping_json:
            mapping = json.loads(job.file_mapping_json)
            for idx in sorted(mapping.keys(), key=int):
                entry = mapping[idx]
                files.append(BatchTaskFile(
                    file_uid=entry["file_uid"],
                    original_filename=entry["original_filename"],
                ))

        elapsed = None
        if job.created_at:
            # created_at 以應用層本地時間寫入（models.py 的 datetime.now default），
            # 需用 now() 對齊（utcnow 會差 8 小時）
            elapsed = (datetime.now() - job.created_at).total_seconds()

        is_alive = None
        if job.status in ("UPLOADING", "POLLING", "RECOVERING"):
            alive = run_mode.get().is_alive(job.celery_task_id)
            if alive is not None:
                is_alive = alive
            elif elapsed and elapsed > 300:
                # PENDING 狀態超過 5 分鐘，極大概率已死
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

    - status=COMPLETED 且有 results_json：直接從 DB 讀取結果
    - 其他情況：透過 Celery task 從 Gemini 取得結果（batches.get 只能在 worker 中運行）
    """
    job = batch_repo.get_job(db, batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到此批次任務")

    file_mapping = json.loads(job.file_mapping_json) if job.file_mapping_json else {}

    # ============================================================
    # 快速路徑：有存檔結果 → 直接從 DB 回傳
    # ============================================================
    if job.status in ("COMPLETED", "RETRIEVED", "RECOVERING") and job.results_json:
        logger.info(f"恢復批次 {batch_id}: 從 DB 讀取已存檔的結果 (status={job.status})")
        stored_results = json.loads(job.results_json)

        file_results = []
        for file_uid, result_data in stored_results.items():
            original_filename = file_uid
            for entry in file_mapping.values():
                if entry.get("file_uid") == file_uid:
                    original_filename = entry.get("original_filename", file_uid)
                    break

            file_results.append(RecoverFileResult(
                file_uid=file_uid,
                original_filename=original_filename,
                status=TaskStatus.COMPLETED,
                result=result_data,
            ))

        batch_repo.update_job(db, batch_id, {"status": "RETRIEVED"})
        return RecoverBatchResponse(batch_id=batch_id, files=file_results)

    # ============================================================
    # Celery 路徑：派送 Celery task 從 Gemini 取得結果
    # ============================================================
    if not job.gemini_job_name:
        raise HTTPException(status_code=400, detail="此任務尚未建立 Gemini batch job，無法恢復")

    # 前端不再保存明文金鑰：請求沒帶（或只帶遮罩值）時改用資料庫裡的 Google 金鑰
    api_key = resolve_api_key(db, "Google", body.api_keys)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Gemini 批次任務尚在處理中，需要 API 金鑰才能查詢狀態，"
                   "請先到 Settings 設定 Google API 金鑰",
        )

    logger.info(f"恢復批次 {batch_id}: 派送背景任務從 Gemini 取得結果 (當前狀態={job.status})")

    # 派送背景任務非同步處理。結果稍後透過 WebSocket / pending API 通知前端
    batch_repo.update_job(db, batch_id, {"status": "RECOVERING"})
    run_mode.get().submit_recover(batch_id, api_key)

    # 立刻回傳空結果；前端應透過 WebSocket 或重新查詢 /pending 取得最新狀態
    return RecoverBatchResponse(batch_id=batch_id, files=[])


# ==================== Original Endpoints ====================

def start_batch_task_sync(payload_str: str, batch_id: str) -> list[dict]:
    """
    同步函式：解析批次請求並派發批次轉錄任務。
    在獨立執行緒中執行以避免阻塞事件迴圈。

    檔名不合法（不是 temp_uploads 內的單純檔名）的檔案不派發，其餘照常；
    模型不屬於所選供應商、不支援批次或不吃提示詞時整批不派發。
    回傳被拒檔案的 FAILED 訊息，由 WS 端點送回前端。
    """
    request_data = WebSocketBatchRequest.model_validate_json(payload_str)

    try:
        # 批次層級與各檔案的提示詞串在一起檢查：任一個填了，串起來就不是空白
        all_prompts = "".join(p or "" for p in (
            request_data.prompt, *(f.prompt for f in request_data.files)))
        check_request(request_data.provider, request_data.model,
                      prompt=all_prompts, batch=True)
    except UnsupportedModelError as e:
        logger.warning(f"批次任務 {batch_id} 被拒: {e}")
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
            temp_file_path = resolve_upload_path(f.filename, TEMP_UPLOADS_DIR)
        except UnsafeUploadFilenameError as e:
            logger.warning(f"批次任務拒絕不合法的上傳檔名 (file_uid: {f.file_uid}): {f.filename!r}")
            rejected.append({
                "client_id": batch_id,
                "file_uid": f.file_uid,
                "status_code": TaskStatus.FAILED,
                "status_text": str(e),
            })
            continue
        if not temp_file_path.is_file():
            logger.error(f"批次任務檔案不存在: {f.filename}")
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
        logger.error(f"批次任務 {batch_id} 沒有有效的檔案，取消任務")
        return rejected

    # 前端不再送明文金鑰：缺少或只帶遮罩值時改用資料庫裡的金鑰
    with SessionLocal() as db:
        api_key = resolve_api_key(db, request_data.provider, request_data.api_keys)

    task_params = BatchTranscriptionTaskParams(
        files=file_items,
        provider=request_data.provider,
        model=request_data.model,
        api_keys=api_key,
        source_lang=request_data.source_lang,
        target_lang=request_data.target_lang,
        prompt=request_data.prompt,
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
