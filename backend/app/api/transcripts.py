"""校正介面用的轉錄文件端點。

與 ``/history`` 的差別：history 給的是任務層級的統計與可下載的轉錄結果，
這裡給的是**可逐段操作的結構化文件**（說話者、逐字時間戳、第二假設）加上
保留音檔，讓前端能邊聽邊改。

音檔用 FileResponse 直接服務；Starlette 會處理 Range 請求，播放器才能拖曳。
"""

from pathlib import Path
from typing import Optional, cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog
from app.database.session import get_db
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.schemas.schemas import (
    TranscriptResponse,
    TranscriptSegmentResponse,
    TranscriptWord,
)
from app.services import audio_store
from app.utils.audio import get_mime_type
from app.utils.identifiers import coerce_uuid
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()
segment_repo = TranscriptSegmentRepository()


def _get_log(db: Session, task_uuid: str) -> TranscriptionLog:
    uuid_val = coerce_uuid(task_uuid)
    if uuid_val is None:
        raise HTTPException(status_code=400, detail="task_uuid 格式不正確")
    log = (
        db.query(TranscriptionLog)
        .filter(TranscriptionLog.task_uuid == uuid_val)
        .first()
    )
    if log is None:
        raise HTTPException(status_code=404, detail="找不到此任務紀錄")
    return log


@router.get("/{task_uuid}", response_model=TranscriptResponse)
def get_transcript(task_uuid: str, db: Session = Depends(get_db)):
    """取得結構化轉錄文件；片段尚未產生時 segments 為空陣列。"""
    log = _get_log(db, task_uuid)
    rows = segment_repo.list_for_task(db, task_uuid)

    segments = []
    for row in rows:
        words = segment_repo.words(row)
        segments.append(TranscriptSegmentResponse(
            seg_key=row.seg_key,
            seq=row.seq,
            start=row.start_sec,
            end=row.end_sec,
            speaker=row.speaker,
            text=row.text,
            text_alt=row.text_alt,
            source=row.source,
            confidence=row.confidence,
            review_state=row.review_state,
            words=[TranscriptWord(**w) for w in words] if words else None,
        ))

    return TranscriptResponse(
        task_uuid=str(log.task_uuid),
        status=log.status,
        original_filename=log.original_filename,
        audio_duration_seconds=log.audio_duration_seconds,
        audio_available=audio_store.resolve(log.audio_filename) is not None,
        segment_count=len(segments),
        segments=segments,
    )


@router.get("/{task_uuid}/audio")
def get_transcript_audio(task_uuid: str, db: Session = Depends(get_db)):
    """回傳保留音檔，供校正介面播放。"""
    log = _get_log(db, task_uuid)
    path = audio_store.resolve(log.audio_filename)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="音檔已不存在（未保留或已超過保留期限）",
        )
    return FileResponse(
        path,
        media_type=get_mime_type(path) or "application/octet-stream",
        filename=_retained_name(cast(Optional[str], log.original_filename), path),
        content_disposition_type="inline",
    )


def _retained_name(original_filename: Optional[str], path: Path) -> str:
    """保留音檔下載時的檔名：原檔名換上保留音檔的副檔名。影片上傳時抽成了 FLAC（#258），照原檔名
    存成 .mp4 會打不開。"""
    if not original_filename:
        return path.name
    return f"{Path(original_filename).stem}{path.suffix}"
