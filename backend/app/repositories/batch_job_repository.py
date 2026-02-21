from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from app.database.models import BatchJob


class BatchJobRepository:
    """
    用於處理 batch_jobs 資料表資料庫操作的 Repository。
    """

    def create_job(self, db: Session, batch_id: str, task_params_json: str) -> BatchJob:
        """
        建立一筆新的批次任務記錄 (status=UPLOADING)。
        """
        new_job = BatchJob(
            batch_id=batch_id,
            task_params_json=task_params_json,
            status="UPLOADING",
        )
        db.add(new_job)
        db.commit()
        db.refresh(new_job)
        return new_job

    def update_job(self, db: Session, batch_id: str, update_data: Dict[str, Any]) -> Optional[BatchJob]:
        """
        根據 batch_id 更新一筆現有的批次任務記錄。
        """
        job = db.query(BatchJob).filter(BatchJob.batch_id == batch_id).first()
        if job:
            for key, value in update_data.items():
                setattr(job, key, value)
            db.commit()
            db.refresh(job)
            return job
        return None

    def get_pending_jobs(self, db: Session) -> List[BatchJob]:
        """
        查詢 status 為 UPLOADING 或 POLLING 的未完成任務。
        """
        return db.query(BatchJob).filter(
            BatchJob.status.in_(["UPLOADING", "POLLING"])
        ).all()

    def get_job(self, db: Session, batch_id: str) -> Optional[BatchJob]:
        """
        依 batch_id 查詢單筆記錄。
        """
        return db.query(BatchJob).filter(BatchJob.batch_id == batch_id).first()
