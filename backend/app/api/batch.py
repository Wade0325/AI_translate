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

from app.celery.batch_task import batch_transcribe_task, _process_single_result
from app.celery.models import BatchTranscriptionTaskParams, BatchFileItemParams
from app.core.config import get_settings
from app.database.session import get_db
from app.provider.google.gemini import (
    GeminiClient,
    poll_batch_job_status,
    get_batch_job_state_name,
    BATCH_COMPLETED_STATES,
)
from app.repositories.batch_job_repository import BatchJobRepository
from app.repositories.transcription_log_repository import TranscriptionLogRepository
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
    """查詢未完成的批次任務（status=UPLOADING 或 POLLING）"""
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
    恢復指定批次任務：用前端提供的 API key 向 Gemini 查詢結果，
    並對每個檔案呼叫 _process_single_result() 處理。
    """
    job = batch_repo.get_job(db, batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到此批次任務")
    if not job.gemini_job_name:
        raise HTTPException(status_code=400, detail="此任務尚未建立 Gemini batch job，無法恢復")

    # 初始化 Gemini 客戶端
    client_wrapper = GeminiClient(body.api_keys)
    client = client_wrapper.client
    if not client:
        raise HTTPException(status_code=400, detail="API Key 無效，無法初始化 Gemini 客戶端")

    # 查詢 Gemini 批次任務狀態
    try:
        batch_job = poll_batch_job_status(client, job.gemini_job_name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"查詢 Gemini 批次任務失敗: {e}")

    state_name = get_batch_job_state_name(batch_job)

    # 若任務尚未完成，回傳當前狀態
    if state_name not in BATCH_COMPLETED_STATES:
        raise HTTPException(
            status_code=202,
            detail=f"Gemini 批次任務仍在進行中 (狀態: {state_name})，請稍後再試"
        )

    # 若任務失敗
    if state_name != "JOB_STATE_SUCCEEDED":
        batch_repo.update_job(db, batch_id, {"status": "FAILED"})
        raise HTTPException(status_code=500, detail=f"Gemini 批次任務失敗，狀態: {state_name}")

    # 解析 DB 中的映射資訊
    file_mapping = json.loads(job.file_mapping_json) if job.file_mapping_json else {}
    file_durations = json.loads(job.file_durations_json) if job.file_durations_json else {}
    file_log_uuids = json.loads(job.file_log_uuids_json) if job.file_log_uuids_json else {}
    task_params_data = json.loads(job.task_params_json) if job.task_params_json else {}

    # 建立輕量的 task_params 物件（供 _process_single_result 使用）
    task_params = SimpleNamespace(
        model=task_params_data.get("model", ""),
        provider=task_params_data.get("provider", "google"),
        source_lang=task_params_data.get("source_lang", ""),
        target_lang=task_params_data.get("target_lang"),
        prompt=task_params_data.get("prompt", ""),
    )

    log_repo = TranscriptionLogRepository()
    start_time = time.time()

    # 收集結果的列表
    file_results: list[RecoverFileResult] = []

    # 捕獲 update_fn 的結果（_process_single_result 透過此回呼傳遞結果）
    captured_results = {}

    def capture_update(*args, status_code="PROCESSING", result_data=None, file_uid=None, **kwargs):
        if file_uid and result_data and status_code == "COMPLETED":
            captured_results[file_uid] = result_data

    # 處理各檔案結果
    ordered_indices = sorted(file_mapping.keys(), key=int)

    if batch_job.dest and batch_job.dest.inlined_responses:
        for response_idx, inline_response in enumerate(batch_job.dest.inlined_responses):
            if response_idx >= len(ordered_indices):
                break

            idx_str = ordered_indices[response_idx]
            entry = file_mapping[idx_str]
            file_uid = entry["file_uid"]
            original_filename = entry["original_filename"]
            file_task_uuid = file_log_uuids.get(file_uid, "")
            audio_duration = file_durations.get(file_uid, 0.0)

            # 建立輕量 file_item
            file_item = SimpleNamespace(
                file_uid=file_uid,
                original_filename=original_filename,
            )

            try:
                _process_single_result(
                    inline_response=inline_response,
                    file_item=file_item,
                    task_params=task_params,
                    client=client,
                    file_task_uuid=file_task_uuid,
                    audio_duration=audio_duration,
                    start_time=start_time,
                    db=db,
                    log_repo=log_repo,
                    update_fn=capture_update,
                )
                result_data = captured_results.get(file_uid)
                file_results.append(RecoverFileResult(
                    file_uid=file_uid,
                    original_filename=original_filename,
                    status="COMPLETED" if result_data else "FAILED",
                    result=result_data,
                    error=None if result_data else "處理完成但未產生結果",
                ))
            except Exception as e:
                logger.error(f"恢復處理檔案 {original_filename} 失敗: {e}", exc_info=True)
                file_results.append(RecoverFileResult(
                    file_uid=file_uid,
                    original_filename=original_filename,
                    status="FAILED",
                    error=str(e),
                ))
    else:
        logger.warning(f"恢復批次 {batch_id}: 任務成功但沒有回傳結果")

    # 更新 DB 狀態
    batch_repo.update_job(db, batch_id, {"status": "COMPLETED"})

    return RecoverBatchResponse(batch_id=batch_id, files=file_results)


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
