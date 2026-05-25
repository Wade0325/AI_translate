import uuid
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.database.models import TranscriptionLog


class TranscriptionLogRepository:
    """
    用於處理 transcription_logs 資料表資料庫操作的 Repository。
    """

    @staticmethod
    def _coerce_task_uuid(task_uuid) -> Optional[uuid.UUID]:
        if isinstance(task_uuid, uuid.UUID):
            return task_uuid
        try:
            return uuid.UUID(str(task_uuid))
        except (ValueError, AttributeError, TypeError):
            return None

    def insert_log(self, db: Session, initial_data: Dict[str, Any]) -> TranscriptionLog:
        """
        在資料庫中建立一筆新的轉錄日誌。

        :param db: SQLAlchemy Session.
        :param initial_data: 包含日誌初始資料的字典。
        :return: 新建立的 TranscriptionLog ORM 物件。
        """
        data = dict(initial_data)
        if "task_uuid" in data:
            coerced = self._coerce_task_uuid(data["task_uuid"])
            if coerced is not None:
                data["task_uuid"] = coerced
        new_log = TranscriptionLog(**data)
        db.add(new_log)
        db.commit()
        db.refresh(new_log)
        return new_log

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
