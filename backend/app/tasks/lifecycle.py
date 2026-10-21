"""任務生命週期模組：一個單檔任務的狀態轉換與副作用都在這裡。

    開始 → 進度 … → 完成／失敗／取消／暫時錯誤 → 收尾 → 宣告結果

呼叫端只給「怎麼轉錄」：拿到輸入音檔與進度與取消物件，回傳轉錄結果。任務紀錄與片段、
計價、狀態廣播、取消旗標、保留音檔與清理輸入音檔都在這裡，每條規則只寫一次：

- 取消不是失敗：任務紀錄寫 CANCELLED。開始前就取消的任務也有紀錄，不呼叫供應商；
  使用者取消之後，供應商才跑完或才出錯，都不蓋掉取消，供應商已經轉完的部分照樣記下
  用量與費用（供應商照樣收費）。其他狀態照實改寫：啟動清掃把還在跑的任務記成失敗，
  任務之後跑完就記成完成。
- 暫時錯誤不寫 FAILED：輸入音檔與取消旗標留給執行模式的重試；沒有重試了才照失敗處理。
- 完成和片段一起寫：任務紀錄記成完成（連同凍結的原始轉錄副本）和片段在同一個交易，片段
  寫不進去就照失敗處理。同一個任務再完成一次時，使用者動過的片段不刪、不覆寫（ADR-0007）。
- 先保留音檔，再清理：不論結果（連被強制終止也一樣），輸入音檔先搬進保留區。關掉保留
  音檔時刪掉上傳檔；開著卻保留不成時，上傳檔是唯一的一份，留在暫存區。最後清掉任務
  登記與取消旗標。收尾的每一步各自保護，失敗只記 log。
- 不會再執行的任務也收尾（:meth:`TaskLifecycle.abandon`）：在佇列中或等重試時被撤銷、
  應用程式關閉時還在排隊的任務，一樣留下紀錄、保留或清理上傳檔。
- 收尾之後才宣告結果：畫面收到完成、失敗或取消時，紀錄、片段與保留音檔都已就緒。
- 資料庫出錯不轉述例外：資料庫例外一接到就換成只有類型與原因的
  :class:`~app.exceptions.TaskDatabaseError`，記進 log 與往上拋給執行模式的都是它；畫面與
  任務紀錄給看得懂的固定訊息。

狀態廣播與查詢取消只經由執行模式模組（:mod:`app.runtime.run_mode`）。
"""

from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.celery.models import TranscriptionTaskParams
from app.core.config import get_settings
from app.core.task_status import TaskStatus
from app.database.session import SessionLocal, describe_db_error
from app.exceptions import TaskDatabaseError, TranscriptionCancelledError, TransientError
from app.provider.base import ProgressAndCancel
from app.provider.registry import UnsupportedModelError, model_capabilities
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.runtime import run_mode
from app.runtime.run_mode import publish_status
from app.services import audio_store, output_format
from app.services.calculator.models import CalculationItem
from app.services.calculator.service import CalculatorService
from app.services.transcription.flows import order_segments
from app.services.transcription.models import TranscriptionResponse, TranscriptionTaskResult
from app.utils.audio import get_audio_duration
from app.utils.logger import setup_logger
from app.utils.paths import is_temp_upload

logger = setup_logger(__name__)

Transcribe = Callable[[Path, ProgressAndCancel], TranscriptionTaskResult]
"""轉錄輸入音檔；見 :meth:`TaskLifecycle.run`。"""


@dataclass(frozen=True)
class _Outcome:
    """任務這一次執行的結果：要宣告的狀態，以及收尾之後要回傳或往上拋的東西。"""

    status: TaskStatus
    text: str
    """宣告時的狀態文字。"""
    broadcast_result: Optional[dict] = None
    """完成時隨宣告送給畫面的結果。"""
    error: Optional[Exception] = None
    """收尾之後往上拋，讓執行模式記下失敗或安排重試。"""
    retry: bool = False
    """暫時錯誤：執行模式會再跑一次這個任務。"""
    return_value: Optional[dict] = None
    """:meth:`TaskLifecycle.run` 回傳給執行模式的值。"""


