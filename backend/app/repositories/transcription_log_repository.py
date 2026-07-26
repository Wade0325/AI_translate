import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.database.models import TranscriptionLog
from app.utils.identifiers import coerce_uuid


class TranscriptionLogRepository:
    """
    用於處理 transcription_logs 資料表資料庫操作的 Repository。
    """

    @staticmethod
    def _coerce_task_uuid(task_uuid) -> Optional[uuid.UUID]:
        return coerce_uuid(task_uuid)

    def insert_log(self, db: Session, initial_data: Dict[str, Any]) -> TranscriptionLog:
        """建立轉錄日誌；同 task_uuid 已存在時改為覆寫（upsert）。

        Celery 任務被重派（redelivered）時會以相同 task_uuid 重跑，
        單純 insert 會撞主鍵並讓紀錄永遠卡在 PROCESSING。
        """
        data = dict(initial_data)
        if "task_uuid" in data:
            coerced = self._coerce_task_uuid(data["task_uuid"])
            if coerced is not None:
                data["task_uuid"] = coerced

        existing = None
        if data.get("task_uuid") is not None:
            existing = db.query(TranscriptionLog).filter(
                TranscriptionLog.task_uuid == data["task_uuid"]).first()

        if existing:
            for key, value in data.items():
                setattr(existing, key, value)
            log = existing
        else:
            log = TranscriptionLog(**data)
            db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def update_log(self, db: Session, task_uuid: uuid.UUID, update_data: Dict[str, Any]) -> Optional[TranscriptionLog]:
        """
        根據 ID 更新一筆現有的轉錄日誌。

        :param db: SQLAlchemy Session.
        :param task_uuid: 要更新的日誌的 UUID。
        :param update_data: 包含要更新欄位和值的字典。
        :return: 更新後的 TranscriptionLog ORM 物件，如果找不到則返回 None。
        """
        uuid_val = self._coerce_task_uuid(task_uuid)
        if uuid_val is None:
            return None
        log_to_update = db.query(TranscriptionLog).filter(
            TranscriptionLog.task_uuid == uuid_val).first()
        if log_to_update:
            for key, value in update_data.items():
                setattr(log_to_update, key, value)
            db.commit()
            db.refresh(log_to_update)
            return log_to_update
        return None

    def mark_cancelled_if_processing(self, db: Session, task_uuid) -> bool:
        """僅當紀錄仍在 PROCESSING 時標記為 CANCELLED，回傳是否有更新。

        供取消端點使用：被 revoke/terminate 掉的任務不會再回報狀態，
        由端點直接補寫；條件式更新避免與剛完成的任務競爭時覆寫結果。
        """
        uuid_val = self._coerce_task_uuid(task_uuid)
        if uuid_val is None:
            return False
        updated = (
            db.query(TranscriptionLog)
            .filter(
                TranscriptionLog.task_uuid == uuid_val,
                TranscriptionLog.status == "PROCESSING",
            )
            .update(
                {
                    TranscriptionLog.status: "CANCELLED",
                    TranscriptionLog.error_message: "使用者取消任務",
                    TranscriptionLog.completed_at: datetime.now(),
                },
                synchronize_session=False,
            )
        )
        if updated:
            db.commit()
        return bool(updated)

    def mark_stale_processing_failed(self, db: Session, max_age_hours: int) -> int:
        """把卡在 PROCESSING 超過 max_age_hours 的單檔紀錄標記為 FAILED，回傳筆數。

        worker 行程中途被終止（斷電、手動砍掉）不會回來更新狀態，這類紀錄
        會永遠顯示「處理中」。批次任務有自己的 recover 機制，不在此處理。
        """
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        updated = (
            db.query(TranscriptionLog)
            .filter(
                TranscriptionLog.is_batch.isnot(True),
                TranscriptionLog.status == "PROCESSING",
                TranscriptionLog.request_timestamp < cutoff,
            )
            .update(
                {
                    TranscriptionLog.status: "FAILED",
                    TranscriptionLog.error_message:
                        f"任務逾時未完成（超過 {max_age_hours} 小時，worker 可能已中斷），"
                        "由啟動清掃標記為失敗",
                    TranscriptionLog.completed_at: datetime.now(),
                },
                synchronize_session=False,
            )
        )
        if updated:
            db.commit()
        return updated
