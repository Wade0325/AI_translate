"""transcript_segments 的資料庫操作。

片段存的是原始轉錄，校正不改它：每一次校正另存一筆校正紀錄，校正後版本由兩者算出來（ADR 0011，
見 :mod:`app.repositories.correction_repository`）。片段的 ``source`` 只記原始轉錄的來源。

同一個任務再完成一次時，什麼情況下整批換成這次的結果（:meth:`TranscriptSegmentRepository.replace_for_task`）、
什麼情況下原本的片段一個都不動，由任務生命週期決定（:mod:`app.tasks.lifecycle`）。
"""

from __future__ import annotations

import json
from typing import Any, Collection, Dict, Iterable, List, Optional, Set

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
        "speaker_confidence": seg.get("speaker_confidence"),
    }


class TranscriptSegmentRepository:
    @staticmethod
    def replace_for_task(db: Session, task_uuid, segments: List[Dict[str, Any]]) -> int:
        """一個任務的片段整批換成 ``segments``（原本有、這次沒有的也拿掉），回傳寫入的筆數。

        只給沒有校正紀錄與確認狀態的任務用（見 :mod:`app.tasks.lifecycle`）。只寫進目前的交易、不
        commit：任務生命週期把它和任務記成完成一起提交。
        """
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return 0
        # 先刪再寫：這次的片段沿用舊片段的 seg_key 時，才不會撞到唯一鍵
        TranscriptSegmentRepository.delete_for_task(db, uuid_val, commit=False)
        rows = [TranscriptSegment(task_uuid=uuid_val, **_to_row_values(seg, seq))
                for seq, seg in enumerate(segments)]
        db.add_all(rows)
        db.flush()
        return len(rows)

    @staticmethod
    def list_for_task(db: Session, task_uuid,
                      seg_keys: Optional[Collection[str]] = None) -> List[TranscriptSegment]:
        """依 seq 讀回一個任務的片段；給 ``seg_keys`` 時只讀這些片段。"""
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return []
        query = db.query(TranscriptSegment).filter(TranscriptSegment.task_uuid == uuid_val)
        if seg_keys is not None:
            query = query.filter(TranscriptSegment.seg_key.in_(list(seg_keys)))
        return query.order_by(TranscriptSegment.seq).all()

    @staticmethod
    def tasks_with_segments(db: Session, task_uuids: Iterable[Any]) -> Set[str]:
        """這些任務裡有片段的那些（任務紀錄 id 的字串）。一次查完，History 的一頁不會一個任務查一次。"""
        uuids = [u for u in (coerce_uuid(t) for t in task_uuids) if u is not None]
        if not uuids:
            return set()
        rows = (
            db.query(TranscriptSegment.task_uuid)
            .filter(TranscriptSegment.task_uuid.in_(uuids))
            .distinct()
            .all()
        )
        return {str(row[0]) for row in rows}

    @staticmethod
    def segments_for_task(db: Session, task_uuid,
                          seg_keys: Optional[Collection[str]] = None) -> List[Dict[str, Any]]:
        """依 seq 讀回片段，形狀和寫入時傳進來的相同（``_to_row_values`` 的反向），另外帶著確認狀態
        （``review_state``：使用者標的，寫入轉錄結果時不帶；沒有標是 None）。給 ``seg_keys`` 時只讀
        這些片段。"""
        return [
            {"seg_key": row.seg_key, "seq": row.seq, "start": row.start_sec, "end": row.end_sec,
             "speaker": row.speaker, "text": row.text, "text_alt": row.text_alt,
             "source": row.source, "words": TranscriptSegmentRepository.words(row),
             "speaker_confidence": row.speaker_confidence, "review_state": row.review_state or None}
            for row in TranscriptSegmentRepository.list_for_task(db, task_uuid, seg_keys)
        ]

    @staticmethod
    def delete_for_task(db: Session, task_uuid, *, commit: bool = True) -> int:
        """刪掉一個任務的所有片段，回傳刪了幾筆。``commit=False`` 時只寫進目前的交易。"""
        uuid_val = coerce_uuid(task_uuid)
        if uuid_val is None:
            return 0
        deleted = (
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.task_uuid == uuid_val)
            .delete(synchronize_session=False)
        )
        if deleted and commit:
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
