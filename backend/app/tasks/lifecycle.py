"""任務生命週期模組：一個任務的狀態轉換與副作用都在這裡，單檔任務與批次的每個檔案都一樣。

    開始 → 進度 … → 完成／失敗／取消 → 收尾 → 宣告結果

單檔任務一次跑完（:meth:`TaskLifecycle.run`）：呼叫端只給「怎麼轉錄」，拿到輸入音檔與進度與取消
物件，回傳轉錄結果。批次的每個檔案分兩段：送出之前開始（:meth:`TaskLifecycle.start`），批次的
結果回來時結束（:meth:`TaskLifecycle.end`）；結果可能在重啟之後才從復原入口回來，這時從任務紀錄
接回（:meth:`TaskLifecycle.resume`）。任務紀錄與片段、計價、狀態廣播、取消旗標、保留音檔與清理
輸入音檔都在這裡，每條規則只寫一次：

- 取消不是失敗：任務紀錄寫 CANCELLED。開始前就取消的任務也有紀錄，不呼叫供應商；
  使用者取消之後，供應商才跑完或才出錯，都不蓋掉取消。其他狀態照實改寫：啟動清掃把
  還在跑的任務記成失敗，任務之後跑完就記成完成。
- 暫時錯誤在出錯的那一步等一段時間再做一次：分段轉錄重試出錯的那一段
  （:mod:`app.services.chunked_transcription`），批次重做上傳、送出或查詢（:mod:`app.tasks.batch_core`）；
  執行模式不重試整個任務。萬一有暫時錯誤漏到這裡，一律照失敗處理，任務不會停在處理中。
- 完成和片段一起寫：任務紀錄記成完成（連同凍結的原始轉錄副本）和片段在同一個交易，片段
  寫不進去就照失敗處理。同一個任務再完成一次時，使用者動過的片段不刪、不覆寫（ADR-0007）。
- 說話者標記跟著 Multi-Speaker 開關：任務紀錄記下開關，完成時送給畫面的輸出格式照它帶或不帶
  說話者標記，和之後下載的相同；片段與凍結的原始轉錄副本不論開關都有說話者編號（#13 Q1、ADR-0007）。
- 中文一律輸出繁體：完成時先把片段轉成繁體輸出（:mod:`app.services.traditional_output`），
  輸出格式、凍結的原始轉錄副本與片段都從轉換後的片段產生（ADR-0002）。
- 計價照模型能力的計價方式；實際以 Flex 或批次完成的照設定打折。供應商已經回應的用量，
  不論任務完成、失敗或取消都記下用量與費用（供應商照樣收費）：例如取消之前已經轉完的段、
  回應解析不出任何一行、分段轉錄的某一段失敗、片段寫不進去。失敗與取消時 token 數是 0
  （例如本機的模型不回報 token）就不記，紀錄的用量留空。
- 先保留音檔，再清理：不論結果（連被強制終止也一樣），輸入音檔先搬進保留區。關掉保留
  音檔時刪掉上傳檔；開著卻保留不成時，上傳檔是唯一的一份，留在暫存區。最後清掉任務
  登記與取消旗標。收尾的每一步各自保護，失敗只記 log。
- 不會再執行的任務也收尾（:meth:`TaskLifecycle.abandon`）：在佇列中被撤銷、應用程式關閉時還在
  排隊的任務，一樣留下紀錄、保留或清理上傳檔。
- 收尾之後才宣告結果：畫面收到完成、失敗或取消時，紀錄、片段與保留音檔都已就緒。
- 失敗帶錯誤碼：讓任務失敗的例外由 :func:`app.core.error_codes.describe` 對應成錯誤碼與細節，
  一起記進任務紀錄、隨失敗的狀態廣播送給畫面；畫面照錯誤碼顯示原因與下一步（#24 門檻 4）。
- 資料庫出錯不轉述例外：資料庫例外一接到就換成只有類型與原因的
  :class:`~app.exceptions.TaskDatabaseError`（:func:`~app.database.session.without_db_details`），
  記進 log 與往上拋給執行模式的都是它；畫面與任務紀錄只有錯誤碼，細節是空的。
  批次在任務之外出錯時也照這條規則。

狀態廣播與查詢取消只經由執行模式模組（:mod:`app.runtime.run_mode`）。
"""

