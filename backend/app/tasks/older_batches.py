"""舊版送出的批次（#117）：#116 之前，批次的檔案清單、長度、任務紀錄 id 與去靜音區間存在批次紀錄的
四個 JSON 欄位裡，沒有 batch_files 的列。

應用程式啟動時（:func:`add_file_rows`）從舊欄位讀出，替這些批次補上每個檔案的列。之後它們和這一版
送出的批次沒有分別：復原、取回結果與任務頁的檔名都只讀 batch_files，走同一個狀態機
（:mod:`app.tasks.batch_core`），沒有第二份流程。舊欄位只讀不寫，保留一個版本；之後另開票刪掉它們時，
這個模組一起刪。

舊欄位的格式，兩種都讀得懂：

- ``file_mapping_json``：送出的檔案，``{key: {file_uid, original_filename, vad_segments[, file_path]}}``。
  key 是數字字串，依數字排序就是送出的順序：#115 之前是檔案在批次裡的位置（上傳失敗的不在裡面），
  之後是第幾個請求。``vad_segments`` 是去靜音保留下來的有聲段，和語音視圖的序列化形式同一個形狀，
  沒有去靜音時是 None；``file_path`` 是上傳檔，#115 之前沒有存。
- ``file_log_uuids_json``、``file_durations_json``：以 file_uid 為 key 的任務紀錄 id 與開始時量到的
  長度，依檔案在批次裡的順序寫入。#115 之前列出每個檔案（包括沒有送出的），之後只列送出的。
- 結果狀態沒有舊的對應，看任務紀錄。
"""

import json
import uuid
from typing import List, Optional

from sqlalchemy import exists
from sqlalchemy.orm import Session

from app.core.task_status import TaskStatus
from app.database.models import BatchFile, BatchJob, TranscriptionLog
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.services.silence_removal import SpeechTimeline
from app.tasks.lifecycle import without_db_details
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def add_file_rows(db: Session) -> int:
    """替還沒有列的舊版批次補上每個檔案的列，回傳補了幾個批次。應用程式每次啟動時呼叫；補過的批次
    有了列，之後不再動它。

    每個批次各自一個交易：讀不懂的（舊欄位不是預期的形狀）或寫不進去的只記 log、不補，不影響其他
    批次。沒補上列的批次從復原入口接手時會被拒絕（:func:`~app.tasks.batch_core.recovery_refusal`）。
    """
    older = (
        db.query(BatchJob.batch_id, BatchJob.file_mapping_json, BatchJob.file_durations_json,
                 BatchJob.file_log_uuids_json)
        .filter(BatchJob.file_mapping_json.isnot(None),
                ~exists().where(BatchFile.batch_id == BatchJob.batch_id))
        .all()
    )
    added = 0
    for batch_id, sent, durations, task_uuids in older:
        try:
            rows = _rows(db, batch_id, json.loads(sent), json.loads(durations or "{}"),
                         json.loads(task_uuids or "{}"))
            if not rows:
                logger.warning(f"舊版送出的批次 {batch_id} 沒有記下任務紀錄 id，不補列")
                continue
            db.add_all(rows)
            db.commit()
            added += 1
        except Exception as e:
            db.rollback()
            logger.warning(f"舊版送出的批次 {batch_id} 沒有補上列: {without_db_details(e)!r}")
    return added


def _rows(db: Session, batch_id: str, sent: dict, durations: dict,
          task_uuids: dict) -> List[BatchFile]:
    """一個舊版批次每個檔案的列，依檔案在批次裡的順序；沒有任務紀錄 id 的檔案沒有列。"""
    requests = {
        entry["file_uid"]: (request_index, entry)
        for request_index, (_, entry) in enumerate(
            sorted(sent.items(), key=lambda item: int(item[0])))
    }
    records = TranscriptionLogRepository()
    rows = []
    for seq, (file_uid, task_uuid) in enumerate(task_uuids.items()):
        request_index, entry = requests.get(file_uid, (None, None))
        record = records.get(db, task_uuid)
        duration = durations.get(file_uid)
        rows.append(BatchFile(
            task_uuid=uuid.UUID(task_uuid),
            batch_id=batch_id,
            seq=seq,
            file_uid=file_uid,
            original_filename=((entry or {}).get("original_filename")
                               or (record.original_filename if record else None) or file_uid),
            file_path=(entry or {}).get("file_path"),
            audio_duration_seconds=None if duration is None else float(duration),
            speech_view_json=None if entry is None else json.dumps(
                SpeechTimeline.from_serialized(entry.get("vad_segments")).serialized()),
            request_index=request_index,
            status=_result_status(record),
        ))
    return rows


def _result_status(record: Optional[TranscriptionLog]) -> TaskStatus:
    """舊版沒有記結果狀態，照任務紀錄：完成或還在處理中的照記，其他（失敗、紀錄不在了）是失敗。"""
    if record is not None and record.status in (TaskStatus.COMPLETED, TaskStatus.PROCESSING):
        return TaskStatus(record.status)
    return TaskStatus.FAILED
