from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy import or_, and_
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

    def get_job(self, db: Session, batch_id: str) -> Optional[BatchJob]:
        """
        依 batch_id 查詢單筆記錄。
        """
        return db.query(BatchJob).filter(BatchJob.batch_id == batch_id).first()

    def get_active_tasks(self, db: Session) -> List[BatchJob]:
        """
        取得活躍的批次任務（Task 頁面用）：
        - 所有進行中/待取回的任務（UPLOADING/POLLING/COMPLETED/RECOVERING）
        - 24 小時內已取回的任務（RETRIEVED），供用戶確認和下載
        """
        cutoff = datetime.now() - timedelta(hours=24)  # created_at/updated_at 為 DB 本地時間
        return (
            db.query(BatchJob)
            .filter(
                or_(
                    BatchJob.status.in_(["UPLOADING", "POLLING", "COMPLETED", "RECOVERING"]),
                    and_(
                        BatchJob.status == "RETRIEVED",
                        BatchJob.updated_at >= cutoff,
                    ),
                )
            )
            .order_by(BatchJob.created_at.desc())
            .all()
        )

    def archive_old_completed(self, db: Session) -> int:
        """
        將已完成超過 24 小時的批次標記為 RETRIEVED。
        回傳受影響的筆數。
        """
        cutoff = datetime.now() - timedelta(hours=24)  # created_at/updated_at 為 DB 本地時間
        count = db.query(BatchJob).filter(
            BatchJob.status == "COMPLETED",
            BatchJob.updated_at < cutoff,
        ).update({"status": "RETRIEVED"})
        db.commit()
        return count

    def mark_as_retrieved(self, db: Session, batch_id: str) -> bool:
        """將指定批次標記為 RETRIEVED（用戶手動忽略/歸檔）。"""
        job = self.get_job(db, batch_id)
        if job:
            job.status = "RETRIEVED"
            db.commit()
            return True
        return False
