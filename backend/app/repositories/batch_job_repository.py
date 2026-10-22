from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.batch_state import ALLOWED_FROM, IN_PROGRESS, BatchState
from app.database.models import BatchFile, BatchJob
from app.utils.identifiers import coerce_uuid


class BatchJobRepository:
    """
    用於處理 batch_jobs 與 batch_files 資料表資料庫操作的 Repository：批次紀錄，以及它每個檔案的一列。

    批次的狀態只經由 :meth:`move` 改變（狀態機見 :mod:`app.core.batch_state`）。寫入預設馬上提交；
    ``commit=False`` 時只寫進目前的交易，由呼叫端連同其他寫入一起提交。
    """

    def create_job(self, db: Session, job: BatchJob, files: Sequence[BatchFile]) -> None:
        """建立批次紀錄（上傳中）與它每個檔案的一列，同一個交易。

        同一個批次 id 已經有紀錄時拋 IntegrityError，什麼都不寫。
        """
        job.status = BatchState.UPLOADING
        db.add(job)
        # 先寫批次紀錄：檔案的列參照它
        db.flush()
        db.add_all(files)
        db.commit()

    def update_job(self, db: Session, batch_id: str, update_data: Dict[str, Any], *,
                   commit: bool = True) -> Optional[BatchJob]:
        """
        根據 batch_id 更新一筆現有的批次記錄；狀態改用 :meth:`move`。
        """
        job = db.query(BatchJob).filter(BatchJob.batch_id == batch_id).first()
        if job:
            for key, value in update_data.items():
                setattr(job, key, value)
            if commit:
                db.commit()
                db.refresh(job)
            return job
        return None

    def move(self, db: Session, batch_id: str, to: BatchState, *,
             only_from: Optional[Iterable[BatchState]] = None, commit: bool = True) -> bool:
        """批次的狀態改成 ``to``，回傳有沒有改：資料庫裡現在的狀態是可以改過來的狀態之一
        （:data:`~app.core.batch_state.ALLOWED_FROM`，``only_from`` 再縮小範圍）時才改。

        直接以條件更新，不經過 session 裡已經載入的物件：別的行程（API、另一個 worker）可能剛改了
        狀態，已經載入的物件不會自己更新。
        """
        allowed = ALLOWED_FROM[to]
        if only_from is not None:
            allowed = allowed & frozenset(only_from)
        moved = (
            db.query(BatchJob)
            .filter(BatchJob.batch_id == batch_id, BatchJob.status.in_(allowed))
            .update({BatchJob.status: to}, synchronize_session=False)
        )
        if commit:
            db.commit()
        return bool(moved)

    def get_job(self, db: Session, batch_id: str) -> Optional[BatchJob]:
        """
        依 batch_id 查詢單筆記錄。
        """
        return db.query(BatchJob).filter(BatchJob.batch_id == batch_id).first()

    def files(self, db: Session, batch_id: str) -> List[BatchFile]:
        """批次裡的每個檔案，依在批次裡的順序。"""
        return self.files_of(db, [batch_id]).get(batch_id, [])

    def files_of(self, db: Session, batch_ids: Sequence[str]) -> Dict[str, List[BatchFile]]:
        """幾個批次各自的檔案（依在批次裡的順序），以 batch_id 為 key；沒有檔案的批次不在裡面。"""
        if not batch_ids:
            return {}
        rows = (
            db.query(BatchFile)
            .filter(BatchFile.batch_id.in_(batch_ids))
            .order_by(BatchFile.batch_id, BatchFile.seq)
            .all()
        )
        grouped: Dict[str, List[BatchFile]] = defaultdict(list)
        for row in rows:
            grouped[row.batch_id].append(row)
        return dict(grouped)

    def update_file(self, db: Session, task_uuid, update_data: Dict[str, Any], *,
                    commit: bool = True) -> bool:
        """更新一個檔案的列（以它的任務紀錄 id 找），回傳有沒有這一列。"""
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return False
        updated = (
            db.query(BatchFile)
            .filter(BatchFile.task_uuid == uuid_val)
            .update(update_data, synchronize_session=False)
        )
        if commit:
            db.commit()
        return bool(updated)

    def get_active_tasks(self, db: Session) -> List[BatchJob]:
        """
        取得活躍的批次（Task 頁面用）：
        - 所有進行中/待取回的批次（上傳中、輪詢中、復原中、完成）
        - 24 小時內失敗的批次：送出過的可以從任務頁恢復
        - 24 小時內已取回的批次，供使用者確認和下載
        """
        cutoff = datetime.now() - timedelta(hours=24)  # created_at/updated_at 為 DB 本地時間
        return (
            db.query(BatchJob)
            .filter(
                or_(
                    BatchJob.status.in_(IN_PROGRESS | {BatchState.COMPLETED}),
                    and_(
                        BatchJob.status.in_({BatchState.FAILED, BatchState.RETRIEVED}),
                        BatchJob.updated_at >= cutoff,
                    ),
                )
            )
            .order_by(BatchJob.created_at.desc())
            .all()
        )

    def archive_old_completed(self, db: Session) -> int:
        """
        將已完成超過 24 小時的批次歸檔（已取回）。
        回傳受影響的筆數。
        """
        cutoff = datetime.now() - timedelta(hours=24)  # created_at/updated_at 為 DB 本地時間
        count = db.query(BatchJob).filter(
            BatchJob.status == BatchState.COMPLETED,
            BatchJob.updated_at < cutoff,
        ).update({BatchJob.status: BatchState.RETRIEVED}, synchronize_session=False)
        db.commit()
        return count

    def mark_as_retrieved(self, db: Session, batch_id: str) -> bool:
        """將指定批次歸檔（使用者取回結果或手動歸檔）；找不到批次時回 False。"""
        return self.move(db, batch_id, BatchState.RETRIEVED)
