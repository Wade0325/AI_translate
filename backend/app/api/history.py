import math
from pathlib import Path
from typing import Optional, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.task_status import TaskStatus
from app.database.models import TranscriptionLog
from app.database.session import get_db
from app.repositories.correction_repository import CorrectionRepository
from app.repositories.history_repository import HistoryRepository
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.services import audio_store, correctability
from app.schemas.schemas import (
    HistoryLogResponse,
    HistoryListResponse,
    HistoryStatsResponse,
    HistoryUsageResponse,
)
from app.services import output_format
from app.services.calculator.flows import MODEL_PRICES
from app.services.output_format import OutputFormat, Version
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


def _log_to_response(log: TranscriptionLog, *, correctable: bool, has_corrections: bool) -> HistoryLogResponse:
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
        error_code=cast(Optional[str], log.error_code),
        error_message=log.error_message,
        is_batch=log.is_batch,
        session_id=log.session_id,
        file_uid=log.file_uid,
        service_tier_used=log.service_tier_used,
        tail_loss_from_seconds=cast(Optional[float], log.tail_loss_from_seconds),
        correctable=correctable,
        has_corrections=has_corrections,
    )


def _with_correction_state(db: Session, logs: list[TranscriptionLog]) -> list[HistoryLogResponse]:
    """任務紀錄的回應，各帶能不能校正（app.services.correctability）與有沒有校正紀錄；有沒有片段、
    有沒有校正紀錄各一次查完。"""
    task_uuids = [log.task_uuid for log in logs]
    with_segments = segment_repo.tasks_with_segments(db, task_uuids)
    with_records = CorrectionRepository.tasks_with_records(db, task_uuids)
    return [
        _log_to_response(
            log,
            correctable=correctability.reason(log, has_segments=str(log.task_uuid) in with_segments) is None,
            has_corrections=str(log.task_uuid) in with_records,
        )
        for log in logs
    ]


def _download_filename(original_filename: Optional[str], fmt: str, version: Version) -> str:
    """下載的檔名：音檔的主檔名換上輸出格式的副檔名。原始轉錄多一段 ``.original``（#346），例如
    ``會議.srt`` 是校正後版本、``會議.original.srt`` 是原始轉錄，放在同一個資料夾不會搞混。"""
    stem = Path(original_filename or "transcript").stem
    marker = ".original" if version is Version.ORIGINAL else ""
    return f"{stem}{marker}.{fmt}"


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
    Billing 頁與轉錄頁費用估算的用量彙總：每日與各模型的 tokens / 費用 / 檔案數，
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
    return _with_correction_state(db, logs)


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

    items = _with_correction_state(db, logs)
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
    return _with_correction_state(db, [log])[0]


@router.get("/{task_uuid}/download/{fmt}")
def download_transcript(
    task_uuid: str,
    fmt: str,
    version: Version = Query(Version.CORRECTED, description="corrected（校正後版本，預設）或 original（原始轉錄）"),
    db: Session = Depends(get_db),
):
    """下載任務的一種輸出格式，內容由輸出格式模組產生（#346）。

    預設給校正後版本；``version=original`` 給原始轉錄，檔名多一段 ``.original``。沒有校正的任務、沒有片段的
    舊任務（不能校正），兩個版本的內容相同。
    """
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

    content = output_format.for_task(db, log, output, version)
    if content is None:
        raise HTTPException(status_code=404, detail="此任務沒有儲存的轉錄結果")
    if not content.strip():
        raise HTTPException(status_code=404, detail="無法產生此格式的字幕內容")

    filename = _download_filename(log.original_filename, fmt, version)
    return Response(
        content=content,
        media_type=DOWNLOAD_MIME_TYPES[output],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.delete("/{task_uuid}")
def delete_history(task_uuid: str, db: Session = Depends(get_db)):
    """刪除單筆歷史紀錄，連帶清掉結構化片段、校正紀錄與保留音檔。

    SQLite 預設不強制外鍵，所以片段與校正紀錄不能只靠 ON DELETE CASCADE，這裡明確刪除。三者在
    同一個交易裡刪（刪任務紀錄時一起 commit）：任務紀錄刪不掉時，校正不會先不見（ADR 0007）。
    """
    log = history_repo.get_log_by_uuid(db, task_uuid)
    if not log:
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")

    audio_filename = log.audio_filename
    CorrectionRepository.delete_for_task(db, task_uuid, commit=False)
    segment_repo.delete_for_task(db, task_uuid, commit=False)
    if not history_repo.delete_log(db, task_uuid):
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")
    if audio_filename:
        audio_store.delete(audio_filename)
    return {"success": True, "message": "已刪除此紀錄"}
