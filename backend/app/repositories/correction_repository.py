"""校正紀錄的資料庫操作，以及校正後版本的算法（#340，ADR 0011）。

片段存的是原始轉錄，寫入後不再改；每一次校正另存一筆校正紀錄（``CorrectionRecord``），只增不改。
校正後版本不另外存，由原始轉錄套上最新的校正紀錄算出來：

1. 一個片段在校正後版本裡的文字，是它最新一筆「文字」紀錄的改後；沒有紀錄就是原始轉錄。說話者同理。
2. 刪掉片段是一筆「文字」紀錄，改後是空字串。文字是空的片段就是刪掉的片段。還原是再記一筆。
3. 一個說話者編號現在的名稱，是它最新一筆「說話者名稱」紀錄的改後；空的就是沒有名稱。
4. 和現在的內容相同的校正不記。
5. 校正紀錄寫入後不改、不刪，只有刪掉整個任務時一起刪。

「最新」看紀錄的編號（自動遞增的 ``id``），不看時間。下載、校正頁與匯出都從
:meth:`CorrectionRepository.corrected_version` 讀，不各寫各的。

確認狀態（``review_state``）留在片段上，不是校正，不進校正紀錄。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from sqlalchemy.orm import Session

from app.database.models import CorrectionRecord, TranscriptSegment
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.utils.identifiers import coerce_uuid


class CorrectionField(StrEnum):
    """校正改了什麼。v0.2 的校正只有這幾種（刪掉片段是文字改成空字串）。"""

    TEXT = "text"
    SPEAKER = "speaker"
    SPEAKER_NAME = "speaker_name"
    """對象是說話者編號，不是片段。"""


@dataclass(frozen=True)
class Correction:
    """一次操作裡的一筆校正：把 ``target`` 的 ``field`` 改成 ``new_value``。

    ``target`` 是片段的 ``seg_key``；``field`` 是說話者名稱時是說話者編號（例如 ``S0``）。
    改前由 repository 從現在的內容讀，不由呼叫的人傳。
    """

    target: str
    field: CorrectionField
    new_value: Optional[str]


_Key = Tuple[str, str]
"""(field, target)"""


def _normalized(field: str, value: Optional[str]) -> Optional[str]:
    """文字與說話者名稱的「沒有」一律是空字串；說話者照原樣（原始轉錄可能沒有說話者）。"""
    if field == CorrectionField.SPEAKER:
        return value
    return value or ""


def _original(field: str, segment: Optional[TranscriptSegment]) -> Optional[str]:
    """沒有校正紀錄時的內容：片段的原始轉錄；說話者名稱是沒有名稱。"""
    if segment is None:
        return _normalized(field, None)
    if field == CorrectionField.TEXT:
        return _normalized(field, cast(Optional[str], segment.text))
    return _normalized(field, cast(Optional[str], segment.speaker))


def _task_uuid(task_uuid) -> uuid.UUID:
    value = coerce_uuid(task_uuid)
    if value is None:
        raise ValueError("task_uuid 格式不正確")
    return value


def _records(db: Session, task_uuid: uuid.UUID) -> List[CorrectionRecord]:
    return (
        db.query(CorrectionRecord)
        .filter(CorrectionRecord.task_uuid == task_uuid)
        .order_by(CorrectionRecord.id)
        .all()
    )


def _latest(records: Sequence[CorrectionRecord]) -> Dict[_Key, CorrectionRecord]:
    """每個 (field, target) 最新的一筆；records 依編號排序。"""
    return {(str(r.field), str(r.target)): r for r in records}


def _old(record: CorrectionRecord) -> Optional[str]:
    """改前（models.py 用舊式的 Column 宣告，型別檢查把欄位看成 Column，這裡換回值的型別）。"""
    return cast(Optional[str], record.old_value)


def _new(record: CorrectionRecord) -> Optional[str]:
    """改後。"""
    return cast(Optional[str], record.new_value)


class _CurrentContent:
    """一個任務現在的內容（原始轉錄套上最新的校正紀錄），以及照它寫下新的校正紀錄。

    讀兩次資料庫（片段一次、校正紀錄一次），之後的比對都在記憶體裡；寫下的紀錄也更新這份內容，
    同一次操作裡的下一筆就以它為改前。
    """

    def __init__(self, db: Session, task_uuid: uuid.UUID):
        self._task_uuid = task_uuid
        self._segments = {str(row.seg_key): row
                          for row in TranscriptSegmentRepository.list_for_task(db, task_uuid)}
        self._values: Dict[_Key, Optional[str]] = {
            key: _new(r) for key, r in _latest(_records(db, task_uuid)).items()}
        self.pending: List[CorrectionRecord] = []

    def value(self, field: CorrectionField, target: str) -> Optional[str]:
        key = (field.value, target)
        if key in self._values:
            return self._values[key]
        return _original(field, self._segments.get(target))

    def change(self, field: CorrectionField, target: str, new_value: Optional[str],
               operation_id: uuid.UUID) -> bool:
        """有變時記下一筆（還沒寫進資料庫），回傳記了沒有；和現在的內容相同時不記。"""
        if field != CorrectionField.SPEAKER_NAME and target not in self._segments:
            raise ValueError(f"這個任務沒有片段 {target}")
        old = self.value(field, target)
        new = _normalized(field, new_value)
        if new == old:
            return False
        self.pending.append(CorrectionRecord(
            task_uuid=self._task_uuid, target=target, field=field.value,
            old_value=old, new_value=new, operation_id=operation_id))
        self._values[(field.value, target)] = new
        return True

    def commit(self, db: Session) -> None:
        """記下的紀錄在同一個交易裡寫進資料庫並 commit；沒有記任何一筆時不動資料庫。"""
        if self.pending:
            db.add_all(self.pending)
            db.commit()


@dataclass(frozen=True)
class UndoResult:
    """復原一次操作的結果。"""

    restored: int
    """還原了幾筆。"""
    skipped: int
    """略過幾筆：那次操作之後對象又被改過。"""
    operation_id: Optional[uuid.UUID]
    """這次復原自己的操作編號；一筆都沒有還原時是 None。"""


class CorrectionRepository:
    @staticmethod
    def record_operation(db: Session, task_uuid, corrections: Sequence[Correction]) -> Optional[uuid.UUID]:
        """記一次操作：每一筆有變的校正各記一筆校正紀錄，共用一個新的操作編號，在同一個交易裡
        寫完並 commit，回傳操作編號。每一筆都和現在的內容相同時什麼都不記，回傳 None。

        同一次操作裡同一個對象改了兩次時，第二筆的改前是第一筆的改後。
        片段的 ``seg_key`` 不在這個任務裡時丟 ``ValueError``，什麼都不記。
        """
        content = _CurrentContent(db, _task_uuid(task_uuid))
        operation_id = uuid.uuid4()
        for correction in corrections:
            content.change(CorrectionField(correction.field), correction.target,
                           correction.new_value, operation_id)
        content.commit(db)
        return operation_id if content.pending else None

    @staticmethod
    def undo_operation(db: Session, task_uuid, operation_id) -> Optional[UndoResult]:
        """復原一次操作：那次操作的每一筆，對象現在的內容還是那一筆的改後，就再記一筆改回改前；
        之後又被改過的略過。復原也是一次操作，有自己的操作編號，所以復原可以再復原。

        從那次操作最後記的一筆往回處理：同一個對象在那次操作裡改了兩次時，才會一路改回最初的內容。
        這個任務沒有這次操作時回傳 None。
        """
        uuid_val = _task_uuid(task_uuid)
        operation = coerce_uuid(operation_id)
        if operation is None:
            return None
        records = (
            db.query(CorrectionRecord)
            .filter(CorrectionRecord.task_uuid == uuid_val,
                    CorrectionRecord.operation_id == operation)
            .order_by(CorrectionRecord.id.desc())
            .all()
        )
        if not records:
            return None
        content = _CurrentContent(db, uuid_val)
        undo_id = uuid.uuid4()
        restored = 0
        for record in records:
            field, target = CorrectionField(record.field), str(record.target)
            if content.value(field, target) != _new(record):
                continue
            content.change(field, target, _old(record), undo_id)
            restored += 1
        content.commit(db)
        return UndoResult(restored=restored, skipped=len(records) - restored,
                          operation_id=undo_id if restored else None)

    @staticmethod
    def corrected_version(db: Session, task_uuid) -> List[Dict[str, Any]]:
        """一個任務的校正後版本：依 seq 排序的片段，形狀和
        :meth:`TranscriptSegmentRepository.segments_for_task` 相同，文字與說話者換成校正後的，
        可以直接交給輸出格式模組（文字是空的片段不產生行）。

        每個片段另外帶著：

        * ``original_text``、``original_speaker``：原始轉錄的文字與說話者；
        * ``corrected``：文字或說話者和原始轉錄不同；
        * ``deleted``：校正後的文字是空的（刪掉的片段，輸出時略過）；
        * ``has_correction_records``：這個片段有沒有校正紀錄（改回原樣之後仍是有）。

        不論片段有多少個，都只查兩次：片段一次、校正紀錄一次。
        """
        uuid_val = _task_uuid(task_uuid)
        latest = _latest(_records(db, uuid_val))
        version = []
        for segment in TranscriptSegmentRepository.segments_for_task(db, uuid_val):
            seg_key = segment["seg_key"]
            original_text = _normalized(CorrectionField.TEXT, segment["text"])
            original_speaker = segment["speaker"]
            text_record = latest.get((CorrectionField.TEXT.value, seg_key))
            speaker_record = latest.get((CorrectionField.SPEAKER.value, seg_key))
            text = original_text if text_record is None else _new(text_record)
            speaker = original_speaker if speaker_record is None else _new(speaker_record)
            version.append({
                **segment,
                "text": text,
                "speaker": speaker,
                "original_text": original_text,
                "original_speaker": original_speaker,
                "corrected": text != original_text or speaker != original_speaker,
                "deleted": not text,
                "has_correction_records": text_record is not None or speaker_record is not None,
            })
        return version

    @staticmethod
    def records_for_segment(db: Session, task_uuid, seg_key: str) -> List[CorrectionRecord]:
        """一個片段的文字與說話者的校正紀錄，依編號排序（舊的在前）。"""
        uuid_val = _task_uuid(task_uuid)
        return (
            db.query(CorrectionRecord)
            .filter(CorrectionRecord.task_uuid == uuid_val,
                    CorrectionRecord.target == seg_key,
                    CorrectionRecord.field.in_([CorrectionField.TEXT.value,
                                                CorrectionField.SPEAKER.value]))
            .order_by(CorrectionRecord.id)
            .all()
        )

    @staticmethod
    def speaker_names(db: Session, task_uuid) -> Dict[str, str]:
        """一個任務現在的說話者名稱：{說話者編號: 名稱}，只列有名稱的說話者。"""
        uuid_val = _task_uuid(task_uuid)
        records = (
            db.query(CorrectionRecord)
            .filter(CorrectionRecord.task_uuid == uuid_val,
                    CorrectionRecord.field == CorrectionField.SPEAKER_NAME.value)
            .order_by(CorrectionRecord.id)
            .all()
        )
        names = {target: _new(r) for (_, target), r in _latest(records).items()}
        return {target: name for target, name in names.items() if name}

    @staticmethod
    def touched_by_user(db: Session, task_uuid) -> bool:
        """使用者動過這個任務：有任何校正紀錄（改回原樣、復原過的也算），或有片段標了確認狀態。"""
        uuid_val = _task_uuid(task_uuid)
        has_record = db.query(
            db.query(CorrectionRecord).filter(CorrectionRecord.task_uuid == uuid_val).exists()
        ).scalar()
        if has_record:
            return True
        return bool(db.query(
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.task_uuid == uuid_val,
                    TranscriptSegment.review_state.isnot(None),
                    TranscriptSegment.review_state != "")
            .exists()
        ).scalar())

    @staticmethod
    def delete_for_task(db: Session, task_uuid) -> int:
        """刪掉一個任務的所有校正紀錄，回傳刪了幾筆；只有刪掉整個任務時才用。

        只寫進目前的交易、不 commit：刪任務紀錄的地方把它和片段、任務紀錄一起提交
        （``app.api.history`` 的 ``delete_history``）。SQLite 預設不強制外鍵，不能只靠
        ``ON DELETE CASCADE``。
        """
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return 0
        return (
            db.query(CorrectionRecord)
            .filter(CorrectionRecord.task_uuid == uuid_val)
            .delete(synchronize_session=False)
        )