def _cancelled() -> _Outcome:
    return _Outcome(TaskStatus.CANCELLED, "任務已取消", return_value={"cancelled": True})


_DB_ERROR_MESSAGE = "轉錄結果沒有存進資料庫，請重新轉錄"
"""資料庫出錯時給使用者看的原因；開始時就建立不了任務紀錄時也一樣沒有轉錄結果。"""


def _without_db_details(error: Exception) -> Exception:
    """資料庫例外換成 :class:`~app.exceptions.TaskDatabaseError`，其他例外原樣傳回。

    資料庫例外的訊息與它的成因（DBAPI 的原始例外）都帶著 SQL 原文，Postgres 在第一行之後
    附上的 DETAIL 還可能是寫不進去的整列（見 :func:`describe_db_error`）。換掉的例外沿用
    原本的 traceback，log 照樣看得到在哪裡出錯；執行模式也會把往上拋的例外連同 traceback
    記進 log（Docker 模式的 Celery worker），還存進 Celery 的結果後端。
    """
    if not isinstance(error, SQLAlchemyError):
        return error
    return TaskDatabaseError(describe_db_error(error)).with_traceback(error.__traceback__)


def _shown_to_user(error: Exception) -> str:
    """給使用者看的失敗原因：資料庫出錯換成看得懂的固定訊息，原因只記在 log；其他例外
    （例如供應商回報的錯誤）照例外訊息。"""
    return _DB_ERROR_MESSAGE if isinstance(error, TaskDatabaseError) else str(error)


