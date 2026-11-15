"""校正介面用的轉錄文件端點。

與 ``/history`` 的差別：history 給的是任務層級的統計與可下載的轉錄結果，
這裡給的是**可逐段操作的結構化文件**（說話者、逐字時間戳、第二假設）加上
保留音檔，讓前端能邊聽邊改。

音檔用 FileResponse 直接服務；Starlette 會處理 Range 請求，播放器才能拖曳。

校正（#341，ADR 0011）：讀到的片段是校正後版本，另外帶著原始轉錄；改一個片段的文字、說話者與確認狀態，
以及復原一次操作，都從這裡寫。校正後版本與校正紀錄的規則在 ``app.repositories.correction_repository``，
這裡只檢查請求。寫入端點和 History 的清單、讀取端點用同一個「能不能校正」的判斷
（``app.services.correctability``）。轉錄的文字不寫進日誌（#25 故事 84）。

寫入端點沒有使用者驗證：免安裝模式只收 app 自己的頁面送的寫入請求，做在 ``app.core.api_access``，
這裡不各自處理。
"""

import re
from pathlib import Path
from typing import Any, Collection, Dict, List, Optional, Tuple, cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog
from app.database.session import get_db
from app.repositories.correction_repository import (
    Correction,
    CorrectionField,
    CorrectionRepository,
    ReviewState,
)
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.schemas.schemas import (
    SegmentCorrectionRequest,
    SegmentCorrectionResponse,
    TranscriptResponse,
    TranscriptSegmentResponse,
    TranscriptWord,
    UndoOperationResponse,
)
from app.services import audio_store, correctability
from app.services.correctability import Uncorrectable
from app.utils.audio import get_mime_type
from app.utils.identifiers import coerce_uuid
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()
segment_repo = TranscriptSegmentRepository()

TEXT_MAX_LENGTH = 5000
"""一個片段的文字最多幾個字（去掉前後的空白、收掉換行之後算）。最長的片段也只有幾百字，上限只擋貼錯的大段文字。"""

_SPEAKER_ID = re.compile(r"S(?:0|[1-9][0-9]{0,2})")
"""說話者編號：S 加數字（S0 到 S999），和轉錄時產生的寫法相同，不補零。"""

_LINE_BREAKS = re.compile(r"\s*[\r\n]+\s*")

_UNCORRECTABLE = {
    Uncorrectable.NOT_COMPLETED: "這個任務還沒完成，完成之後才能校正",
    Uncorrectable.WITH_TRANSLATION: "這個任務是轉錄並翻譯，翻譯過的結果不能校正",
    Uncorrectable.NO_SEGMENTS: "這個任務沒有可以逐段校正的片段",
}


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


def _correctable_log(db: Session, task_uuid: str) -> TranscriptionLog:
    """寫入端點用：任務紀錄要在，而且任務能校正（已完成、有片段、不是轉錄並翻譯的任務）。"""
    log = _get_log(db, task_uuid)
    has_segments = bool(segment_repo.tasks_with_segments(db, [log.task_uuid]))
    blocker = correctability.reason(log, has_segments=has_segments)
    if blocker is not None:
        raise HTTPException(status_code=409, detail=_UNCORRECTABLE[blocker])
    return log


def _segment_response(segment: Dict[str, Any]) -> TranscriptSegmentResponse:
    """校正後版本的一個片段（``CorrectionRepository.corrected_version`` 回的形狀）→ 回應的片段。"""
    words = segment["words"]
    return TranscriptSegmentResponse(
        seg_key=segment["seg_key"],
        seq=segment["seq"],
        start=segment["start"],
        end=segment["end"],
        speaker=segment["speaker"],
        text=segment["text"],
        original_speaker=segment["original_speaker"],
        original_text=segment["original_text"],
        corrected=segment["corrected"],
        deleted=segment["deleted"],
        has_correction_records=segment["has_correction_records"],
        text_alt=segment["text_alt"],
        source=segment["source"],
        confidence=segment["confidence"],
        review_state=segment["review_state"],
        words=[TranscriptWord(**w) for w in words] if words else None,
    )


def _segments(db: Session, log: TranscriptionLog,
              seg_keys: Optional[Collection[str]] = None) -> List[TranscriptSegmentResponse]:
    """任務的校正後版本（給 ``seg_keys`` 時只有這些片段），依 seq 排序。"""
    return [_segment_response(segment)
            for segment in CorrectionRepository.corrected_version(db, log.task_uuid, seg_keys)]