from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Union, cast

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.error_codes import ErrorCode, Failure, TaskFailedError, describe
from app.core.task_status import TaskStatus
from app.database.session import SessionLocal, without_db_details
from app.exceptions import TranscriptionCancelledError
from app.provider.base import ProgressAndCancel
from app.provider.registry import UnsupportedModelError, model_capabilities
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.runtime import run_mode
from app.runtime.run_mode import publish_status
from app.services import audio_store, output_format, traditional_output
from app.services.calculator.models import CalculationItem
from app.services.calculator.service import CalculatorService
from app.services.transcription.models import TranscriptionResponse, TranscriptionTaskResult
from app.utils.audio import get_audio_duration
from app.utils.logger import setup_logger
from app.utils.paths import is_temp_upload

logger = setup_logger(__name__)

Transcribe = Callable[[Path, ProgressAndCancel], TranscriptionTaskResult]
"""轉錄輸入音檔；見 :meth:`TaskLifecycle.run`。"""


@dataclass(frozen=True)
class Task:
    """任務生命週期要知道的一個任務：任務紀錄的欄位、狀態廣播送到哪裡，以及輸入音檔。"""

    file_path: Optional[str]
    """輸入音檔（上傳檔），收尾時保留或清理。不知道在哪裡時是 None：改版前送出、升級後才從復原入口
    結束的批次沒有存下上傳檔。"""
    file_uid: str
    """畫面上的檔案代號：取消旗標與任務登記以它為鍵，狀態廣播也帶著它。"""
    client_id: str
    """狀態廣播送到哪一條 WebSocket：單檔任務是 ``file_uid``，批次的檔案是批次。"""
    original_filename: str
    provider: str
    model: str
    source_lang: str
    multi_speaker: Optional[bool]
    """Multi-Speaker 開關：輸出格式帶不帶說話者標記（見 :func:`app.services.output_format.shows_speaker_labels`）。
    只有接回開關做出來之前開始的任務（:meth:`TaskLifecycle.resume`）時是 None。"""
    target_lang: Optional[str] = None
    session_id: Optional[str] = None
    batch_id: Optional[str] = None
    """所屬的批次；單檔任務是 None。批次的檔案記在批次底下，狀態廣播也帶著它。"""


@dataclass(frozen=True)
class _Outcome:
    """任務這一次執行的結果：要宣告的狀態，以及收尾之後要回傳或往上拋的東西。"""

    status: TaskStatus
    text: str
    """宣告時的狀態文字。"""
    broadcast_result: Optional[dict] = None
    """完成時隨宣告送給畫面的結果。"""
    error: Optional[Exception] = None
    """收尾之後往上拋，讓執行模式記下失敗。"""
    return_value: Optional[dict] = None
    """:meth:`TaskLifecycle.run` 回傳給執行模式的值。"""
    failure: Optional[Failure] = None
    """失敗時的錯誤碼與細節，隨宣告送給畫面。"""


def _cancelled() -> _Outcome:
    return _Outcome(TaskStatus.CANCELLED, "任務已取消", return_value={"cancelled": True})


def _failed(failure: Failure, error: Exception) -> _Outcome:
    """失敗：宣告時的狀態文字帶著細節，錯誤碼與細節另外放在宣告的欄位裡（見 :meth:`TaskLifecycle._publish`）。"""
    text = f"任務失敗: {failure.detail}" if failure.detail else "任務失敗"
    return _Outcome(TaskStatus.FAILED, text, error=error, failure=failure)


