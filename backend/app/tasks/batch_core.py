"""批次（純同步 Python，與任務框架無關）：以批次模式一起送出的一組任務，每個音檔仍各是一個任務。

Docker 模式由 :mod:`app.celery.batch_task` 的 Celery shim 包裝執行，免安裝模式由
:class:`app.runtime.in_process.InProcessRunMode` 丟進行程內執行緒池；兩邊共用這裡的同一份流程。

批次是一個狀態機（:mod:`app.core.batch_state`），執行與復原是它的兩個入口：

- 執行（:func:`run_batch`）：建立批次（上傳中）→ 開始每個檔案 → 去靜音、上傳 → 送出（輪詢中）
  → 輪詢到批次結束 → 結束送出的檔案（完成／失敗）
- 復原（:func:`run_recover`，由 :func:`start_recovery` 派送）：重啟或輪詢中斷之後接手（復原中）
  → 輪詢到批次結束 → 結束送出的檔案

上傳時停住的批次（例如上傳時關掉了應用程式）沒有送出、不能復原：執行批次的行程再啟動時，由
:func:`end_stopped_uploads` 記成失敗。

送出之後只有一份流程（:class:`_Watch`）：輪詢到批次結束，再結束送出的每個檔案。每個檔案在
batch_files 資料表各一列，建立批次時就有（#116 之前送出的批次在應用程式啟動時或復原入口補上，見
:mod:`app.tasks.older_batches`）；送出時記下它是第幾個請求與語音視圖的序列化形式。結束時
讀回這些列，供應商的結果用存下的語音視圖放回原音檔的時間軸，交給任務生命週期記下完成或失敗、收尾、
宣告，再把結果狀態記回它的列；已經完成的檔案不再結束一次（兩邊同時看著同一個批次時，先看到批次
結束的那邊結束它）。執行時用自己的任務生命週期，復原時從任務紀錄接回。取回結果
（:func:`completed_results`）從完成的檔案的任務紀錄與片段讀出，不另外存一份。

每個檔案都走任務生命週期（:mod:`app.tasks.lifecycle`），和單檔任務一樣有任務紀錄、片段、計價與
狀態廣播；去靜音也和單檔任務一樣經語音視圖（:func:`app.services.silence_removal.speech_view`）。

送出之前就失敗的檔案（開不了供應商、上傳失敗、送不出去）當場結束。輪詢中斷時，送出的檔案照失敗
結束、批次記成失敗，之後還能從復原入口結束成完成；應用程式在輪詢時重啟的話，批次停在輪詢中、檔案
停在處理中，一樣從復原入口接著結束。上傳、送出與查詢遇到暫時錯誤（429、503）時，等一段時間再做
一次那一步（:meth:`~app.exceptions.TransientError.wait_seconds`）。執行模式不重試整個批次：檔案都
已經開始，整個批次再執行一次會替同一個音檔再開一個任務。資料庫出錯時照任務生命週期的規則，不轉述
例外（:func:`~app.tasks.lifecycle.without_db_details`）。
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple, TypeVar, Union

from sqlalchemy.orm import Session

from app.celery.models import BatchFileItemParams, BatchTranscriptionTaskParams
from app.core.batch_state import IN_PROGRESS, BatchState
from app.core.config import get_settings
from app.core.default_prompt import build_prompt
from app.core.task_status import TaskStatus
from app.database.models import BatchFile, BatchJob
from app.database.session import SessionLocal
from app.exceptions import TransientError
from app.provider.base import BatchProvider, BatchStatus
from app.provider.registry import open_batch_provider, provider_info, reopen_batch_provider
from app.repositories.batch_job_repository import BatchJobRepository
from app.runtime import run_mode
from app.runtime.run_mode import publish_status
from app.services.silence_removal import SpeechTimeline, SpeechView, speech_view
from app.services.transcription.models import TranscriptionTaskResult
from app.tasks import older_batches
from app.tasks.lifecycle import (
    Task,
    TaskLifecycle,
    completed_result,
    shown_to_user,
    without_db_details,
)
from app.utils.logger import setup_logger
from app.utils.paths import delete_temp_files

logger = setup_logger(__name__)

T = TypeVar("T")

FIRST_POLL_SECONDS = 10.0
"""送出之後等幾秒才第一次查；之後每次多等一半，最多 :data:`MAX_POLL_SECONDS`。"""
MAX_POLL_SECONDS = 60.0

Publish = Callable[..., None]
"""批次層級的狀態廣播：``publish(text, status_code=TaskStatus.PROCESSING)``。"""

FileOutcome = Union[TranscriptionTaskResult, Exception]
"""一個檔案的結果：供應商的轉錄結果（時間在原音檔的時間軸上），或讓它失敗的例外。"""


class _BatchError(Exception):
    """批次讓一個檔案失敗的原因，例如上傳失敗、整個批次失敗；訊息給使用者看。"""


class _Interrupted(_BatchError):
    """輪詢中斷：送出的檔案都照失敗結束、批次記成失敗了，之後還能從復原入口接手。"""


STOPPED_WHILE_UPLOADING = "上傳時服務停止了，批次沒有送出"
"""上傳時停住的批次，還沒結束的檔案失敗的原因（:func:`end_stopped_uploads`）。"""


def run_batch(task_params_dict: dict, task_uuid: str) -> None:
    """執行入口：執行一個批次；``task_uuid`` 是執行模式給這次執行的代號，批次層級的廣播帶著它。

    Raises:
        Exception: 中途出錯時，還沒結束的檔案都照失敗結束、批次記成失敗之後，原本的例外往上拋，
            讓執行模式記下失敗；資料庫例外換成 :class:`~app.exceptions.TaskDatabaseError`。
    """
    _Run(BatchTranscriptionTaskParams.model_validate(task_params_dict), task_uuid).run()


def recovery_refusal(db: Session, job: BatchJob) -> Optional[str]:
    """這個批次不能從復原入口接手的原因（給使用者看）；可以接手時是 None。

    還沒送出的不能接手。送出了卻沒有記下送出的檔案的，是 #116 之前送出、補不了列的批次：舊的 JSON
    欄位讀不懂（:func:`_file_rows`）。已經完成的由 :func:`start_recovery` 擋下。
    """
    return _refusal(job, _file_rows(db, job))


def recoverable(job: BatchJob, files: Sequence[BatchFile], *, alive: Optional[bool]) -> bool:
    """任務頁要不要給這個批次「恢復」：沒有任務看著它，而且可以從復原入口接手
    （:func:`recovery_refusal`）。沒有任務看著的是失敗了（例如輪詢中斷），或還在進行的狀態、看著它的
    任務卻不在了（例如應用程式重啟了）。

    ``files`` 是這個批次每個檔案的列；``alive`` 是看著它的任務還在不在，不知道時是 None（不給）。
    批次清單傳的是任務頁的 ``is_alive``：Docker 模式查不出來（PENDING）、派出之後又超過 5 分鐘的當成
    不在，所以在佇列裡排了這麼久的復原也會給（重複接手是安全的，見 :func:`start_recovery`）；worker
    被砍掉之後 Celery 仍把它的任務當成執行中，這時不給。
    """
    unwatched = job.status == BatchState.FAILED or (job.status in IN_PROGRESS and alive is False)
    return unwatched and _refusal(job, files) is None


def _refusal(job: BatchJob, files: Sequence[BatchFile]) -> Optional[str]:
    """:func:`recovery_refusal`，用已經讀出來的檔案的列。"""
    if not job.gemini_job_name:
        return "此任務尚未建立 Gemini batch job，無法恢復"
    if not _submitted(files):
        return "這個批次是舊版送出的，讀不出它的檔案清單，無法恢復"
    return None


def start_recovery(db: Session, batch_id: str, api_key: str) -> bool:
    """派送復原入口接手批次：記成復原中，交給執行模式執行 :func:`run_recover`，派出去的任務記成
    看著這個批次的任務。回傳有沒有接手：批次剛好完成了就不接手，之後取回結果即可。

    先用 :func:`recovery_refusal` 確認可以接手。還有任務看著這個批次時照樣接手：Docker 模式的
    worker 被砍掉之後，Celery 仍把它的任務當成執行中，看不出來；兩邊都看著時，已經完成的檔案不會
    再被結束一次（:class:`_Watch`）。
    """
    jobs = BatchJobRepository()
    if not jobs.move(db, batch_id, BatchState.RECOVERING):
        return False
    task_id = run_mode.get().submit_recover(batch_id, api_key)
    jobs.update_job(db, batch_id, {"celery_task_id": task_id})
    return True


def run_recover(batch_id: str, api_key: str) -> None:
    """復原入口：重啟或輪詢中斷之後接手批次（復原中），接著輪詢到批次結束，和執行同一份流程。

    只接手送出過、還沒完成的批次（輪詢中、失敗、復原中，或在跑的時候被歸檔的）；不能接手的
    （:func:`recovery_refusal`，或已經完成）不動它。建立不了供應商轉接器、或接手之後出錯時，批次
    退回輪詢中，之後可以再復原。輪詢中斷時和執行一樣，送出的檔案照失敗結束、批次記成失敗。
    不往上拋例外：出錯只記 log。
    """
    publish = _publisher(batch_id, "")
    jobs = BatchJobRepository()

    def back_to_polling(text: str) -> None:
        """接手了卻接不下去：批次退回輪詢中，再宣告這次復原結束。記不下來只記 log。"""
        try:
            with SessionLocal() as db:
                jobs.move(db, batch_id, BatchState.POLLING, only_from={BatchState.RECOVERING})
        except Exception as e:
            logger.error(f"批次 {batch_id} 無法記回輪詢中: {without_db_details(e)}")
        publish(text, TaskStatus.BATCH_COMPLETED)

    try:
        with SessionLocal() as db:
            job = jobs.get_job(db, batch_id)
            if job is None:
                logger.error(f"復原找不到批次: {batch_id}")
                return
            refusal = recovery_refusal(db, job)
            name = job.gemini_job_name
            stored = json.loads(job.task_params_json) if job.task_params_json else {}
        if refusal is not None or not name:
            logger.error(f"批次 {batch_id} 不能復原: {refusal}")
            publish(refusal or "批次不能恢復", TaskStatus.BATCH_COMPLETED)
            return
        with SessionLocal() as db:
            if not jobs.move(db, batch_id, BatchState.RECOVERING):
                logger.info(f"批次 {batch_id} 已經完成，不必復原")
                return
    except Exception as e:
        logger.error(f"復原批次 {batch_id} 時讀不到批次: {without_db_details(e)}")
        return

    try:
        publish("正在恢復批次的結果...")
        provider = stored.get("provider", "google")
        try:
            # 復原不驗證模型：升級後模型清單拿掉了送出時的模型，進行中的批次也收得回來
            adapter = reopen_batch_provider(provider, stored.get("model", ""), api_key)
        except ValueError as e:
            logger.warning(f"復原批次 {batch_id} 無法建立供應商轉接器: {e}")
            back_to_polling("API Key 無效")
            return
        try:
            _Watch(batch_id, publish, _resumed, started_at=time.time()).until_done(
                adapter, name, provider_info(provider).label)
        except _Interrupted as e:
            logger.warning(f"復原批次 {batch_id} 時輪詢中斷: {e}")
        finally:
            # 接手批次的轉接器一樣要釋放（見 BatchProvider）
            adapter.release()
    except Exception as e:
        error = without_db_details(e)
        logger.error(f"復原批次 {batch_id} 失敗:\n{''.join(traceback.format_exception(error))}")
        back_to_polling(f"恢復批次失敗: {shown_to_user(error)}")


def end_stopped_uploads() -> int:
    """執行批次的行程啟動時，把上傳中的批次記成失敗，回傳記了幾個：之前執行它的行程已經停了。

    呼叫端只能是執行批次的行程，在它開始執行任何批次之前：免安裝模式是應用程式啟動時（批次跑在
    應用程式的行程裡），Docker 模式是消費預設佇列的 worker 啟動時（:mod:`app.celery.celery`）。
    Docker 模式只有一個這樣的 worker；Celery 收到任務就確認（沒有開 ``acks_late``），被砍掉的
    worker 在跑的批次不會再派給別人，所以它一啟動，上傳中的批次就沒有任務看著了。API 啟動時不收：
    API 單獨重啟（例如 ``--reload``）時 worker 可能還在上傳。

    批次還沒送出（沒有記下送出的批次名稱），不能從復原入口接手，只能記成失敗。還沒結束的檔案從
    任務紀錄接回任務生命週期、照失敗結束：和其他失敗一樣保留或清理上傳檔、宣告結果；已經結束的
    （例如上傳失敗）不動。每個批次各自處理：出錯的只記 log、留在上傳中，下次啟動再收，不影響
    其他批次。

    送出之後、記下送出的批次名稱之前就停住的批次也在這裡：供應商那邊的批次照樣會跑完，但沒有
    記下名稱，拿不回結果。
    """
    jobs = BatchJobRepository()
    with SessionLocal() as db:
        stopped = jobs.batch_ids_in(db, BatchState.UPLOADING)
    ended = 0
    for batch_id in stopped:
        try:
            # 先結束檔案、再記成失敗：中途又停了的話，下次啟動還找得到這個批次與沒結束的檔案
            with SessionLocal() as db:
                unfinished = [row for row in jobs.files(db, batch_id)
                              if row.status == TaskStatus.PROCESSING]
            for row in unfinished:
                _end_stopped_file(batch_id, row)
            with SessionLocal() as db:
                if jobs.move(db, batch_id, BatchState.FAILED, only_from={BatchState.UPLOADING}):
                    ended += 1
                    logger.warning(f"批次 {batch_id} 在上傳時停住了，記成失敗")
        except Exception as e:
            logger.error(f"批次 {batch_id} 無法記成失敗: {without_db_details(e)}")
    return ended


def _end_stopped_file(batch_id: str, row: BatchFile) -> None:
    """上傳時停住的批次裡還沒結束的一個檔案，照失敗結束；任務紀錄不在了的只記下列的結果狀態。"""
    lifecycle = TaskLifecycle.resume(str(row.task_uuid), file_path=row.file_path,
                                     duration=row.audio_duration_seconds or 0.0)
    if lifecycle is None:
        _record_status(batch_id, str(row.task_uuid), TaskStatus.FAILED)
        return
    _end_file(batch_id, lifecycle, _BatchError(STOPPED_WHILE_UPLOADING))


def abandon_batch(task_params_dict: dict) -> None:
    """收尾一個不會再執行的批次（應用程式關閉時還在排隊）：和單檔任務一樣，每個檔案都留下任務紀錄、
    照保留設定處理上傳檔（:meth:`TaskLifecycle.abandon`）；批次記成失敗，每個檔案的列也是。

    批次沒有撤銷的入口，不會再執行的只有這一種。
    """
    params = BatchTranscriptionTaskParams.model_validate(task_params_dict)
    files = _files(params)
    try:
        with SessionLocal() as db:
            _create_record(db, params, files, run_id=None, file_status=TaskStatus.FAILED)
            BatchJobRepository().move(db, params.batch_id, BatchState.FAILED)
    except Exception as e:
        # 任務紀錄記在批次紀錄底下，建立不了也照樣處理每個檔案的上傳檔
        logger.error(f"批次 {params.batch_id} 無法建立批次紀錄: {without_db_details(e)}")
    for file in files:
        file.lifecycle.abandon(cancelled=False)


def completed_results(db: Session, job: BatchJob) -> Optional[List[Tuple[BatchFile, dict]]]:
    """取回結果：批次已經結束時，完成的檔案各自連同完成時送給畫面的結果，依在批次裡的順序。

    批次還沒結束時是 None，要從復原入口接手：不是完成或已取回、在跑的時候被歸檔了還有送出的檔案在
    處理中，或沒有記下檔案（#116 之前送出、補不了列的批次，見 :func:`recovery_refusal`）。
    完成沒有照列上的結果狀態，看的是任務紀錄：結果狀態記不下來時（只記 log），任務紀錄已經記下了
    完成。結果從任務紀錄與片段讀出（:func:`~app.tasks.lifecycle.completed_result`），和完成時廣播的
    相同；任務紀錄不在了（例如使用者刪掉了）的檔案略過。
    """
    if job.status not in (BatchState.COMPLETED, BatchState.RETRIEVED):
        return None
    rows = _file_rows(db, job)
    if not rows:
        return None
    if job.status == BatchState.RETRIEVED and any(
            file.status == TaskStatus.PROCESSING for file in _submitted(rows)):
        return None
    completed = []
    for row in rows:
        result = completed_result(db, row.task_uuid)
        if result is not None:
            completed.append((row, result))
    return completed


def _file_rows(db: Session, job: BatchJob) -> List[BatchFile]:
    """復原入口讀這個批次每個檔案的列。#116 之前送出、還沒補列的批次（應用程式啟動時補每一個，但舊版的
    worker 可能在這一版啟動之後才送出）先從舊欄位補上（:mod:`app.tasks.older_batches`）；補不了時沒有列。
    """
    jobs = BatchJobRepository()
    rows = jobs.files(db, job.batch_id)
    if not rows and older_batches.add_file_rows(db, job.batch_id):
        rows = jobs.files(db, job.batch_id)
    return rows


# ── 執行 ─────────────────────────────────────────────────────────

@dataclass
class _File:
    """執行中的一個檔案：在批次裡的順序、它的任務生命週期，以及送出之前的語音視圖與上傳的代號。"""

    seq: int
    item: BatchFileItemParams
    lifecycle: TaskLifecycle
    view: Optional[SpeechView] = None
    handle: Any = None
    """:meth:`BatchProvider.upload` 的代號。"""
    ended: bool = False
    """已經交給任務生命週期結束了（或另一邊已經結束了它）。"""


class _Run:
    """一個批次的一次執行。"""

    def __init__(self, params: BatchTranscriptionTaskParams, run_id: str):
        self._params = params
        self._batch_id = params.batch_id
        self._run_id = run_id
        self._publish = _publisher(params.batch_id, run_id)
        self._started_at = time.time()
        self._files = _files(params)
        self._jobs = BatchJobRepository()
        self._created = False
        """這次執行建立了批次紀錄；同一個批次 id 已經有紀錄時是 False，失敗時不動別人的批次。"""

    def run(self) -> None:
        adapter: Optional[BatchProvider] = None
        failure: Optional[Exception] = None
        try:
            with SessionLocal() as db:
                _create_record(db, self._params, self._files, run_id=self._run_id)
            self._created = True
            self._publish(f"正在初始化批次 ({len(self._files)} 個檔案)...")
            for file in self._files:
                file.lifecycle.start()
            self._save_durations()
            # 模型不支援批次、金鑰無效都在這裡失敗：每個檔案都照失敗結束
            adapter = open_batch_provider(
                self._params.provider, self._params.model, self._params.api_keys)
            label = provider_info(self._params.provider).label

            uploaded = self._upload(adapter)
            if not uploaded:
                self._fail_batch("所有檔案都沒有上傳成功，批次結束")
                return
            name = self._submit(adapter, uploaded)
            self._save_submitted(name, uploaded)
            self._publish(f"批次已送出給 {label}，共 {len(uploaded)} 個檔案，等待處理中...",
                          TaskStatus.BATCH_SUBMITTED)

            _Watch(self._batch_id, self._publish, self._own_lifecycle,
                   started_at=self._started_at).until_done(adapter, name, label)
            # 存下來的檔案清單少了誰（不該發生）：那個檔案照樣要結束，不停在處理中
            for file in uploaded:
                self._end(file, _BatchError("批次紀錄裡找不到這個檔案，無法取回結果"))
        except _Interrupted as e:
            # 送出的檔案與批次都已經照失敗結束；沒讀到的檔案（不該發生）照同一個原因結束
            failure = e
            for file in self._files:
                self._end(file, e)
        except Exception as e:
            failure = without_db_details(e)
            # 還沒結束的檔案都照失敗結束：畫面靠每個檔案自己的結果離開處理中
            for file in self._files:
                self._end(file, failure)
            self._fail_batch(f"批次失敗: {shown_to_user(failure)}")
        finally:
            if adapter is not None:
                # 刪掉上傳到供應商的遠端檔
                adapter.release()
        if failure is not None:
            raise failure

    def _end(self, file: _File, result: FileOutcome) -> None:
        """還沒結束的檔案交給它的任務生命週期結束；已經結束的不動。"""
        if not file.ended:
            file.ended = True
            _end_file(self._batch_id, file.lifecycle, result)

    def _own_lifecycle(self, submitted: _Submitted) -> Optional[TaskLifecycle]:
        """執行時結束送出的檔案，用這次執行自己的任務生命週期（:class:`_Watch`）；交出去之後這次
        執行不再結束它。"""
        for file in self._files:
            if file.lifecycle.task_uuid == submitted.task_uuid and not file.ended:
                file.ended = True
                return file.lifecycle
        return None

    def _save_durations(self) -> None:
        """每個檔案的列記下開始時量到的長度：結果在重啟之後才回來時，接回的任務照它計價。"""
        with SessionLocal() as db:
            for file in self._files:
                self._jobs.update_file(db, file.lifecycle.task_uuid, {
                    "audio_duration_seconds": file.lifecycle.duration}, commit=False)
            db.commit()

    def _upload(self, adapter: BatchProvider) -> List[_File]:
        """每個檔案去靜音拿到語音視圖，上傳要送進模型的音檔；上傳失敗的檔案當場結束。

        回傳上傳成功的檔案。語音視圖的暫存檔（轉成的 wav、只剩語音的音檔）上傳之後就用不到，馬上清掉。
        """
        remove_silence = adapter.capabilities()[self._params.model].remove_silence
        temp_dir = get_settings().temp_uploads_path
        uploaded: List[_File] = []
        for number, file in enumerate(self._files, start=1):
            name = file.item.original_filename
            file.lifecycle.progress.report(f"前處理與上傳 ({number}/{len(self._files)}): {name}")
            try:
                file.view = speech_view(
                    Path(file.item.file_path),
                    file.lifecycle.duration,
                    remove_silence=remove_silence,
                    temp_dir=temp_dir,
                    task_id=file.lifecycle.task_uuid,
                    original_filename=name,
                )
                file.handle = _retrying(self._publish, f"上傳 {name} ", adapter.upload,
                                        file.view.audio)
            except Exception as e:
                logger.error(f"上傳檔案失敗 {name}: {e}", exc_info=True)
                self._end(file, _BatchError(f"檔案上傳失敗: {e}"))
                continue
            finally:
                if file.view is not None:
                    delete_temp_files(file.view.temp_files)
            uploaded.append(file)
        return uploaded

    def _submit(self, adapter: BatchProvider, uploaded: List[_File]) -> str:
        requests = [(file.handle, self._prompt(file.item)) for file in uploaded]
        try:
            name = _retrying(self._publish, "送出批次", adapter.submit_batch, requests,
                             f"transcription-{self._batch_id[:8]}")
        except Exception as e:
            raise _BatchError(f"送出批次失敗: {e}") from e
        logger.info(f"批次已送出: {name}")
        return name

    def _save_submitted(self, name: str, uploaded: List[_File]) -> None:
        """存下送出的批次（輪詢中），以及每個送出的檔案是第幾個請求、語音視圖的序列化形式，同一個
        交易：結果回來時（可能在重啟之後）從這裡結束每個檔案的任務。"""
        with SessionLocal() as db:
            self._jobs.update_job(db, self._batch_id, {"gemini_job_name": name}, commit=False)
            for index, file in enumerate(uploaded):
                self._jobs.update_file(db, file.lifecycle.task_uuid, {
                    "request_index": index,
                    "speech_view_json": json.dumps(file.view.serialized()),
                }, commit=False)
            self._jobs.move(db, self._batch_id, BatchState.POLLING, commit=False)
            db.commit()

    def _prompt(self, item: BatchFileItemParams) -> str:
        """這個檔案的提示詞：個別檔案的設定優先，沒設定的用批次的。"""
        params = self._params
        return build_prompt(
            source_lang=item.source_lang or params.source_lang,
            target_lang=item.target_lang or params.target_lang,
            multi_speaker=params.multi_speaker if item.multi_speaker is None else item.multi_speaker,
            template=params.prompt_template,
            supplement=item.prompt or params.prompt,
        )

    def _fail_batch(self, text: str) -> None:
        """批次沒有正常結束：批次記成失敗，再宣告批次結束。記不下來只記 log；這次執行沒有建立批次
        紀錄時（同一個批次 id 又送了一次）不動那個批次。"""
        if self._created:
            try:
                with SessionLocal() as db:
                    self._jobs.move(db, self._batch_id, BatchState.FAILED)
            except Exception as e:
                logger.error(f"批次 {self._batch_id} 無法記成失敗: {without_db_details(e)}")
        self._publish(text, TaskStatus.BATCH_COMPLETED)


# ── 送出之後（執行與復原共用）─────────────────────────────────────

@dataclass(frozen=True)
class _Submitted:
    """送出的一個檔案，從它在 batch_files 的列讀回來的樣子。"""

    request_index: int
    """送出時是第幾個請求，批次的結果也照這個順序。"""
    task_uuid: str
    file_uid: str
    original_filename: str
    duration: float
    file_path: Optional[str]
    timeline: SpeechTimeline
    """送進模型的語音視圖怎麼對回原音檔，從序列化形式讀回。"""
    status: str
    """讀回來時的結果狀態。"""


def _resumed(file: _Submitted) -> Optional[TaskLifecycle]:
    """復原時結束送出的檔案：從它的任務紀錄接回任務生命週期；紀錄不在了時是 None。"""
    return TaskLifecycle.resume(file.task_uuid, file_path=file.file_path, duration=file.duration)


class _Watch:
    """送出之後的批次：輪詢到批次結束，再結束送出的每個檔案（執行與復原共用）。

    ``lifecycle_of`` 給每個送出的檔案它的任務生命週期：執行時用這次執行自己的，復原時從任務紀錄
    接回（:func:`_resumed`）；給不出來的（例如使用者把紀錄刪掉了）沒有結果，結果狀態記成失敗。
    """

    def __init__(self, batch_id: str, publish: Publish,
                 lifecycle_of: Callable[[_Submitted], Optional[TaskLifecycle]], *,
                 started_at: float):
        self._batch_id = batch_id
        self._publish = publish
        self._lifecycle_of = lifecycle_of
        self._started_at = started_at
        self._jobs = BatchJobRepository()

    def until_done(self, adapter: BatchProvider, name: str, label: str) -> None:
        """輪詢到批次結束，結束送出的每個檔案；批次記成完成（整個批次失敗時是失敗），宣告批次結束。

        Raises:
            _Interrupted: 查詢一直失敗、輪詢中斷：送出的檔案都照失敗結束、批次記成失敗之後才拋。
        """
        try:
            status = self._poll(adapter, name, label)
        except Exception as e:
            interrupted = _Interrupted(f"查詢批次狀態失敗: {e}")
            self._end_files(lambda file: interrupted, failure=f"批次失敗: {interrupted}")
            raise interrupted from e
        logger.info(f"批次 {self._batch_id} 結束，狀態: {status.state}")
        self._end_files(lambda file: _result_of(status, file),
                        failure=None if status.succeeded else _failed_state(status))

    def _poll(self, adapter: BatchProvider, name: str, label: str) -> BatchStatus:
        """輪詢到批次結束；查詢遇到暫時錯誤時等一段時間再查（見 :func:`_retrying`）。"""
        interval = FIRST_POLL_SECONDS
        while True:
            status = _retrying(self._publish, "查詢批次狀態", adapter.poll_batch, name)
            if status.done:
                return status
            waited = int(time.time() - self._started_at)
            self._publish(f"{label} 批次處理中... (已等待 {waited} 秒, 狀態: {status.state})")
            time.sleep(interval)
            interval = min(interval * 1.5, MAX_POLL_SECONDS)

    def _end_files(self, outcome_of: Callable[[_Submitted], FileOutcome], *,
                   failure: Optional[str]) -> None:
        """結束送出的每個檔案，記下批次的結果，再宣告批次結束；``failure`` 是批次沒有成功結束時
        給使用者看的原因。一個檔案出錯不影響其他檔案。

        已經完成的檔案不再結束一次：兩邊同時看著同一個批次時，另一邊可能已經結束了它，晚到的一邊
        （例如輪詢中斷了）不能把它改記成失敗。
        """
        with SessionLocal() as db:
            submitted = _submitted(self._jobs.files(db, self._batch_id))
        self._publish(failure or "批次結束，正在處理結果...")
        completed = 0
        for file in submitted:
            try:
                lifecycle = self._lifecycle_of(file)
            except Exception as e:
                logger.error(
                    f"批次 {self._batch_id} 的 {file.file_uid} 接不回任務: {without_db_details(e)}")
                lifecycle = None
            if file.status == TaskStatus.COMPLETED:
                completed += 1
                continue
            if lifecycle is None:
                # 沒有任務可以結束：這個檔案沒有結果。結果狀態照樣記下，取回結果時才不會一直等它
                logger.warning(f"批次 {self._batch_id} 的 {file.file_uid} 找不到任務，記成失敗")
                _record_status(self._batch_id, file.task_uuid, TaskStatus.FAILED)
                continue
            try:
                outcome = outcome_of(file)
            except Exception as e:
                # 結果放不回原音檔的時間軸（例如片段的時間不是數字）：這個檔案照失敗結束
                outcome = _BatchError(f"結果放不回原音檔的時間軸: {e}")
            # 拿到任務生命週期之後一定結束：回報進度與結束都不往上拋例外
            lifecycle.progress.report(
                f"處理結果 ({file.request_index + 1}/{len(submitted)}): {file.original_filename}")
            if _end_file(self._batch_id, lifecycle, outcome) is not None:
                completed += 1
        with SessionLocal() as db:
            self._jobs.move(db, self._batch_id,
                            BatchState.FAILED if failure else BatchState.COMPLETED)
        logger.info(f"批次 {self._batch_id}: {completed}/{len(submitted)} 個檔案完成")
        self._publish(failure or f"批次全部完成 (耗時 {time.time() - self._started_at:.1f} 秒)",
                      TaskStatus.BATCH_COMPLETED)


def _end_file(batch_id: str, lifecycle: TaskLifecycle, outcome: FileOutcome) -> Optional[dict]:
    """交給任務生命週期結束這個檔案（不往上拋例外），再把結果狀態記回它的列；回傳完成時送給畫面
    的結果，沒有完成時是 None。"""
    result = lifecycle.end(outcome)
    _record_status(batch_id, lifecycle.task_uuid,
                   TaskStatus.COMPLETED if result is not None else TaskStatus.FAILED)
    return result


def _record_status(batch_id: str, task_uuid: str, status: TaskStatus) -> None:
    """把結果狀態記回這個檔案的列。記不下來只記 log：任務紀錄已經記下了結果。"""
    try:
        with SessionLocal() as db:
            BatchJobRepository().update_file(db, task_uuid, {"status": status})
    except Exception as e:
        logger.error(f"批次 {batch_id} 無法記下任務 {task_uuid} 的結果狀態: {without_db_details(e)}")


def _submitted(rows: Sequence[BatchFile]) -> List[_Submitted]:
    """送出的檔案（記下了第幾個請求的列），依送出的順序。"""
    sent = sorted((row for row in rows if row.request_index is not None),
                  key=lambda row: row.request_index)
    return [_Submitted(
        request_index=row.request_index,
        task_uuid=str(row.task_uuid),
        file_uid=row.file_uid,
        original_filename=row.original_filename,
        duration=row.audio_duration_seconds or 0.0,
        file_path=row.file_path,
        timeline=SpeechTimeline.from_serialized(json.loads(row.speech_view_json or "[]")),
        status=row.status,
    ) for row in sent]


def _result_of(status: BatchStatus, file: _Submitted) -> FileOutcome:
    """這個檔案的結果：供應商給的轉錄結果放回原音檔的時間軸；整個批次失敗、或沒有這個檔案的結果時，
    是讓它失敗的原因。"""
    if not status.succeeded:
        return _BatchError(_failed_state(status))
    if file.request_index >= len(status.results):
        return _BatchError("供應商沒有回傳這個檔案的結果")
    result = status.results[file.request_index]
    if not result.success:
        return result
    return result.model_copy(update={"segments": file.timeline.in_original_order(result.segments)})


def _failed_state(status: BatchStatus) -> str:
    """整個批次失敗時給使用者看的原因：帶著供應商回報的狀態。"""
    return f"批次失敗，狀態: {status.state}"


# ── 小工具 ───────────────────────────────────────────────────────

def _retrying(publish: Publish, step: str, call: Callable[..., T], *args: Any) -> T:
    """做一步；遇到暫時錯誤時先廣播，等一段時間（:meth:`TransientError.wait_seconds`）再做一次，
    最多重試 ``TRANSIENT_ERROR_RETRIES`` 次，用完就往上拋。

    和分段轉錄重試一段的規則相同；差在批次沒有使用者取消，等待不必邊等邊查取消。
    """
    retries = get_settings().transient_error_retries
    retry = 0
    while True:
        try:
            return call(*args)
        except TransientError as error:
            if retry >= retries:
                raise
            retry += 1
            seconds = error.wait_seconds(retry)
            notice = (f"{step}遇到暫時錯誤（{error.reason or error}），{seconds:g} 秒後第 "
                      f"{retry} 次重試（最多 {retries} 次）...")
            logger.warning(f"{notice} {error}")
            publish(notice)
            time.sleep(seconds)


def _files(params: BatchTranscriptionTaskParams) -> List[_File]:
    """批次裡的每個檔案，各有自己的任務生命週期（新的任務紀錄 id）。"""
    return [_File(seq, item, TaskLifecycle(str(uuid.uuid4()), _task(item, params)))
            for seq, item in enumerate(params.files)]


def _task(item: BatchFileItemParams, params: BatchTranscriptionTaskParams) -> Task:
    """批次裡的一個檔案是一個任務：個別檔案的設定優先，沒設定的用批次的。"""
    return Task(
        file_path=item.file_path,
        file_uid=item.file_uid,
        client_id=params.batch_id,
        original_filename=item.original_filename,
        provider=params.provider,
        model=params.model,
        source_lang=item.source_lang or params.source_lang,
        target_lang=item.target_lang or params.target_lang,
        session_id=params.session_id or params.batch_id,
        batch_id=params.batch_id,
    )


def _create_record(db: Session, params: BatchTranscriptionTaskParams, files: Sequence[_File], *,
                   run_id: Optional[str], file_status: TaskStatus = TaskStatus.PROCESSING) -> None:
    """建立批次紀錄（上傳中）與每個檔案的一列：每個檔案的任務紀錄記在它底下。存下的任務參數不含
    API 金鑰，提示詞是批次層級的預設；實際送出的是每個檔案各自的提示詞。"""
    job = BatchJob(
        batch_id=params.batch_id,
        task_params_json=json.dumps({
            "model": params.model,
            "provider": params.provider,
            "source_lang": params.source_lang,
            "target_lang": params.target_lang,
            "prompt": build_prompt(
                source_lang=params.source_lang,
                target_lang=params.target_lang,
                multi_speaker=params.multi_speaker,
                template=params.prompt_template,
                supplement=params.prompt,
            ),
        }),
        celery_task_id=run_id,
        file_count=len(files),
        session_id=params.session_id or params.batch_id,
    )
    BatchJobRepository().create_job(db, job, [BatchFile(
        task_uuid=uuid.UUID(file.lifecycle.task_uuid),
        batch_id=params.batch_id,
        seq=file.seq,
        file_uid=file.item.file_uid,
        original_filename=file.item.original_filename,
        file_path=file.item.file_path,
        status=file_status,
    ) for file in files])


def _publisher(batch_id: str, run_id: str) -> Publish:
    """批次層級的狀態廣播（沒有 file_uid）：送到批次的連線，帶著 batch_id 與這次執行的代號。"""
    def publish(text: str, status_code: TaskStatus = TaskStatus.PROCESSING) -> None:
        publish_status(batch_id, run_id, text, status_code=status_code,
                       extra={"batch_id": batch_id})
    return publish