class TaskLifecycle:
    """一個單檔任務的生命週期；每次執行（含重試）建立一個。

    ``retries_left`` 是執行模式在這次之後還會重試幾次；0 代表這是最後一次，
    暫時錯誤就照失敗處理，任務不會一直停在處理中。
    """

    def __init__(self, task_uuid: str, params: TranscriptionTaskParams, *, retries_left: int = 0):
        self._task_uuid = task_uuid
        self._params = params
        self._retries_left = retries_left
        self._input = _resolve_input(params.file_path, task_uuid)
        self._started_at = time.time()
        self._duration = 0.0
        self._records = TranscriptionLogRepository()
        self._progress = ProgressAndCancel(self._report, self._cancel_requested)

    def run(self, transcribe: Transcribe) -> dict:
        """跑完這個任務，回傳給執行模式的結果。

        ``transcribe`` 拿到輸入音檔與進度與取消物件，回傳轉錄結果。它自己產生的暫存檔與
        供應商資源要自己清，輸入音檔不能動。使用者取消時拋
        :class:`~app.exceptions.TranscriptionCancelledError`，暫時錯誤拋
        :class:`~app.exceptions.TransientError`，其他例外都算失敗。

        Raises:
            Exception: 失敗或暫時錯誤時，收尾與宣告都做完之後，原本的例外往上拋，
                讓執行模式記下失敗或安排重試；資料庫例外換成
                :class:`~app.exceptions.TaskDatabaseError`。
        """
        outcome: Optional[_Outcome] = None
        with SessionLocal() as db:
            try:
                outcome = self._attempt(db, transcribe)
            except Exception as e:
                # 連任務紀錄都寫不進去（例如資料庫連不上）：照樣收尾，宣告失敗
                error = _without_db_details(e)
                logger.error(f"任務 {self._task_uuid} 無法更新任務紀錄: {error}")
                outcome = _Outcome(
                    TaskStatus.FAILED, f"任務失敗: {_shown_to_user(error)}", error=error)
            finally:
                # 一定收尾。被強制終止時（Docker 模式的 gevent 丟 GreenletExit，不是 Exception）
                # 例外照樣往上拋、不宣告結果，但上傳的音檔已經保留或清掉
                self._finish(db, retry=outcome is not None and outcome.retry)
        # 收尾之後才宣告：畫面收到結果時，紀錄、片段與保留音檔都已就緒
        self._announce(outcome)
        if outcome.error is not None:
            raise outcome.error
        return outcome.return_value or {}

    def abandon(self, *, cancelled: bool) -> None:
        """收尾一個不會再執行的任務：在佇列中或等重試時被撤銷（``cancelled``），或應用程式
        關閉時還在排隊。

        和開始前就取消的任務一樣留下任務紀錄（被撤銷的記成已取消，關閉時還在排隊的記成
        失敗），再照一般的收尾保留或清理上傳檔、清掉登記與取消旗標。不宣告結果：撤銷時
        取消端點已經宣告過了，關閉時也沒有畫面在聽。
        """
        with SessionLocal() as db:
            try:
                if cancelled:
                    self._cancel_before_start(db)
                else:
                    self._fail_before_start(db, "應用程式關閉時任務還在排隊，沒有開始轉錄")
            except Exception as e:
                logger.error(
                    f"任務 {self._task_uuid} 無法更新任務紀錄: {_without_db_details(e)}")
            finally:
                self._finish(db, retry=False)

    # ── 狀態轉換 ──────────────────────────────────────────────────
    def _attempt(self, db: Session, transcribe: Transcribe) -> _Outcome:
        try:
            if self._progress.cancel_requested():
                return self._cancel_before_start(db)
            self._start(db)
            result = transcribe(self._input, self._progress)
            if self._progress.cancel_requested():
                # 供應商沒理會取消、照樣跑完：使用者已經取消，不採用這次的結果（用量照記）
                return self._cancel(db, result)
            if not result.success:
                # 失敗結果的 text 是錯誤描述而非 LRC，不能標成完成、產出空字幕
                raise ValueError(f"轉錄失敗: {result.text}")
            if not result.segments:
                # 每一段都沒有內容（例如 Gemini 沒寫出任何帶時間戳的行）：沒有轉錄結果，一樣不能
                # 標成完成；text 是供應商寫的原因
                raise ValueError(f"轉錄失敗: {result.text or '沒有轉錄出任何內容'}")
            return self._complete(db, result)
        except Exception as e:
            # 失敗的寫入可能讓 session 停在 pending rollback，先復原才寫得進紀錄
            db.rollback()
            if isinstance(e, TranscriptionCancelledError):
                # 取消前已經轉完的段落，供應商照樣收費：用量照記
                return self._cancel(db, e.billed_usage)
            if self._progress.cancel_requested():
                # 使用者取消之後才冒出的錯誤（例如 503 剛好回來）也算取消：不重試、不算失敗
                return self._cancel(db)
            if isinstance(e, TransientError) and self._retries_left > 0:
                return self._transient(e)
            return self._fail(db, _without_db_details(e))

    def _start(self, db: Session) -> None:
        """開始：建立任務紀錄，廣播處理中。"""
        self._records.insert_log(db, {"status": TaskStatus.PROCESSING, **self._record_fields()})
        if self._params.session_id:
            logger.info(
                f"TranscriptionLog created session_id={self._params.session_id} "
                f"file_uid={self._params.file_uid}")
        else:
            logger.warning(f"TranscriptionLog missing session_id file_uid={self._params.file_uid}")
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
        """完成：產生輸出格式、計價、存任務紀錄與片段。"""
        logger.info(
            f"Transcription complete. Task ID: {self._task_uuid}. "
            f"Tokens used: {result.total_tokens:,}")

        self._progress.report("正在轉換字幕格式...")
        transcripts = _output_formats(result)

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
            # 凍結的原始轉錄副本（ADR-0007）：和下載的 LRC 一樣由輸出格式模組從轉錄結果產生
            "lrc_content": transcripts["lrc"] or None,
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

        response = TranscriptionResponse(
            task_uuid=self._task_uuid,
            transcripts=transcripts,
            tokens_used=tokens,
            cost=cost,
            model=self._params.model,
            source_language=self._params.source_lang,
            audio_duration_seconds=self._duration,
        ).model_dump()
        response["task_uuid"] = response["task_uuid"].hex
        return _Outcome(TaskStatus.COMPLETED, "任務完成", broadcast_result=response,
                        return_value={"raw_lrc_text": transcripts["lrc"]})

    def _cancel(self, db: Session, result: Optional[TranscriptionTaskResult] = None) -> _Outcome:
        """取消：不是失敗，任務紀錄寫 CANCELLED。

        使用者取消之後供應商才跑完、或分段轉錄已經轉完幾段（``result`` 是它們的用量）時，
        照樣記下用量與費用：供應商照樣收費（例如 Gemini 已經送出的生成），帳單頁不能少算。
        """
        logger.info(f"Transcription task {self._task_uuid} cancelled by user.")
        fields = self._cancelled_fields()
        if result is not None:
            fields.update(self._usage(result))
        self._records.update_log(db, self._task_uuid, fields)
        return _cancelled()

    def _cancel_before_start(self, db: Session) -> _Outcome:
        """開始前就取消：建立已取消的任務紀錄（重試時改寫第一次執行的紀錄），不呼叫供應商。

        任務在佇列等待時被取消，revoke 卻沒送到 worker（例如 worker 當時離線），
        任務照樣會開始，靠取消旗標在這裡攔下；免安裝模式在等重試時被取消，重試開始時也在
        這裡攔下。不會再執行的任務（:meth:`abandon`）也記成這樣。
        """
        logger.info(
            f"任務 {self._task_uuid} 在啟動前已被取消 (file_uid={self._params.file_uid})")
        self._records.insert_log(db, {**self._record_fields(), **self._cancelled_fields()})
        return _cancelled()

    def _fail_before_start(self, db: Session, reason: str) -> None:
        """開始前就停了、也不是使用者取消的（例如應用程式關閉時還在排隊）：記成失敗並寫明原因。"""
        logger.warning(f"任務 {self._task_uuid} 沒有開始就停了: {reason}")
        self._records.insert_log(db, {
            **self._record_fields(),
            "status": TaskStatus.FAILED,
            "error_message": reason,
            "completed_at": datetime.now(),
        })

    def _transient(self, error: Exception) -> _Outcome:
        """暫時錯誤：不寫 FAILED，交給執行模式重試。"""
        logger.warning(
            f"Transcription task {self._task_uuid} hit transient error, will retry: {error}")
        return _Outcome(TaskStatus.PROCESSING, f"暫時性錯誤，將重試: {error}",
                        error=error, retry=True)

    def _fail(self, db: Session, error: Exception) -> _Outcome:
        """失敗：任務紀錄寫 FAILED 與錯誤訊息。"""
        logger.error(
            f"Transcription task failed for log ID: {self._task_uuid}\n"
            f"{''.join(traceback.format_exception(error))}")
        reason = _shown_to_user(error)
        failed = self._records.update_log_unless_cancelled(db, self._task_uuid, {
            "status": TaskStatus.FAILED,
            "error_message": reason,
            "processing_time_seconds": self._elapsed(),
        })
        if not failed and self._is_record_cancelled(db):
            # 取消端點剛好先把紀錄記成已取消：失敗不蓋掉取消
            return self._cancel(db)
        return _Outcome(TaskStatus.FAILED, f"任務失敗: {reason}", error=error)

    def _finish(self, db: Session, *, retry: bool) -> None:
        """收尾：先保留音檔，再清理。

        每一步各自保護：失敗只記 log，不中斷後面的步驟，也不蓋掉任務的結果。
        """
        # 音檔搬進保留區：成功要給校正介面重播，失敗／取消要留給再開任務與診斷，
        # 暫時錯誤時重試從保留區找回它
        retained = None
        with self._best_effort("保留音檔"):
            retained = audio_store.retain(self._input, self._task_uuid)
        if retained:
            with self._best_effort("記下保留音檔"):
                # 前面失敗的寫入可能讓 session 停在 pending rollback，先復原才寫得進去
                db.rollback()
                self._records.update_log(db, self._task_uuid, {"audio_filename": retained})

        if retry:
            # 輸入音檔與取消旗標都留給重試：沒保留的上傳檔原地不動，
            # 使用者在兩次執行之間的取消，重試開始時才看得到
            return
        if not retained:
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
            run_mode.get().task_ended(self._params.file_uid, self._task_uuid)

    @contextmanager
    def _best_effort(self, step: str) -> Iterator[None]:
        """收尾的一步：失敗只記 log。"""
        try:
            yield
        except Exception as e:
            logger.warning(f"{step}失敗 (task={self._task_uuid}): {_without_db_details(e)}")

    # ── 進度與廣播 ────────────────────────────────────────────────
    def _report(self, text: str) -> None:
        self._publish(text, TaskStatus.PROCESSING)

    def _cancel_requested(self) -> bool:
        return run_mode.get().is_cancel_requested(self._params.file_uid)

    def _announce(self, outcome: _Outcome) -> None:
        self._publish(outcome.text, outcome.status, outcome.broadcast_result)

    def _publish(self, text: str, status: TaskStatus, result: Optional[dict] = None) -> None:
        publish_status(
            self._params.client_id,
            self._task_uuid,
            text,
            status_code=status,
            file_uid=self._params.file_uid,
            result_data=result,
        )

    # ── 小工具 ────────────────────────────────────────────────────
    def _record_fields(self) -> dict:
        params = self._params
        return {
            "original_filename": params.original_filename,
            "model_used": params.model,
            "source_language": params.source_lang,
            "task_uuid": self._task_uuid,
            "provider": params.provider,
            "target_language": params.target_lang,
            "is_batch": False,
            "session_id": params.session_id,
            "file_uid": params.file_uid,
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

    def _usage(self, result: TranscriptionTaskResult) -> dict:
        """供應商回報的用量與據此算出的費用，記進任務紀錄的欄位。"""
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
            model=self._params.model,
            processing_time_seconds=elapsed,
            audio_duration_seconds=self._duration,
        )
        if self._pricing() == "free":
            return metrics.total_tokens, 0.0
        cost = metrics.cost
        # 實際以 Flex 完成（不是退回標準）才打折
        if result.service_tier_used == "flex":
            discount = get_settings().flex_cost_discount
            cost *= discount
            logger.info(f"Flex 處理模式生效，費用套用 {int(discount * 100)}% 折扣")
        logger.info(f"Metrics calculated. Task ID: {self._task_uuid}. Cost: ${cost:.6f}")
        return metrics.total_tokens, cost

    def _pricing(self) -> str:
        try:
            return model_capabilities(self._params.provider, self._params.model).pricing
        except UnsupportedModelError:
            # 派送時驗證過；之後才從模型清單拿掉的模型照 token 計價
            return "per_token"

    def _save_segments(self, db: Session, result: TranscriptionTaskResult) -> None:
        """片段是校正介面的資料來源；同一個任務再完成一次時，使用者動過的片段不刪、不覆寫
        （ADR-0007），其他片段換成這次的結果。只寫進目前的交易，由 :meth:`_complete` 提交。"""
        if not result.segments:
            return
        segments = order_segments(result.segments)
        count = TranscriptSegmentRepository.replace_untouched(db, self._task_uuid, segments)
        logger.info(f"已寫入 {count} 個轉錄片段 (task={self._task_uuid})")

    def _elapsed(self) -> float:
        return time.time() - self._started_at


def _output_formats(result: TranscriptionTaskResult) -> dict:
    """完成時送給畫面的四種輸出格式，由輸出格式模組產生：和之後下載的內容相同；
    凍結的原始轉錄副本也是這裡的 LRC。"""
    return output_format.for_result(result).model_dump()


def _resolve_input(file_path: str, task_uuid: str) -> Path:
    """輸入音檔；暫時錯誤的重試時，上傳檔已經搬進保留區，改從那裡找。

    Celery 重試沿用同一個 task id，所以保留檔名找得到。
    """
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