class TaskLifecycle:
    """一個任務的生命週期；每次執行建立一個（Docker 模式的重派會讓同一個任務再執行一次），
    批次的檔案在結果回來時另外接回一個（:meth:`resume`）。"""

    def __init__(self, task_uuid: str, task: Task, *, duration: float = 0.0,
                 started_at: Optional[float] = None):
        """``duration`` 與 ``started_at`` 給接回的任務用：開始時量到的長度，以及開始的時間（處理時間
        從這裡算起）。新的任務在開始時才量長度，從建立這個物件時算起。"""
        self._task_uuid = task_uuid
        self._task = task
        self._input = _resolve_input(task.file_path, task_uuid)
        self._started_at = time.time() if started_at is None else started_at
        self._duration = duration
        self._records = TranscriptionLogRepository()
        self._progress = ProgressAndCancel(self._report, self._cancel_requested)

    @classmethod
    def resume(cls, task_uuid: str, *, file_path: Optional[str],
               duration: float) -> Optional[TaskLifecycle]:
        """接回一個已經開始的任務，接著結束它（:meth:`end`）：批次的檔案在結果回來時，可能已經是
        另一個行程（重啟之後從復原入口）。

        任務的資訊讀它自己的任務紀錄，處理時間從紀錄建立的時間算起；``file_path`` 與 ``duration``
        是開始時的輸入音檔與量到的長度。紀錄不在了（例如使用者把它刪掉了）時回 None。

        Raises:
            TaskDatabaseError: 讀不到任務紀錄（資料庫出錯）。
        """
        try:
            with SessionLocal() as db:
                record = TranscriptionLogRepository().get(db, task_uuid)
        except SQLAlchemyError as e:
            raise without_db_details(e) from None
        if record is None:
            return None
        task = Task(
            file_path=file_path,
            file_uid=record.file_uid or "",
            client_id=record.batch_id or record.file_uid or "",
            original_filename=record.original_filename or "",
            provider=record.provider or "",
            model=record.model_used or "",
            source_lang=record.source_language or "",
            multi_speaker=cast(Optional[bool], record.multi_speaker),
            target_lang=record.target_language,
            session_id=record.session_id,
            batch_id=record.batch_id,
        )
        started_at = record.request_timestamp.timestamp() if record.request_timestamp else None
        return cls(str(task_uuid), task, duration=duration, started_at=started_at)

    @property
    def task_uuid(self) -> str:
        return self._task_uuid

    @property
    def progress(self) -> ProgressAndCancel:
        """這個任務的進度與取消物件；批次在送出之前用它回報這個檔案的進度。"""
        return self._progress

    @property
    def duration(self) -> float:
        """輸入音檔的長度（秒），開始時量；量不到時是 0。"""
        return self._duration

    def run(self, transcribe: Transcribe) -> dict:
        """跑完這個任務，回傳給執行模式的結果。

        ``transcribe`` 拿到輸入音檔與進度與取消物件，回傳轉錄結果。它自己產生的暫存檔與
        供應商資源要自己清，輸入音檔不能動。使用者取消時拋
        :class:`~app.exceptions.TranscriptionCancelledError`，其他例外都算失敗。

        Raises:
            Exception: 失敗時，收尾與宣告都做完之後，原本的例外往上拋，讓執行模式記下失敗；
                資料庫例外換成 :class:`~app.exceptions.TaskDatabaseError`。
        """
        outcome = self._to_the_end(lambda db: self._attempt(db, transcribe))
        if outcome.error is not None:
            raise outcome.error
        return outcome.return_value or {}

    def start(self) -> None:
        """開始：建立任務紀錄並廣播處理中，量輸入音檔的長度。批次在送出之前對每個檔案呼叫一次，
        之後由 :meth:`end` 結束。

        Raises:
            TaskDatabaseError: 任務紀錄寫不進去。
        """
        try:
            with SessionLocal() as db:
                self._start(db)
        except SQLAlchemyError as e:
            raise without_db_details(e) from None

    def end(self, result: Union[TranscriptionTaskResult, Exception]) -> Optional[dict]:
        """結束一個已經開始的任務（批次的檔案）：記下完成或失敗、收尾，再宣告結果。

        ``result`` 是供應商的轉錄結果，時間已經在原音檔的時間軸上；或是讓這個任務失敗的例外，例如
        上傳失敗、整個批次失敗。回傳完成時送給畫面的結果，沒有完成時是 None。不往上拋例外：一個
        檔案失敗不影響同一批的其他檔案。
        """
        if isinstance(result, Exception):
            error = result
            outcome = self._to_the_end(lambda db: self._failed_attempt(db, error))
        else:
            outcome = self._to_the_end(lambda db: self._conclude(db, result))
        return outcome.broadcast_result if outcome.status == TaskStatus.COMPLETED else None

    def abandon(self, *, cancelled: bool) -> None:
        """收尾一個不會再執行的任務：在佇列中被撤銷（``cancelled``），或應用程式關閉時還在排隊。

        和開始前就取消的任務一樣留下任務紀錄（被撤銷的記成已取消，關閉時還在排隊的記成
        失敗），再照一般的收尾保留或清理上傳檔、清掉登記與取消旗標。不宣告結果：撤銷時
        取消端點已經宣告過了，關閉時也沒有畫面在聽。
        """
        with SessionLocal() as db:
            try:
                if cancelled:
                    self._cancel_before_start(db)
                else:
                    self._fail_before_start(db, Failure(
                        ErrorCode.INTERRUPTED, "應用程式關閉時任務還在排隊，沒有開始轉錄"))
            except Exception as e:
                logger.error(
                    f"任務 {self._task_uuid} 無法更新任務紀錄: {without_db_details(e)}")
            finally:
                self._finish(db)

    # ── 狀態轉換 ──────────────────────────────────────────────────
    def _to_the_end(self, step: Callable[[Session], _Outcome]) -> _Outcome:
        """做完一次狀態轉換之後一定收尾，收尾之後才宣告：畫面收到結果時，紀錄、片段與保留音檔都已
        就緒。"""
        outcome: Optional[_Outcome] = None
        with SessionLocal() as db:
            try:
                outcome = step(db)
            except Exception as e:
                # 連任務紀錄都寫不進去（例如資料庫連不上）：照樣收尾，宣告失敗
                error = without_db_details(e)
                logger.error(f"任務 {self._task_uuid} 無法更新任務紀錄: {error}")
                outcome = _failed(describe(error), error)
            finally:
                # 一定收尾。被強制終止時（Docker 模式的 gevent 丟 GreenletExit，不是 Exception）
                # 例外照樣往上拋、不宣告結果，但上傳的音檔已經保留或清掉
                self._finish(db)
        self._announce(outcome)
        return outcome

    def _attempt(self, db: Session, transcribe: Transcribe) -> _Outcome:
        try:
            if self._progress.cancel_requested():
                return self._cancel_before_start(db)
            self._start(db)
            result = transcribe(self._input, self._progress)
        except Exception as e:
            return self._failed_attempt(db, e)
        return self._conclude(db, result)

    def _conclude(self, db: Session, result: TranscriptionTaskResult) -> _Outcome:
        """供應商轉錄完了：記下完成；使用者已經取消、或沒有轉錄結果時，改記取消或失敗。

        不論記成哪一種，``result`` 的用量都照記：供應商已經回應，照樣收費。
        """
        try:
            if self._progress.cancel_requested():
                # 供應商沒理會取消、照樣跑完：使用者已經取消，不採用這次的結果（用量照記）
                return self._cancel(db, result)
            if not result.success:
                # 失敗結果的 text 是錯誤描述而非 LRC，不能標成完成、產出空字幕
                raise TaskFailedError(result.error_code or ErrorCode.INTERNAL, result.text)
            if not result.segments:
                # 每一段都沒有內容（例如 Gemini 沒寫出任何帶時間戳的行）：沒有轉錄結果，一樣不能
                # 標成完成；text 是供應商寫的原因
                raise TaskFailedError(result.error_code or ErrorCode.NO_TRANSCRIPT, result.text)
            return self._complete(db, result)
        except Exception as e:
            return self._failed_attempt(db, e, usage=result)

    def _failed_attempt(self, db: Session, error: Exception,
                        usage: Optional[TranscriptionTaskResult] = None) -> _Outcome:
        """這一次沒有完成：使用者取消的記成取消，其他記成失敗。

        ``usage`` 是轉錄結果回來之後才失敗時，供應商已經回應的用量，記成哪一種都照記；使用者取消
        時，到目前為止的用量附在 :class:`~app.exceptions.TranscriptionCancelledError` 上。
        """
        # 失敗的寫入可能讓 session 停在 pending rollback，先復原才寫得進紀錄
        db.rollback()
        if isinstance(error, TranscriptionCancelledError):
            # 取消前已經轉完的段落，供應商照樣收費：用量照記
            return self._cancel(db, error.billed_usage)
        if self._progress.cancel_requested():
            # 使用者取消之後才冒出的錯誤（例如 503 剛好回來）也算取消：不算失敗
            return self._cancel(db, usage)
        return self._fail(db, without_db_details(error), usage)

    def _start(self, db: Session) -> None:
        """開始：建立任務紀錄，廣播處理中。"""
        task = self._task
        self._records.insert_log(db, {"status": TaskStatus.PROCESSING, **self._record_fields()})
        if task.session_id:
            logger.info(
                f"TranscriptionLog created session_id={task.session_id} file_uid={task.file_uid}")
        else:
            logger.warning(f"TranscriptionLog missing session_id file_uid={task.file_uid}")
        logger.info(f"Transcription task started. Task ID: {self._task_uuid}")

        self._progress.report("檔案處理與分析...")
        self._duration = get_audio_duration(self._input) or 0.0
        if self._duration > 0:
            logger.info(
                f"Audio file {self._input.name} for task {self._task_uuid}: "
                f"{self._duration:.2f} seconds")
        else:
            logger.warning(f"Could not read audio duration for {self._input.name}.")

    def _complete(self, db: Session, result: TranscriptionTaskResult) -> _Outcome:
        """完成：中文轉成繁體輸出，產生輸出格式、計價、存任務紀錄與片段。"""
        logger.info(
            f"Transcription complete. Task ID: {self._task_uuid}. "
            f"Tokens used: {result.total_tokens:,}")

        # 輸出格式、凍結的原始轉錄副本與片段都從轉換後的片段產生（ADR-0002、ADR-0007）
        result = result.model_copy(update={"segments": traditional_output.convert(
            result.segments, source_lang=self._task.source_lang,
            target_lang=self._task.target_lang)})

        self._progress.report("正在轉換字幕格式...")
        transcripts = output_format.for_result(
            result, speaker_labels=output_format.shows_speaker_labels(self._task.multi_speaker),
        ).model_dump()

        self._progress.report("正在計算費用...")
        elapsed = self._elapsed()
        tokens, cost = self._price(result, elapsed)

        # 和片段寫進同一個交易：看得到完成時片段已經在了；片段寫不進去就連完成一起退回，照失敗處理
        completed = self._records.update_log_unless_cancelled(db, self._task_uuid, {
            "status": TaskStatus.COMPLETED,
            "audio_duration_seconds": self._duration,
            "processing_time_seconds": elapsed,
            "total_tokens": tokens,
            "cost": cost,
            "completed_at": datetime.now(),
            # 凍結的原始轉錄副本（ADR-0007）：不論 Multi-Speaker 開關都帶說話者標記
            "lrc_content": output_format.frozen_copy(result) or None,
            "service_tier_used": result.service_tier_used or "standard",
        }, commit=False)
        # 只有取消不蓋掉；其他狀態照實記成完成（例如啟動清掃把還在跑的任務記成了失敗）
        if not completed and self._is_record_cancelled(db):
            # 取消端點剛好先把紀錄記成已取消：完成不蓋掉取消，也不宣告完成
            return self._cancel(db, result)
        if completed:
            self._save_segments(db, result)
            db.commit()
            logger.info(f"Task status updated to COMPLETED. Task ID: {self._task_uuid}")
        else:
            # 片段也不寫：沒有紀錄的片段找不到，Postgres 也會擋下
            logger.warning(f"找不到任務紀錄（可能在處理中被刪掉了）: {self._task_uuid}")

        response = _completed_response(
            self._task_uuid, transcripts, tokens=tokens, cost=cost, model=self._task.model,
            source_language=self._task.source_lang, duration=self._duration,
            speaker_count=_speaker_count(result.segments))
        return _Outcome(TaskStatus.COMPLETED, "任務完成", broadcast_result=response,
                        return_value={"raw_lrc_text": transcripts["lrc"]})

    def _cancel(self, db: Session, usage: Optional[TranscriptionTaskResult] = None) -> _Outcome:
        """取消：不是失敗，任務紀錄寫 CANCELLED。

        使用者取消之後供應商才跑完、或分段轉錄已經轉完幾段（``usage`` 是它們的用量）時，
        照樣記下用量與費用（見 :meth:`_usage`）：供應商照樣收費（例如 Gemini 已經送出的生成），
        計費頁不能少算。
        """
        logger.info(f"Transcription task {self._task_uuid} cancelled by user.")
        self._records.update_log(
            db, self._task_uuid, {**self._cancelled_fields(), **self._usage(usage)})
        return _cancelled()

    def _cancel_before_start(self, db: Session) -> _Outcome:
        """開始前就取消：建立已取消的任務紀錄（重派時改寫第一次執行的紀錄），不呼叫供應商。

        任務在佇列等待時被取消，revoke 卻沒送到 worker（例如 worker 當時離線），
        任務照樣會開始，靠取消旗標在這裡攔下。不會再執行的任務（:meth:`abandon`）也記成這樣。
        """
        logger.info(
            f"任務 {self._task_uuid} 在啟動前已被取消 (file_uid={self._task.file_uid})")
        self._records.insert_log(db, {**self._record_fields(), **self._cancelled_fields()})
        return _cancelled()

    def _fail_before_start(self, db: Session, failure: Failure) -> None:
        """開始前就停了、也不是使用者取消的（例如應用程式關閉時還在排隊）：記成失敗並寫明原因。"""
        logger.warning(f"任務 {self._task_uuid} 沒有開始就停了: {failure.detail}")
        self._records.insert_log(db, {
            **self._record_fields(),
            "status": TaskStatus.FAILED,
            **failure.fields(),
            "completed_at": datetime.now(),
        })

    def _fail(self, db: Session, error: Exception,
              usage: Optional[TranscriptionTaskResult] = None) -> _Outcome:
        """失敗：任務紀錄寫 FAILED 與錯誤碼、細節（:func:`~app.core.error_codes.describe`）。

        供應商已經回應過（``usage`` 是它的用量）時，連同用量與費用一起記下（見 :meth:`_usage`）：
        供應商照樣收費，儀表板與計費頁不能少算。
        """
        logger.error(
            f"Transcription task failed for log ID: {self._task_uuid}\n"
            f"{''.join(traceback.format_exception(error))}")
        failure = describe(error)
        failed = self._records.update_log_unless_cancelled(db, self._task_uuid, {
            "status": TaskStatus.FAILED,
            **failure.fields(),
            "processing_time_seconds": self._elapsed(),
            **self._usage(usage),
        })
        if not failed and self._is_record_cancelled(db):
            # 取消端點剛好先把紀錄記成已取消：失敗不蓋掉取消
            return self._cancel(db, usage)
        return _failed(failure, error)

    def _finish(self, db: Session) -> None:
        """收尾：先保留音檔，再清理。

        每一步各自保護：失敗只記 log，不中斷後面的步驟，也不蓋掉任務的結果。
        """
        # 音檔搬進保留區：成功要給校正介面重播，失敗／取消要留給再開任務與診斷；
        # 同一個任務再執行一次時（Docker 模式的重派、批次從復原入口再結束一次）從保留區找回它
        retained = None
        if self._input is not None:
            with self._best_effort("保留音檔"):
                retained = audio_store.retain(self._input, self._task_uuid)
        if retained:
            with self._best_effort("記下保留音檔"):
                # 前面失敗的寫入可能讓 session 停在 pending rollback，先復原才寫得進去
                db.rollback()
                self._records.update_log(db, self._task_uuid, {"audio_filename": retained})

        if not retained and self._input is not None:
            if audio_store.enabled():
                # 開著保留音檔卻沒保留成（例如保留區寫不進去）：上傳檔是唯一的一份，不刪，
                # 留在暫存區，之後由啟動清掃處理
                logger.warning(
                    f"音檔沒保留成，上傳檔留在暫存區 (task={self._task_uuid}): {self._input}")
            else:
                with self._best_effort("清理上傳檔"):
                    _delete_upload(self._input)
        # 任務結束後登記與旗標都已無作用，清掉：取消端點才不會去撤銷早已結束的任務，
        # 旗標也不會影響同一檔案之後再開的任務（同一檔案已經登記了新任務時不動它的）
        with self._best_effort("清除任務登記與取消旗標"):
            run_mode.get().task_ended(self._task.file_uid, self._task_uuid)

    @contextmanager
    def _best_effort(self, step: str) -> Iterator[None]:
        """收尾的一步：失敗只記 log。"""
        try:
            yield
        except Exception as e:
            logger.warning(f"{step}失敗 (task={self._task_uuid}): {without_db_details(e)}")

    # ── 進度與廣播 ────────────────────────────────────────────────
    def _report(self, text: str) -> None:
        self._publish(text, TaskStatus.PROCESSING)

    def _cancel_requested(self) -> bool:
        return run_mode.get().is_cancel_requested(self._task.file_uid)

    def _announce(self, outcome: _Outcome) -> None:
        self._publish(outcome.text, outcome.status, outcome.broadcast_result, outcome.failure)

    def _publish(self, text: str, status: TaskStatus, result: Optional[dict] = None,
                 failure: Optional[Failure] = None) -> None:
        """狀態廣播；失敗時另外帶錯誤碼與細節（``error_code``、``error_message``，和任務紀錄同名）。"""
        task = self._task
        extra = {"batch_id": task.batch_id} if task.batch_id else {}
        if failure is not None:
            extra.update(failure.fields())
        publish_status(
            task.client_id,
            self._task_uuid,
            text,
            status_code=status,
            file_uid=task.file_uid,
            result_data=result,
            extra=extra or None,
        )

    # ── 小工具 ────────────────────────────────────────────────────
    def _record_fields(self) -> dict:
        task = self._task
        return {
            "original_filename": task.original_filename,
            "model_used": task.model,
            "source_language": task.source_lang,
            "multi_speaker": task.multi_speaker,
            "task_uuid": self._task_uuid,
            "provider": task.provider,
            "target_language": task.target_lang,
            "is_batch": task.batch_id is not None,
            "batch_id": task.batch_id,
            "session_id": task.session_id,
            "file_uid": task.file_uid,
        }

    def _cancelled_fields(self) -> dict:
        return {
            "status": TaskStatus.CANCELLED,
            "error_message": "使用者取消任務",
            "processing_time_seconds": self._elapsed(),
            "completed_at": datetime.now(),
        }

    def _is_record_cancelled(self, db: Session) -> bool:
        return self._records.current_status(db, self._task_uuid) == TaskStatus.CANCELLED

    def _usage(self, result: Optional[TranscriptionTaskResult]) -> dict:
        """取消或失敗時，供應商回報的用量與據此算出的費用，記進任務紀錄的欄位。

        沒有用量時是空的，紀錄的用量欄位留空：沒有結果（例如呼叫本身就出錯），或 token 數是 0
        （例如本機的模型不回報 token）。和 :meth:`_price` 一樣，token 數是 0 就沒有東西可以計價。
        """
        if result is None or result.total_tokens <= 0:
            return {}
        tokens, cost = self._price(result, self._elapsed())
        return {
            "audio_duration_seconds": self._duration,
            "total_tokens": tokens,
            "cost": cost,
            "service_tier_used": result.service_tier_used or "standard",
        }

    def _price(self, result: TranscriptionTaskResult, elapsed: float) -> tuple[int, float]:
        """計價：回傳 (總 token 數, 費用)；收不收費照模型能力的計價方式。"""
        items = []
        if result.total_tokens > 0:
            items.append(CalculationItem(
                task_name="total_transcription",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                content_type="audio",
            ))
        metrics = CalculatorService().calculate_metrics(
            items=items,
            model=self._task.model,
            processing_time_seconds=elapsed,
            audio_duration_seconds=self._duration,
        )
        if self._pricing() == "free":
            return metrics.total_tokens, 0.0
        cost = metrics.cost
        # 實際以 Flex 完成（不是退回標準）或以批次完成才打折
        discount = _discount(result.service_tier_used)
        if discount is not None:
            cost *= discount
            logger.info(f"處理模式是 {result.service_tier_used}，費用套用 {int(discount * 100)}% 折扣")
        logger.info(f"Metrics calculated. Task ID: {self._task_uuid}. Cost: ${cost:.6f}")
        return metrics.total_tokens, cost

    def _pricing(self) -> str:
        try:
            return model_capabilities(self._task.provider, self._task.model).pricing
        except UnsupportedModelError:
            # 派送時驗證過；之後才從模型清單拿掉的模型照 token 計價
            return "per_token"

    def _save_segments(self, db: Session, result: TranscriptionTaskResult) -> None:
        """片段是校正介面的資料來源；同一個任務再完成一次時，使用者動過的片段不刪、不覆寫
        （ADR-0007），其他片段換成這次的結果。只寫進目前的交易，由 :meth:`_complete` 提交。

        片段已經依開始時間排好、序號連續（分段轉錄合併時、批次放回原音檔的時間軸時排好）。
        """
        if not result.segments:
            return
        count = TranscriptSegmentRepository.replace_untouched(db, self._task_uuid, result.segments)
        logger.info(f"已寫入 {count} 個轉錄片段 (task={self._task_uuid})")

    def _elapsed(self) -> float:
        return time.time() - self._started_at


