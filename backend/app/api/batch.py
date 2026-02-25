from pathlib import Path
import json
import time
from types import SimpleNamespace

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    HTTPException,
)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.celery.batch_task import batch_transcribe_task
from app.celery.models import BatchTranscriptionTaskParams, BatchFileItemParams
from app.core.config import get_settings
from app.database.session import get_db
from app.repositories.batch_job_repository import BatchJobRepository
from app.utils.logger import setup_logger
from app.websocket.manager import manager
from app.schemas.schemas import (
    WebSocketBatchRequest,
    PendingBatchFile,
    PendingBatchResponse,
    RecoverBatchRequest,
    RecoverFileResult,
    RecoverBatchResponse,
)

logger = setup_logger(__name__)

router = APIRouter()

settings = get_settings()
TEMP_UPLOADS_DIR = Path(settings.temp_uploads_dir)
TEMP_UPLOADS_DIR.mkdir(exist_ok=True)

batch_repo = BatchJobRepository()


# ==================== Recovery REST Endpoints ====================

@router.get("/pending", response_model=list[PendingBatchResponse])
def get_pending_batches(db: Session = Depends(get_db)):
    """查詢未完成或尚未取回結果的批次任務"""
    jobs = batch_repo.get_pending_jobs(db)
    results = []
    for job in jobs:
        files = []
        if job.file_mapping_json:
            mapping = json.loads(job.file_mapping_json)
            for idx in sorted(mapping.keys(), key=int):
                entry = mapping[idx]
                files.append(PendingBatchFile(
                    file_uid=entry["file_uid"],
                    original_filename=entry["original_filename"],
                ))
        results.append(PendingBatchResponse(
            batch_id=job.batch_id,
            status=job.status,
            created_at=str(job.created_at) if job.created_at else "",
            files=files,
        ))
    return results


@router.post("/{batch_id}/recover", response_model=RecoverBatchResponse)
def recover_batch(batch_id: str, body: RecoverBatchRequest, db: Session = Depends(get_db)):
    """
    恢復指定批次任務的結果。

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
            for idx, entry in file_mapping.items():
                if entry.get("file_uid") == file_uid:
                    original_filename = entry.get("original_filename", file_uid)
                    break

            file_results.append(RecoverFileResult(
                file_uid=file_uid,
                original_filename=original_filename,
                status="COMPLETED",
                result=result_data,
            ))

        batch_repo.update_job(db, batch_id, {"status": "RETRIEVED"})
        return RecoverBatchResponse(batch_id=batch_id, files=file_results)

    # ============================================================
    # Celery 路徑：派送 Celery task 從 Gemini 取得結果
    # ============================================================
    if not job.gemini_job_name:
        raise HTTPException(status_code=400, detail="此任務尚未建立 Gemini batch job，無法恢復")

    api_key = body.api_keys
    if not api_key:
        raise HTTPException(status_code=400, detail="請提供 API Key")

    logger.info(f"恢復批次 {batch_id}: 派送 Celery 恢復任務 (當前狀態={job.status})")

    from app.celery.batch_task import batch_recover_task
    batch_recover_task.delay(batch_id, api_key)

    # 回傳空結果 — 前端透過輪詢等待結果出現在 DB
    return RecoverBatchResponse(batch_id=batch_id, files=[])


# ==================== Original Endpoints ====================

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
        multi_speaker=request_data.multi_speaker,
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
