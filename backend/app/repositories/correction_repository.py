"""校正紀錄的資料庫操作，以及校正後版本的算法（#340，ADR 0011）。

片段存的是原始轉錄，寫入後不再改；每一次校正另存一筆校正紀錄（``CorrectionRecord``），只增不改。
校正後版本不另外存，由原始轉錄套上最新的校正紀錄算出來：

1. 一個片段在校正後版本裡的文字，是它最新一筆「文字」紀錄的改後；沒有紀錄就是原始轉錄。說話者同理。
   改過文字的片段，逐字時間照校正後的文字重算（#357），也不另外存。
2. 刪掉片段是一筆「文字」紀錄，改後是空字串。文字是空的片段就是刪掉的片段。還原是再記一筆。
3. 一個說話者編號現在的名稱，是它最新一筆「說話者名稱」紀錄的改後；空的就是沒有名稱。
4. 和現在的內容相同的校正不記。
5. 校正紀錄寫入後不改、不刪，只有刪掉整個任務時一起刪。

「最新」看紀錄的編號（自動遞增的 ``id``），不看時間；這條規則只寫在 :func:`_current`。下載、
校正頁與匯出都從 :meth:`CorrectionRepository.corrected_version` 讀，不各寫各的。

「沒有」的寫法：文字與說話者名稱的「沒有」一律是空字串（原始轉錄的文字是 NULL 時也當成空字串），
說話者的「沒有」一律是 NULL，見 :func:`_normalized`。

確認狀態（``review_state``）留在片段上，不是校正，不進校正紀錄；它是片段上唯一會在寫入後改的欄位，
原始轉錄的欄位（文字、說話者、時間等）照舊不改。寫的時候和校正紀錄一樣先鎖住任務
（:meth:`CorrectionRepository.record_operation` 的 ``review_states``）。

校正紀錄與確認狀態一律經過 :class:`_CurrentContent` 寫（它鎖住任務）。每次寫了校正紀錄或確認狀態，
這個任務的保留音檔的保留天數就從現在重新起算（#350），做在它 commit 的地方，之後新的寫入端點也不必
各自記得。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Collection, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, cast

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core import word_timings
from app.database.models import CorrectionRecord, TranscriptionLog, TranscriptSegment
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.services import audio_store
from app.utils.identifiers import coerce_uuid


class CorrectionField(StrEnum):
    """校正改了什麼。v0.2 的校正只有這幾種（刪掉片段是文字改成空字串）。"""

    TEXT = "text"
    SPEAKER = "speaker"
    SPEAKER_NAME = "speaker_name"
    """對象是說話者編號，不是片段。"""


SEGMENT_FIELDS = (CorrectionField.TEXT, CorrectionField.SPEAKER)
"""對象是片段的校正。"""


class ReviewState(StrEnum):
    """確認狀態：使用者在片段上標的檢查結果。沒有標是 None。不是校正，不留校正紀錄。"""

    VERIFIED = "verified"
    """已確認。"""
    FLAGGED = "flagged"
    """待查。"""


@dataclass(frozen=True)
class Correction:
    """一次操作裡的一筆校正：把 ``target`` 的 ``field`` 改成 ``new_value``。

    ``target`` 是片段的 ``seg_key``；``field`` 是說話者名稱時是說話者編號（例如 ``S0``）。
    改前由 repository 從現在的內容讀，不由呼叫的人傳。
    """

    target: str
    field: CorrectionField
    new_value: Optional[str]


@dataclass(frozen=True)
class UndoResult:
    """復原一次操作的結果。"""

    restored: int
    """還原了幾筆。"""
    skipped: int
    """略過幾筆：那次操作之後對象又被改過。"""
    operation_id: Optional[uuid.UUID]
    """這次復原自己的操作編號；一筆都沒有還原時是 None。"""
    seg_keys: Tuple[str, ...] = ()
    """那次操作改到的片段的鍵（依第一次改到的順序），還原的與略過的都算；說話者名稱的對象不在內。"""


_Key = Tuple[CorrectionField, str]
"""一個對象的一種內容：(改了什麼, 對象)。"""


def _key(record: CorrectionRecord) -> _Key:
    return CorrectionField(record.field), str(record.target)


def _old(record: CorrectionRecord) -> Optional[str]:
    """改前（models.py 用舊式的 Column 宣告，型別檢查把欄位看成 Column，這裡換回值的型別）。"""
    return cast(Optional[str], record.old_value)


def _new(record: CorrectionRecord) -> Optional[str]:
    """改後。"""
    return cast(Optional[str], record.new_value)


def _normalized(field: CorrectionField, value: Optional[str]) -> Optional[str]:
    """文字與說話者名稱的「沒有」一律是空字串，說話者的「沒有」一律是 NULL：比對時兩種寫法才算相同。"""
    if field == CorrectionField.SPEAKER:
        return value or None
    return value or ""


def _current(latest: Dict[_Key, CorrectionRecord], key: _Key, original: Optional[str]) -> Optional[str]:
    """一個對象的一種內容現在是什麼：最新一筆校正紀錄的改後；沒有紀錄就是原始轉錄
    （說話者名稱的原始轉錄是沒有名稱）。"""
    record = latest.get(key)
    return _normalized(key[0], original) if record is None else _new(record)


def _is_deleted(text: Optional[str]) -> bool:
    """刪掉的片段：文字是空的。只有空白也算，和輸出格式模組略過的片段一致。"""
    return not (text or "").strip()


def _task_uuid(task_uuid) -> uuid.UUID:
    value = coerce_uuid(task_uuid)
    if value is None:
        raise ValueError("task_uuid 格式不正確")
    return value


def _records(db: Session, task_uuid: uuid.UUID, *conditions) -> List[CorrectionRecord]:
    """一個任務的校正紀錄（可以再加條件），依編號排序，舊的在前。"""
    return (
        db.query(CorrectionRecord)
        .filter(CorrectionRecord.task_uuid == task_uuid, *conditions)
        .order_by(CorrectionRecord.id)
        .all()
    )


def _latest(records: Sequence[CorrectionRecord]) -> Dict[_Key, CorrectionRecord]:
    """每個對象、每種內容最新的一筆；records 依編號排序。"""
    return {_key(r): r for r in records}


def _lock_task(db: Session, task_uuid: uuid.UUID) -> None:
    """寫校正紀錄之前先鎖住任務：同一個任務的操作一次一個，讀到的現在的內容才不會過時。

    兩個請求同時改同一個片段時，沒有這一步的話兩邊都讀到同一份內容，後寫的那筆的改前就不是前一筆
    的改後，之後的復原會悄悄蓋掉前一次的修改；Postgres 上編號的順序也可能和寫完的順序不同。

    做法是對任務紀錄執行一次不改任何值的 UPDATE，兩種資料庫都會鎖到 commit 為止：SQLite（免安裝
    模式）從這裡開始交易並拿到寫入鎖，別的連線要寫就得等（``busy_timeout``）；Postgres（Docker
    模式）鎖住任務那一列，而且 READ COMMITTED 之後的查詢讀得到別人剛寫完的紀錄。所以這一步要在
    讀現在的內容之前。

    任務紀錄不在時丟 ``ValueError``：SQLite 不強制外鍵，不擋的話說話者名稱的紀錄會變成孤兒。
    """
    locked = db.execute(
        update(TranscriptionLog)
        .where(TranscriptionLog.task_uuid == task_uuid)
        .values(status=TranscriptionLog.status)
        .execution_options(synchronize_session=False)
    )
    if not getattr(locked, "rowcount", 0):
        db.rollback()
        raise ValueError("找不到任務紀錄")


class _CurrentContent:
    """寫校正紀錄用：鎖住任務後讀它現在的內容（原始轉錄套上最新的校正紀錄），照它記下新的紀錄。

    讀三次資料庫（片段、校正紀錄與保留音檔的檔名各一次），之後的比對都在記憶體裡；記下的紀錄也算進
    現在的內容，同一次操作裡的下一筆就以它為改前。

    當成 context manager 用：區塊順利結束時，記下的紀錄和鎖一起 commit（沒有記任何一筆時只放掉鎖）；
    區塊裡出錯時 rollback，一筆都不寫。

    commit 之後，有記下校正紀錄或寫了確認狀態時，這個任務的保留音檔的保留天數從現在重新起算
    （:func:`app.services.audio_store.restart_retention`，#350），校正到一半不會突然聽不到。和現在的
    內容相同、什麼都沒寫的不算（照 GLOSSARY，沒有留下校正紀錄就不是一次校正）。保留音檔不在或改不了時
    校正照樣存。
    """

    def __init__(self, db: Session, task_uuid: uuid.UUID):
        _lock_task(db, task_uuid)
        self._db = db
        self._task_uuid = task_uuid
        self._audio_filename = cast(Optional[str], db.query(TranscriptionLog.audio_filename)
                                    .filter(TranscriptionLog.task_uuid == task_uuid).scalar())
        self._segments = {str(row.seg_key): row
                          for row in TranscriptSegmentRepository.list_for_task(db, task_uuid)}
        self._latest = _latest(_records(db, task_uuid))
        self.recorded: List[CorrectionRecord] = []
        self._wrote_review_state = False

    def __enter__(self) -> _CurrentContent:
        return self

    def __exit__(self, error_type, _error, _traceback) -> None:
        if error_type is not None:
            self._db.rollback()
            return
        self._db.add_all(self.recorded)
        self._db.commit()
        if self.recorded or self._wrote_review_state:
            audio_store.restart_retention(self._audio_filename)

    def value(self, key: _Key) -> Optional[str]:
        field, target = key
        segment = self._segments.get(target)
        original = None
        if segment is not None and field == CorrectionField.TEXT:
            original = cast(Optional[str], segment.text)
        elif segment is not None and field == CorrectionField.SPEAKER:
            original = cast(Optional[str], segment.speaker)
        return _current(self._latest, key, original)

    def set_review_state(self, seg_key: str, state: Optional[ReviewState]) -> None:
        """把片段的確認狀態改成 ``state``（None 是清除），和記下的紀錄一起 commit。不是校正，不留紀錄。"""
        if seg_key not in self._segments:
            raise ValueError(f"這個任務沒有片段 {seg_key}")
        self._db.execute(
            update(TranscriptSegment)
            .where(TranscriptSegment.task_uuid == self._task_uuid, TranscriptSegment.seg_key == seg_key)
            .values(review_state=ReviewState(state).value if state else None)
            .execution_options(synchronize_session=False)
        )
        self._wrote_review_state = True

    def change(self, key: _Key, new_value: Optional[str], operation_id: uuid.UUID) -> None:
        """有變時記下一筆（還沒寫進資料庫）；和現在的內容相同時不記。"""
        field, target = key
        if field in SEGMENT_FIELDS and target not in self._segments:
            raise ValueError(f"這個任務沒有片段 {target}")
        old = self.value(key)
        new = _normalized(field, new_value)
        if new == old:
            return
        record = CorrectionRecord(task_uuid=self._task_uuid, target=target, field=field.value,
                                  old_value=old, new_value=new, operation_id=operation_id)
        self.recorded.append(record)
        self._latest[key] = record


class CorrectionRepository:
    @staticmethod
    def record_operation(db: Session, task_uuid, corrections: Sequence[Correction], *,
                         review_states: Optional[Mapping[str, Optional[ReviewState]]] = None,
                         ) -> Optional[uuid.UUID]:
        """記一次操作：每一筆有變的校正各記一筆校正紀錄，共用一個新的操作編號，在同一個交易裡
        寫完並 commit，回傳操作編號。每一筆都和現在的內容相同時什麼都不記，回傳 None。

        ``review_states``（{片段鍵: 確認狀態}，None 是清除）在同一個交易裡寫在片段上：確認狀態不是校正，
        不留校正紀錄，也不算進這次操作，只標確認狀態時回傳 None。和校正紀錄一樣先鎖住任務再寫，
        任務再完成一次時判斷使用者動過沒有（:mod:`app.tasks.lifecycle`）才不會漏掉剛標的確認狀態。

        同一次操作裡同一個對象改了兩次時，第二筆的改前是第一筆的改後。任務紀錄不在、或片段的
        ``seg_key`` 不在這個任務裡時丟 ``ValueError``，什麼都不記、確認狀態也不寫。
        """
        operation_id = uuid.uuid4()
        with _CurrentContent(db, _task_uuid(task_uuid)) as content:
            for correction in corrections:
                content.change((CorrectionField(correction.field), correction.target),
                               correction.new_value, operation_id)
            for seg_key, state in (review_states or {}).items():
                content.set_review_state(seg_key, state)
        return operation_id if content.recorded else None

    @staticmethod
    def undo_operation(db: Session, task_uuid, operation_id) -> Optional[UndoResult]:
        """復原一次操作：那次操作的每一筆，對象現在的內容還是那一筆的改後，就再記一筆改回改前；
        之後又被改過的略過。復原也是一次操作，有自己的操作編號，所以復原可以再復原。

        從那次操作最後記的一筆往回處理，同一個對象在那次操作裡改了兩次時，才會一路改回操作前的內容；
        較晚的那筆被略過時（之後又被改過），較早的也一起略過，不蓋掉之後的修改。
        這個任務沒有這次操作時回傳 None。
        """
        uuid_val = _task_uuid(task_uuid)
        operation = coerce_uuid(operation_id)
        if operation is None:
            return None
        records = _records(db, uuid_val, CorrectionRecord.operation_id == operation)
        if not records:
            return None
        undo_id = uuid.uuid4()
        changed_since: set[_Key] = set()
        with _CurrentContent(db, uuid_val) as content:
            for record in reversed(records):
                key = _key(record)
                if key in changed_since or content.value(key) != _new(record):
                    changed_since.add(key)
                    continue
                content.change(key, _old(record), undo_id)
        restored = len(content.recorded)
        seg_keys = dict.fromkeys(target for field, target in map(_key, records) if field in SEGMENT_FIELDS)
        return UndoResult(restored=restored, skipped=len(records) - restored,
                          operation_id=undo_id if restored else None, seg_keys=tuple(seg_keys))

    @staticmethod
    def corrected_version(db: Session, task_uuid,
                          seg_keys: Optional[Collection[str]] = None) -> List[Dict[str, Any]]:
        """一個任務的校正後版本：依 seq 排序的片段，形狀和
        :meth:`TranscriptSegmentRepository.segments_for_task` 相同，文字與說話者換成校正後的，
        可以直接交給輸出格式模組（文字是空的片段不產生行）。給 ``seg_keys`` 時只算這些片段（改了
        一個片段之後回它的新內容用）。

        逐字時間（``words``）對的是校正後的文字：文字沒改過的片段照原樣；改過的片段由
        :func:`app.core.word_timings.for_corrected_text` 重算（#357），沒改到的字沿用原本的時間，
        下載照樣斷句、拆字幕，校正頁照樣標出正在唸的字；算不出來（原本就沒有逐字時間、刪掉的片段）
        時是 None。只在這裡算，不寫回片段。

        每個片段另外帶著：

        * ``original_text``、``original_speaker``：原始轉錄的文字與說話者；
        * ``corrected``：文字或說話者和原始轉錄不同；
        * ``deleted``：校正後的文字是空的（刪掉的片段，輸出時略過）。原始轉錄就沒有文字的片段也是；
        * ``has_correction_records``：這個片段有沒有校正紀錄（改回原樣之後仍是有）。

        不論片段有多少個，都只查兩次：片段一次、校正紀錄一次。
        """
        uuid_val = _task_uuid(task_uuid)
        only = () if seg_keys is None else (CorrectionRecord.target.in_(list(seg_keys)),)
        latest = _latest(_records(db, uuid_val, *only))
        version = []
        for segment in TranscriptSegmentRepository.segments_for_task(db, uuid_val, seg_keys):
            text_key = (CorrectionField.TEXT, segment["seg_key"])
            speaker_key = (CorrectionField.SPEAKER, segment["seg_key"])
            original_text = _normalized(CorrectionField.TEXT, segment["text"])
            original_speaker = _normalized(CorrectionField.SPEAKER, segment["speaker"])
            text = _current(latest, text_key, original_text)
            speaker = _current(latest, speaker_key, original_speaker)
            text_changed = text != original_text
            words = segment["words"]
            if text_changed:
                words = word_timings.for_corrected_text(
                    original_text or "", words, text or "", start=segment["start"], end=segment["end"])
            version.append({
                **segment,
                "text": text,
                "speaker": speaker,
                "words": words,
                "original_text": original_text,
                "original_speaker": original_speaker,
                "corrected": text_changed or speaker != original_speaker,
                "deleted": _is_deleted(text),
                "has_correction_records": text_key in latest or speaker_key in latest,
            })
        return version

    @staticmethod
    def records_for_segment(db: Session, task_uuid, seg_key: str) -> List[CorrectionRecord]:
        """一個片段的文字與說話者的校正紀錄，依編號排序（舊的在前）。"""
        return _records(db, _task_uuid(task_uuid), CorrectionRecord.target == seg_key,
                        CorrectionRecord.field.in_([field.value for field in SEGMENT_FIELDS]))

    @staticmethod
    def speaker_names(db: Session, task_uuid) -> Dict[str, str]:
        """一個任務現在的說話者名稱：{說話者編號: 名稱}，只列有名稱的說話者。"""
        records = _records(db, _task_uuid(task_uuid),
                           CorrectionRecord.field == CorrectionField.SPEAKER_NAME.value)
        names = {target: _new(r) for (_, target), r in _latest(records).items()}
        return {target: name for target, name in names.items() if name}

    @staticmethod
    def tasks_with_records(db: Session, task_uuids: Iterable[Any]) -> Set[str]:
        """這些任務裡有校正紀錄的那些（任務紀錄 id 的字串），改回原樣、復原過的也算。一次查完，
        History 的一頁不會一個任務查一次（#346：有校正的任務，下載選單多一組原始轉錄）。"""
        uuids = [u for u in (coerce_uuid(t) for t in task_uuids) if u is not None]
        if not uuids:
            return set()
        rows = (
            db.query(CorrectionRecord.task_uuid)
            .filter(CorrectionRecord.task_uuid.in_(uuids))
            .distinct()
            .all()
        )
        return {str(row[0]) for row in rows}

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
    def delete_for_task(db: Session, task_uuid, *, commit: bool = True) -> int:
        """刪掉一個任務的所有校正紀錄，回傳刪了幾筆；只有刪掉整個任務時才用。

        SQLite 預設不強制外鍵，不能只靠 ``ON DELETE CASCADE``。刪任務紀錄的地方傳 ``commit=False``，
        和片段、任務紀錄在同一個交易裡刪（``app.api.history`` 的 ``delete_history``）。
        """
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return 0
        deleted = (
            db.query(CorrectionRecord)
            .filter(CorrectionRecord.task_uuid == uuid_val)
            .delete(synchronize_session=False)
        )
        if commit:
            db.commit()
        return deleted