@router.get("/{task_uuid}", response_model=TranscriptResponse)
def get_transcript(task_uuid: str, db: Session = Depends(get_db)):
    """取得結構化轉錄文件：片段是校正後版本，另外帶著原始轉錄；片段尚未產生時 segments 為空陣列。"""
    log = _get_log(db, task_uuid)
    segments = _segments(db, log)

    blocker = correctability.reason(log, has_segments=bool(segments))
    return TranscriptResponse(
        task_uuid=str(log.task_uuid),
        status=log.status,
        original_filename=log.original_filename,
        audio_duration_seconds=log.audio_duration_seconds,
        audio_available=audio_store.resolve(log.audio_filename) is not None,
        correctable=blocker is None,
        uncorrectable_reason=blocker,
        segment_count=len(segments),
        segments=segments,
    )


def _normalized_text(text: str) -> str:
    """前後的空白去掉，中間的換行（連同它前後的空白）收成一個空白。照使用者打的字存，不做繁體輸出的轉換。"""
    return _LINE_BREAKS.sub(" ", text.strip())


def _segment_changes(seg_key: str, body: SegmentCorrectionRequest,
                     ) -> Tuple[List[Correction], Dict[str, Optional[ReviewState]]]:
    """PATCH 的 body → 要記的校正（文字、說話者）與要寫的確認狀態；不合規則時回 400。"""
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(status_code=400, detail="至少要帶 text、speaker、review_state 其中一個")
    corrections: List[Correction] = []
    if "text" in sent:
        if body.text is None:
            raise HTTPException(status_code=400, detail="文字不能是 null；要刪掉片段請送空字串")
        text = _normalized_text(body.text)
        if len(text) > TEXT_MAX_LENGTH:
            raise HTTPException(status_code=400, detail=f"文字太長：一個片段最多 {TEXT_MAX_LENGTH} 字")
        corrections.append(Correction(seg_key, CorrectionField.TEXT, text))
    if "speaker" in sent:
        if body.speaker is not None and not _SPEAKER_ID.fullmatch(body.speaker):
            raise HTTPException(status_code=400, detail="說話者的格式不正確：要是 S 加數字，例如 S0、S1")
        corrections.append(Correction(seg_key, CorrectionField.SPEAKER, body.speaker))
    review_states: Dict[str, Optional[ReviewState]] = {}
    if "review_state" in sent:
        if body.review_state is not None and body.review_state not in {s.value for s in ReviewState}:
            raise HTTPException(status_code=400, detail="確認狀態只能是 verified、flagged 或 null")
        review_states[seg_key] = ReviewState(body.review_state) if body.review_state else None
    return corrections, review_states


@router.patch("/{task_uuid}/segments/{seg_key}", response_model=SegmentCorrectionResponse)
def correct_segment(task_uuid: str, seg_key: str, body: SegmentCorrectionRequest,
                    db: Session = Depends(get_db)):
    """改一個片段的文字、說話者或確認狀態。

    文字與說話者有變的各記一筆校正紀錄，共用一個操作編號（復原時用）；和現在的內容相同的不記。
    確認狀態直接寫在片段上，不留校正紀錄，也不算一次操作。還原刪掉的片段、回到某一版，都是把那一版的
    內容用這個端點送出。
    """
    log = _correctable_log(db, task_uuid)
    corrections, review_states = _segment_changes(seg_key, body)
    try:
        operation_id = CorrectionRepository.record_operation(
            db, log.task_uuid, corrections, review_states=review_states)
    except ValueError as e:
        # 片段鍵不在這個任務裡（或任務剛好被刪掉）：什麼都沒寫
        raise HTTPException(status_code=404, detail="找不到此片段") from e
    return SegmentCorrectionResponse(
        operation_id=str(operation_id) if operation_id else None,
        segment=_segments(db, log, [seg_key])[0],
    )


@router.post("/{task_uuid}/operations/{operation_id}/undo", response_model=UndoOperationResponse)
def undo_operation(task_uuid: str, operation_id: str, db: Session = Depends(get_db)):
    """復原一次操作：那次操作改到的每一項，之後沒再改過的改回去，又被改過的略過。

    復原也是一次操作，有自己的操作編號，所以復原可以再復原。回應帶那次操作改到的片段的新內容。
    """
    log = _correctable_log(db, task_uuid)
    operation = coerce_uuid(operation_id)
    if operation is None:
        raise HTTPException(status_code=400, detail="操作編號格式不正確")
    try:
        result = CorrectionRepository.undo_operation(db, log.task_uuid, operation)
    except ValueError as e:
        # 任務剛好被刪掉：什麼都沒寫
        raise HTTPException(status_code=404, detail="找不到此任務紀錄") from e
    if result is None:
        raise HTTPException(status_code=404, detail="這個任務沒有這次操作")
    return UndoOperationResponse(
        restored=result.restored,
        skipped=result.skipped,
        operation_id=str(result.operation_id) if result.operation_id else None,
        segments=_segments(db, log, result.segments) if result.segments else [],
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