def completed_result(db: Session, task_uuid) -> Optional[dict]:
    """一個完成的任務完成時送給畫面的結果，從任務紀錄與片段重新產生（輸出格式模組），和完成時
    廣播的相同；沒有紀錄、或紀錄不是完成時是 None。批次取回結果時用它，不另外存一份。"""
    record = TranscriptionLogRepository().get(db, task_uuid)
    if record is None or record.status != TaskStatus.COMPLETED:
        return None
    transcripts = {fmt.value: output_format.for_task(db, record, fmt) or ""
                   for fmt in output_format.OutputFormat}
    segments = TranscriptSegmentRepository.segments_for_task(db, record.task_uuid)
    return _completed_response(
        record.task_uuid, transcripts, tokens=record.total_tokens or 0, cost=record.cost or 0.0,
        model=record.model_used or "", source_language=record.source_language or "",
        duration=record.audio_duration_seconds or 0.0, speaker_count=_speaker_count(segments))


def _completed_response(task_uuid, transcripts: dict, *, tokens: int, cost: float, model: str,
                        source_language: str, duration: float, speaker_count: int) -> dict:
    """完成時送給畫面的結果：四種輸出格式、計價與說話者人數。"""
    response = TranscriptionResponse(
        task_uuid=task_uuid,
        transcripts=transcripts,
        tokens_used=tokens,
        cost=cost,
        model=model,
        source_language=source_language,
        audio_duration_seconds=duration,
        speaker_count=speaker_count,
    ).model_dump()
    response["task_uuid"] = response["task_uuid"].hex
    return response


