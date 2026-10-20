"""transcript_segments 的資料庫操作。

同一個任務再完成一次時（任務被重派、重新轉錄），``replace_untouched`` 只換掉使用者沒動過的
片段：校正與確認狀態不會被新的轉錄結果蓋掉（ADR-0007）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.database.models import TranscriptSegment
from app.utils.identifiers import coerce_uuid

EDITED = "edited"
"""``source`` 是這個值時，片段的文字是使用者校正過的。"""


def _touched_by_user(row: TranscriptSegment) -> bool:
    """使用者動過這個片段：文字校正過，或標了確認狀態。

    校正的資料模型留給 v0.2，先用現有的欄位判斷。
    """
    return row.source == EDITED or bool(row.review_state)


def _to_row_values(seg: Dict[str, Any], seq: int) -> Dict[str, Any]:
    words = seg.get("words")
    return {
        "seg_key": str(seg.get("seg_key", seq)),
        "seq": int(seg.get("seq", seq)),
        "start_sec": float(seg.get("start", 0.0)),
        "end_sec": None if seg.get("end") is None else float(seg["end"]),
        "speaker": seg.get("speaker"),
        "text": seg.get("text"),
        "text_alt": seg.get("text_alt"),
        "source": seg.get("source"),
        "words_json": json.dumps(words, ensure_ascii=False) if words else None,
        "confidence": seg.get("confidence"),
    }


class TranscriptSegmentRepository:
    @staticmethod
    def replace_untouched(db: Session, task_uuid, segments: List[Dict[str, Any]]) -> int:
        """這次轉錄的片段取代使用者沒動過的片段，回傳寫入的筆數。

        使用者動過的片段（:func:`_touched_by_user`）不刪、不覆寫，這次結果裡同一個 ``seg_key``
        的片段不寫入；沒動過的舊片段全部換成這次的結果，這次沒有的就拿掉。沒有動過的片段時，
        就是整批取代。

        只寫進目前的交易、不 commit：任務生命週期把它和任務記成完成一起提交。
        """
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return 0

        kept = set()
        existing = db.query(TranscriptSegment).filter(TranscriptSegment.task_uuid == uuid_val)
        for row in existing.all():
            if _touched_by_user(row):
                kept.add(row.seg_key)
            else:
                db.delete(row)
        # 先刪再寫：這次的片段沿用舊片段的 seg_key 時，才不會撞到唯一鍵
        db.flush()

        written = 0
        for seq, seg in enumerate(segments):
            values = _to_row_values(seg, seq)
            if values["seg_key"] in kept:
                continue
            db.add(TranscriptSegment(task_uuid=uuid_val, **values))
            written += 1
        db.flush()
        return written

    @staticmethod
    def list_for_task(db: Session, task_uuid) -> List[TranscriptSegment]:
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return []
        return (
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.task_uuid == uuid_val)
            .order_by(TranscriptSegment.seq)
            .all()
        )

    @staticmethod
    def segments_for_task(db: Session, task_uuid) -> List[Dict[str, Any]]:
        """依 seq 讀回片段，形狀和寫入時傳進來的相同（``_to_row_values`` 的反向）。"""
        return [
            {"seg_key": row.seg_key, "seq": row.seq, "start": row.start_sec, "end": row.end_sec,
             "speaker": row.speaker, "text": row.text, "text_alt": row.text_alt,
             "source": row.source, "words": TranscriptSegmentRepository.words(row),
             "confidence": row.confidence}
            for row in TranscriptSegmentRepository.list_for_task(db, task_uuid)
        ]

    @staticmethod
    def delete_for_task(db: Session, task_uuid) -> int:
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return 0
        deleted = (
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.task_uuid == uuid_val)
            .delete(synchronize_session=False)
        )
        if deleted:
            db.commit()
        return deleted

    @staticmethod
    def words(row: TranscriptSegment) -> Optional[List[Dict[str, Any]]]:
        if not row.words_json:
            return None
        try:
            return json.loads(row.words_json)
        except (TypeError, ValueError):
            return None
