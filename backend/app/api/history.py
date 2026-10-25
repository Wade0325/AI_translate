import math
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.task_status import TaskStatus
from app.database.models import TranscriptionLog
from app.database.session import get_db
from app.repositories.history_repository import HistoryRepository
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.services import audio_store
from app.schemas.schemas import (
    HistoryLogResponse,
    HistoryListResponse,
    HistoryStatsResponse,
    HistoryUsageResponse,
)
from app.services import output_format
from app.services.calculator.flows import MODEL_PRICES
from app.services.output_format import OutputFormat
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()
history_repo = HistoryRepository()
segment_repo = TranscriptSegmentRepository()

DOWNLOAD_MIME_TYPES = {
    OutputFormat.LRC: "text/plain; charset=utf-8",
    OutputFormat.SRT: "application/x-subrip; charset=utf-8",
    OutputFormat.VTT: "text/vtt; charset=utf-8",
    OutputFormat.TXT: "text/plain; charset=utf-8",
}


def _log_to_response(log: TranscriptionLog) -> HistoryLogResponse:
    return HistoryLogResponse(
        task_uuid=str(log.task_uuid),
        # isoformat（'T' 分隔）才能被所有瀏覽器的 new Date() 解析；str() 的空格分隔在 Safari 會變 Invalid Date
        request_timestamp=log.request_timestamp.isoformat() if log.request_timestamp else None,
        completed_at=log.completed_at.isoformat() if log.completed_at else None,
        status=log.status,
        original_filename=log.original_filename,
        audio_duration_seconds=log.audio_duration_seconds,
        model_used=log.model_used,
        source_language=log.source_language,
        total_tokens=log.total_tokens,
        cost=log.cost,
        error_message=log.error_message,
        is_batch=log.is_batch,
        session_id=log.session_id,
        file_uid=log.file_uid,
        service_tier_used=log.service_tier_used,
    )


def _download_filename(original_filename: Optional[str], fmt: str) -> str:
    stem = Path(original_filename or "transcript").stem
    return f"{stem}.{fmt}"


@router.get("/stats", response_model=HistoryStatsResponse)
def get_history_stats(db: Session = Depends(get_db)):
    """取得歷史紀錄統計總覽"""
    stats = history_repo.get_stats(db)
    return HistoryStatsResponse(**stats)


@router.get("/usage", response_model=HistoryUsageResponse)
def get_history_usage(
    days: int = Query(180, ge=1, le=366, description="彙總最近多少天的用量"),
    db: Session = Depends(get_db),
):
    """
    Dashboard / Billing 頁的用量彙總：每日與各模型的 tokens / 費用 / 檔案數，
    並附上模型計費表（來源為後端 MODEL_PRICES，避免前端寫死過時價格）。
    """
    usage = history_repo.get_usage(db, days=days)
    pricing = [
        {
            "model": name,
            "input_text": price.input_text,
            "input_audio": price.input_audio,
            "output_text": price.output_text,
        }
        for name, price in MODEL_PRICES.items()
        if name != "default"
    ]
    return HistoryUsageResponse(**usage, pricing=pricing)


@router.get("/active", response_model=list[HistoryLogResponse])
def get_active_single_tasks(
    hours: int = Query(6, ge=1, le=72, description="顯示最近多少小時內已完成/失敗的單檔任務"),
    db: Session = Depends(get_db),
):
    """
    取得「Task 頁面」要顯示的單檔轉錄活躍紀錄：
      - 進行中：所有 PROCESSING 的單檔任務
      - 已完成/失敗：最近 hours 小時內

    屬於批次的任務不包含在此（已由 GET /api/v1/batch/tasks 提供）。
    """
    logs = history_repo.get_active_single_tasks(db, recent_hours=hours)
    return [_log_to_response(log) for log in logs]


@router.get("", response_model=HistoryListResponse)
def get_history(
    page: int = Query(1, ge=1, description="頁碼"),
    page_size: int = Query(20, ge=1, le=100, description="每頁筆數"),
    status: Optional[str] = Query(None, description="篩選狀態 (COMPLETED/FAILED/PROCESSING)"),
    is_batch: Optional[bool] = Query(None, description="篩選是否屬於批次"),
    keyword: Optional[str] = Query(None, description="搜尋關鍵字 (檔名/模型)"),
    db: Session = Depends(get_db),
):
    """分頁查詢歷史紀錄"""
    logs, total = history_repo.get_logs_paginated(
        db,
        page=page,
        page_size=page_size,
        status=status,
        is_batch=is_batch,
        keyword=keyword,
    )

    items = [_log_to_response(log) for log in logs]
    total_pages = math.ceil(total / page_size) if total > 0 else 1

    return HistoryListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{task_uuid}", response_model=HistoryLogResponse)
def get_history_detail(task_uuid: str, db: Session = Depends(get_db)):
    """查詢單筆歷史紀錄詳情"""
    log = history_repo.get_log_by_uuid(db, task_uuid)
    if not log:
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")
    return _log_to_response(log)


@router.get("/{task_uuid}/download/{fmt}")
def download_transcript(
    task_uuid: str,
    fmt: str,
    db: Session = Depends(get_db),
):
    """下載任務的一種輸出格式（原始轉錄），內容由輸出格式模組產生。"""
    fmt = fmt.lower()
    try:
        output = OutputFormat(fmt)
    except ValueError:
        available = ", ".join(sorted(f.value for f in OutputFormat))
        raise HTTPException(
            status_code=400, detail=f"不支援的格式: {fmt}，可用: {available}") from None

    log = history_repo.get_log_by_uuid(db, task_uuid)
    if not log:
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")
    if log.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任務尚未完成，無法下載轉錄結果")

    content = output_format.for_task(db, log, output)
    if content is None:
        raise HTTPException(status_code=404, detail="此任務沒有儲存的轉錄結果")
    if not content.strip():
        raise HTTPException(status_code=404, detail="無法產生此格式的字幕內容")

    filename = _download_filename(log.original_filename, fmt)
    return Response(
        content=content,
        media_type=DOWNLOAD_MIME_TYPES[output],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.delete("/{task_uuid}")
def delete_history(task_uuid: str, db: Session = Depends(get_db)):
    """刪除單筆歷史紀錄，連帶清掉結構化片段與保留音檔。

    SQLite 預設不強制外鍵，所以片段不能只靠 ON DELETE CASCADE，這裡明確刪除。
    """
    log = history_repo.get_log_by_uuid(db, task_uuid)
    if not log:
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")

    audio_filename = log.audio_filename
    segment_repo.delete_for_task(db, task_uuid)
    if not history_repo.delete_log(db, task_uuid):
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")
    if audio_filename:
        audio_store.delete(audio_filename)
    return {"success": True, "message": "已刪除此紀錄"}