def _speaker_count(segments: List[Dict[str, Any]]) -> int:
    """片段裡出現幾個不同的說話者編號（結果頁顯示的人數，#13 Q1）；沒有說話者編號的片段不算。"""
    return len({seg["speaker"] for seg in segments if seg.get("speaker")})


def _discount(service_tier: Optional[str]) -> Optional[float]:
    """這個處理模式的折扣率（費用乘上它）：Flex 與批次照設定，其他不打折，是 None。"""
    settings = get_settings()
    return {"flex": settings.flex_cost_discount,
            "batch": settings.batch_cost_discount}.get(service_tier or "")


def _resolve_input(file_path: Optional[str], task_uuid: str) -> Optional[Path]:
    """輸入音檔；同一個任務再執行一次時（Docker 模式的重派、批次從復原入口再結束一次），上傳檔
    已經搬進保留區，改從那裡找。不知道上傳檔在哪裡時是 None。

    重派沿用同一個 task id，所以保留檔名找得到。
    """
    if not file_path:
        return None
    path = Path(file_path)
    if path.exists():
        return path
    retained = audio_store.resolve(f"{task_uuid}{path.suffix.lower()}")
    if retained:
        logger.info(f"輸入檔已不在 temp_uploads，改用保留的音檔: {retained.name}")
        return retained
    return path


def _delete_upload(path: Path) -> None:
    """刪掉沒有保留下來的上傳檔；只刪 temp_uploads 裡的，路徑異常時寧可不刪。"""
    if path.exists() and is_temp_upload(path):
        path.unlink()
        logger.info(f"已清理上傳檔: {path.name}")
