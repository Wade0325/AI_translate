import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.repositories.history_repository import HistoryRepository
from app.schemas.schemas import (
    HistoryLogResponse,
    HistoryListResponse,
    HistoryStatsResponse,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()
history_repo = HistoryRepository()


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
    return [
        HistoryLogResponse(
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
        )
        for log in logs
    ]


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

    items = []
    for log in logs:
        items.append(HistoryLogResponse(
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
        ))

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
    )


@router.delete("/{task_uuid}")
def delete_history(task_uuid: str, db: Session = Depends(get_db)):
    """刪除單筆歷史紀錄"""
    success = history_repo.delete_log(db, task_uuid)
    if not success:
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")
    return {"success": True, "message": "已刪除此紀錄"}
