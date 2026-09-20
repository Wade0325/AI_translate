"""transcript_segments 的資料庫操作。

``upsert_many`` 以 (task_uuid, seg_key) 為鍵覆寫，所以任務被重派、或之後改成
逐段回傳時反覆寫同一段，都不會產生重複資料。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.database.models import TranscriptSegment
from app.utils.identifiers import coerce_uuid


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
    def upsert_many(db: Session, task_uuid, segments: List[Dict[str, Any]]) -> int:
        """寫入／覆寫片段，回傳處理筆數。"""
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None or not segments:
            return 0

        existing = {
            row.seg_key: row
            for row in db.query(TranscriptSegment)
            .filter(TranscriptSegment.task_uuid == uuid_val)
            .all()
        }
        for seq, seg in enumerate(segments):
            values = _to_row_values(seg, seq)
            row = existing.get(values["seg_key"])
            if row is None:
                db.add(TranscriptSegment(task_uuid=uuid_val, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        db.commit()
        return len(segments)

    @staticmethod
    def replace_all(db: Session, task_uuid, segments: List[Dict[str, Any]]) -> int:
        """整批取代：先刪掉這個任務所有片段，再寫入新的。"""
        TranscriptSegmentRepository.delete_for_task(db, task_uuid)
        return TranscriptSegmentRepository.upsert_many(db, task_uuid, segments)

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
