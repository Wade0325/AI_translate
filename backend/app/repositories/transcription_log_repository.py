import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.error_codes import ErrorCode
from app.core.task_status import TaskStatus
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

        Celery 任務被重派（redelivered）時會以相同 task_uuid 再執行一次，
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
        log_to_update = self.get(db, task_uuid)
        if log_to_update:
            for key, value in update_data.items():
                setattr(log_to_update, key, value)
            db.commit()
            db.refresh(log_to_update)
            return log_to_update
        return None

    def get(self, db: Session, task_uuid) -> Optional[TranscriptionLog]:
        uuid_val = self._coerce_task_uuid(task_uuid)
        if uuid_val is None:
            return None
        return db.query(TranscriptionLog).filter(
            TranscriptionLog.task_uuid == uuid_val).first()

    def current_status(self, db: Session, task_uuid) -> Optional[str]:
        """這筆紀錄在資料庫裡現在的狀態；沒有紀錄時回 None。

        直接查欄位，不經過 session 裡已經載入的物件：別的 session（例如取消端點）
        改了狀態，已經載入的物件不會自己更新。
        """
        uuid_val = self._coerce_task_uuid(task_uuid)
        if uuid_val is None:
            return None
        return db.query(TranscriptionLog.status).filter(
            TranscriptionLog.task_uuid == uuid_val).scalar()

    def update_log_unless_cancelled(
        self, db: Session, task_uuid, update_data: Dict[str, Any], *, commit: bool = True
    ) -> bool:
        """紀錄不是已取消時更新，回傳是否有更新（沒有紀錄或已取消時回 False）。

        任務記下結果用：使用者取消之後（取消端點已經記成 CANCELLED），任務才跑完或失敗，
        不能把取消蓋掉；其他狀態照實改寫，例如啟動清掃把還在跑的任務當成中斷、記成
        FAILED，任務之後跑完就記成完成。

        ``commit=False`` 時只寫進目前的交易，由呼叫端連同其他寫入一起提交。
        """
        uuid_val = self._coerce_task_uuid(task_uuid)
        if uuid_val is None:
            return False
        updated = (
            db.query(TranscriptionLog)
            .filter(
                TranscriptionLog.task_uuid == uuid_val,
                TranscriptionLog.status.is_distinct_from(TaskStatus.CANCELLED),
            )
            .update(update_data, synchronize_session=False)
        )
        if updated and commit:
            db.commit()
        return bool(updated)

    def update_log_if_processing(
        self, db: Session, task_uuid, update_data: Dict[str, Any]
    ) -> bool:
        """僅當紀錄仍在 PROCESSING 時更新，回傳是否有更新。

        已經結束的紀錄不再改寫：例如取消端點已經記成 CANCELLED，任務之後才跑完，
        不能把它蓋回 COMPLETED。
        """
        uuid_val = self._coerce_task_uuid(task_uuid)
        if uuid_val is None:
            return False
        updated = (
            db.query(TranscriptionLog)
            .filter(
                TranscriptionLog.task_uuid == uuid_val,
                TranscriptionLog.status == TaskStatus.PROCESSING,
            )
            .update(update_data, synchronize_session=False)
        )
        if updated:
            db.commit()
        return bool(updated)

    def mark_cancelled_if_processing(self, db: Session, task_uuid) -> bool:
        """僅當紀錄仍在 PROCESSING 時標記為 CANCELLED，回傳是否有更新。

        供取消端點使用：被 revoke/terminate 掉的任務不會再回報狀態，
        由端點直接補寫；條件式更新避免與剛完成的任務競爭時覆寫結果。
        """
        return self.update_log_if_processing(db, task_uuid, {
            "status": TaskStatus.CANCELLED,
            "error_message": "使用者取消任務",
            "completed_at": datetime.now(),
        })

    def mark_stale_processing_failed(self, db: Session, max_age_hours: int) -> int:
        """把卡在 PROCESSING 超過 max_age_hours 的單檔紀錄標記為 FAILED，回傳筆數。

        worker 行程中途被終止（斷電、手動砍掉）不會回來更新狀態，這類紀錄
        會永遠顯示「處理中」。批次有自己的 recover 機制，不在此處理。
        """
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        updated = (
            db.query(TranscriptionLog)
            .filter(
                TranscriptionLog.is_batch.isnot(True),
                TranscriptionLog.status == TaskStatus.PROCESSING,
                TranscriptionLog.request_timestamp < cutoff,
            )
            .update(
                {
                    TranscriptionLog.status: TaskStatus.FAILED,
                    TranscriptionLog.error_code: ErrorCode.INTERRUPTED,
                    TranscriptionLog.error_message:
                        f"超過 {max_age_hours} 小時仍在處理中，轉錄途中程式可能關閉或重新啟動了",
                    TranscriptionLog.completed_at: datetime.now(),
                },
                synchronize_session=False,
            )
        )
        if updated:
            db.commit()
        return updated
