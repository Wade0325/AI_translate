import math
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog
from app.database.session import get_db
from app.repositories.history_repository import HistoryRepository
from app.schemas.schemas import (
    HistoryLogResponse,
    HistoryListResponse,
    HistoryStatsResponse,
)
from app.services.converter.service import convert_from_lrc
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()
history_repo = HistoryRepository()

VALID_DOWNLOAD_FORMATS = frozenset({"lrc", "srt", "vtt", "txt"})
DOWNLOAD_MIME_TYPES = {
    "lrc": "text/plain; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}


def _log_to_response(log: TranscriptionLog, db: Session) -> HistoryLogResponse:
    return HistoryLogResponse(
        task_uuid=str(log.task_uuid),
        request_timestamp=str(log.request_timestamp) if log.request_timestamp else None,
        completed_at=str(log.completed_at) if log.completed_at else None,
        status=log.status,
        original_filename=log.original_filename,
        audio_duration_seconds=log.audio_duration_seconds,
        processing_time_seconds=log.processing_time_seconds,
        model_used=log.model_used,
        provider=log.provider,
        source_language=log.source_language,
        target_language=log.target_language,
        total_tokens=log.total_tokens,
        cost=log.cost,
        error_message=log.error_message,
        is_batch=log.is_batch,
        batch_id=log.batch_id,
        has_transcript=history_repo.has_transcript(db, log),
        session_id=log.session_id,
        file_uid=log.file_uid,
    )


def _transcript_content(lrc_text: str, fmt: str) -> str:
    """由 DB 中的 LRC 產生指定格式的字幕內容。"""
    if fmt == "lrc":
        return lrc_text
    converted = convert_from_lrc(lrc_text)
    return getattr(converted, fmt, "") or ""


def _download_filename(original_filename: Optional[str], fmt: str) -> str:
    stem = Path(original_filename or "transcript").stem
    return f"{stem}.{fmt}"


@router.get("/stats", response_model=HistoryStatsResponse)
def get_history_stats(db: Session = Depends(get_db)):
    """取得歷史紀錄統計總覽"""
    stats = history_repo.get_stats(db)
    return HistoryStatsResponse(**stats)


@router.get("/active", response_model=list[HistoryLogResponse])
def get_active_single_tasks(
    hours: int = Query(6, ge=1, le=72, description="顯示最近多少小時內已完成/失敗的單檔任務"),
    db: Session = Depends(get_db),
):
    """
    取得「Task 頁面」要顯示的單檔轉錄活躍紀錄：
      - 進行中：所有 PROCESSING 的單檔任務
      - 已完成/失敗：最近 hours 小時內

    批次任務不包含在此（已由 GET /api/v1/batch/tasks 提供）。
    """
    logs = history_repo.get_active_single_tasks(db, recent_hours=hours)
    return [_log_to_response(log, db) for log in logs]


@router.get("", response_model=HistoryListResponse)
def get_history(
    page: int = Query(1, ge=1, description="頁碼"),
    page_size: int = Query(20, ge=1, le=100, description="每頁筆數"),
    status: Optional[str] = Query(None, description="篩選狀態 (COMPLETED/FAILED/PROCESSING)"),
    is_batch: Optional[bool] = Query(None, description="篩選是否為批次任務"),
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

    items = [_log_to_response(log, db) for log in logs]
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
    return _log_to_response(log, db)


@router.get("/{task_uuid}/download/{fmt}")
def download_transcript(
    task_uuid: str,
    fmt: str,
    db: Session = Depends(get_db),
):
    """下載指定格式的字幕檔（由 DB 中的 LRC 即時轉換）。"""
    fmt = fmt.lower()
    if fmt not in VALID_DOWNLOAD_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的格式: {fmt}，可用: {', '.join(sorted(VALID_DOWNLOAD_FORMATS))}",
        )

    log = history_repo.get_log_by_uuid(db, task_uuid)
    if not log:
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")
    if log.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="任務尚未完成，無法下載字幕")
    lrc_text = history_repo.resolve_lrc_content(db, log, backfill=True)
    if not lrc_text:
        raise HTTPException(status_code=404, detail="此任務沒有儲存的轉錄結果")

    content = _transcript_content(lrc_text, fmt)
    if not content.strip():
        raise HTTPException(status_code=404, detail="無法產生此格式的字幕內容")

    filename = _download_filename(log.original_filename, fmt)
    return Response(
        content=content,
        media_type=DOWNLOAD_MIME_TYPES[fmt],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.delete("/{task_uuid}")
def delete_history(task_uuid: str, db: Session = Depends(get_db)):
    """刪除單筆歷史紀錄"""
    success = history_repo.delete_log(db, task_uuid)
    if not success:
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")
    return {"success": True, "message": "已刪除此紀錄"}
