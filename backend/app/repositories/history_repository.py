import uuid as _uuid_module
from typing import Optional, List, Tuple
from datetime import datetime

from sqlalchemy import or_, desc
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog, BatchJob


class HistoryRepository:
    """
    用於查詢歷史紀錄的 Repository。
    整合 TranscriptionLog 與 BatchJob 的資料。
    """

    def get_logs_paginated(
        self,
        db: Session,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        is_batch: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        keyword: Optional[str] = None,
    ) -> Tuple[List[TranscriptionLog], int]:
        """
        分頁查詢 TranscriptionLog，支援篩選。
        回傳 (結果列表, 總筆數)。
        """
        query = db.query(TranscriptionLog)

        if status:
            query = query.filter(TranscriptionLog.status == status)
        if is_batch is not None:
            query = query.filter(TranscriptionLog.is_batch == is_batch)
        if start_date:
            query = query.filter(TranscriptionLog.request_timestamp >= start_date)
        if end_date:
            query = query.filter(TranscriptionLog.request_timestamp <= end_date)
        if keyword:
            query = query.filter(
                or_(
                    TranscriptionLog.original_filename.ilike(f"%{keyword}%"),
                    TranscriptionLog.model_used.ilike(f"%{keyword}%"),
                )
            )

        total = query.count()
        results = (
            query.order_by(desc(TranscriptionLog.request_timestamp))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return results, total

    def _coerce_uuid(self, task_uuid):
        """確保 task_uuid 為 Python uuid.UUID 物件（相容 PostgreSQL 與 SQLite）。"""
        if isinstance(task_uuid, _uuid_module.UUID):
            return task_uuid
        try:
            return _uuid_module.UUID(str(task_uuid))
        except (ValueError, AttributeError):
            return None

    def get_log_by_uuid(self, db: Session, task_uuid) -> Optional[TranscriptionLog]:
        """根據 task_uuid 查詢單筆紀錄。"""
        uuid_val = self._coerce_uuid(task_uuid)
        if uuid_val is None:
            return None
        return db.query(TranscriptionLog).filter(
            TranscriptionLog.task_uuid == uuid_val
        ).first()

    def delete_log(self, db: Session, task_uuid) -> bool:
        """刪除單筆紀錄。"""
        uuid_val = self._coerce_uuid(task_uuid)
        if uuid_val is None:
            return False
        log = db.query(TranscriptionLog).filter(
            TranscriptionLog.task_uuid == uuid_val
        ).first()
        if log:
            db.delete(log)
            db.commit()
            return True
        return False

    def get_stats(self, db: Session) -> dict:
        """取得統計總覽。"""
        from sqlalchemy import func

        total = db.query(func.count(TranscriptionLog.task_uuid)).scalar() or 0
        completed = db.query(func.count(TranscriptionLog.task_uuid)).filter(
            TranscriptionLog.status == "COMPLETED"
        ).scalar() or 0
        failed = db.query(func.count(TranscriptionLog.task_uuid)).filter(
            TranscriptionLog.status == "FAILED"
        ).scalar() or 0
        total_cost = db.query(func.sum(TranscriptionLog.cost)).scalar() or 0.0
        total_tokens = db.query(func.sum(TranscriptionLog.total_tokens)).scalar() or 0
        total_duration = db.query(func.sum(TranscriptionLog.audio_duration_seconds)).scalar() or 0.0
        avg_processing_time = db.query(func.avg(TranscriptionLog.processing_time_seconds)).filter(
            TranscriptionLog.status == "COMPLETED"
        ).scalar() or 0.0

        return {
            "total_tasks": total,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "success_rate": round(completed / total * 100, 1) if total > 0 else 0,
            "total_cost": round(total_cost, 6),
            "total_tokens": total_tokens,
            "total_audio_duration_seconds": round(total_duration, 1),
            "avg_processing_time_seconds": round(avg_processing_time, 1),
        }
