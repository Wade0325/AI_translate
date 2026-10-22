"""批次（純同步 Python，與任務框架無關）：以批次模式一起送出的一組任務，每個音檔仍各是一個任務。

Docker 模式由 :mod:`app.celery.batch_task` 的 Celery shim 包裝執行，免安裝模式由
:class:`app.runtime.in_process.InProcessRunMode` 丟進行程內執行緒池；兩邊共用這裡的同一份流程。

每個檔案都走任務生命週期（:mod:`app.tasks.lifecycle`），和單檔任務一樣有任務紀錄、片段、計價與
狀態廣播；去靜音也和單檔任務一樣經語音視圖（:func:`app.services.silence_removal.speech_view`）。
兩個入口：

- 執行（:func:`run_batch`）：開始每個檔案 → 去靜音、上傳 → 送出 → 輪詢到批次結束 → 結束送出的檔案
- 復原（:func:`run_recover`）：重啟或輪詢中斷之後查一次批次，結束了就結束送出的檔案

結束送出的檔案只有一份流程（:func:`_end_submitted`）：兩個入口都讀送出時存下的每個檔案（任務紀錄、
長度、上傳檔，以及語音視圖的序列化形式），供應商的結果用存下的語音視圖放回原音檔的時間軸，再交給
任務生命週期記下完成或失敗、收尾、宣告。執行時用自己的任務生命週期，復原時從任務紀錄接回。這些先存在
批次紀錄現有的 JSON 欄位，搬進 batch_files 資料表是 #116。

送出之前就失敗的檔案（開不了供應商、上傳失敗、送不出去）當場結束；輪詢中斷時，送出的檔案照失敗結束，
之後還能從復原入口結束成完成。上傳、送出與查詢遇到暫時錯誤（429、503）時，等一段時間再做一次那一步
（:meth:`~app.exceptions.TransientError.wait_seconds`）。執行模式不重試整個批次：檔案都已經開始，
整個批次再執行一次會替同一個音檔再開一個任務。資料庫出錯時照任務生命週期的規則，不轉述例外
（:func:`~app.tasks.lifecycle.without_db_details`）。
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from sqlalchemy.orm import Session

from app.celery.models import BatchFileItemParams, BatchTranscriptionTaskParams
from app.core.config import get_settings
from app.core.default_prompt import build_prompt
from app.core.task_status import TaskStatus
from app.database.models import BatchJob
from app.database.session import SessionLocal
from app.exceptions import TransientError
from app.provider.base import BatchProvider, BatchStatus
from app.provider.registry import open_batch_provider, provider_info, reopen_batch_provider
from app.repositories.batch_job_repository import BatchJobRepository
from app.runtime.run_mode import publish_status
from app.services.silence_removal import SpeechTimeline, SpeechView, speech_view
from app.services.transcription.models import TranscriptionTaskResult
from app.tasks.lifecycle import Task, TaskLifecycle, shown_to_user, without_db_details
from app.utils.logger import setup_logger
from app.utils.paths import delete_temp_files

logger = setup_logger(__name__)

T = TypeVar("T")

FIRST_POLL_SECONDS = 10.0
"""送出之後等幾秒才第一次查；之後每次多等一半，最多 :data:`MAX_POLL_SECONDS`。"""
MAX_POLL_SECONDS = 60.0

Publish = Callable[..., None]
"""批次層級的狀態廣播：``publish(text, status_code=TaskStatus.PROCESSING)``。"""


class _BatchError(Exception):
    """批次讓一個檔案失敗的原因，例如上傳失敗、整個批次失敗；訊息給使用者看。"""


def run_batch(task_params_dict: dict, task_uuid: str) -> None:
    """執行一個批次；``task_uuid`` 是執行模式給這次執行的代號，批次層級的廣播帶著它。

    Raises:
        Exception: 中途出錯時，還沒結束的檔案都照失敗結束、批次記成失敗之後，原本的例外往上拋，
            讓執行模式記下失敗；資料庫例外換成 :class:`~app.exceptions.TaskDatabaseError`。
    """
    _Run(BatchTranscriptionTaskParams.model_validate(task_params_dict), task_uuid).run()


def run_recover(batch_id: str, api_key: str) -> None:
    """復原：重啟或輪詢中斷之後查一次批次，結束了就結束送出的每個檔案，和執行同一份流程。

    還沒結束、查不到、建立不了供應商轉接器或中途出錯時，批次留在輪詢中，之後可以再復原。
    不往上拋例外：出錯只記 log。
    """
    publish = _publisher(batch_id, "")
    started_at = time.time()

    def keep_polling(text: str) -> None:
        try:
            with SessionLocal() as db:
                BatchJobRepository().update_job(db, batch_id, {"status": "POLLING"})
        except Exception as e:
            logger.error(f"批次 {batch_id} 無法記回輪詢中: {without_db_details(e)}")
        publish(text, TaskStatus.BATCH_COMPLETED)

    try:
        with SessionLocal() as db:
            job = BatchJobRepository().get_job(db, batch_id)
            name = job.gemini_job_name if job else None
            stored = json.loads(job.task_params_json) if job and job.task_params_json else {}
        if job is None:
            logger.error(f"復原找不到批次: {batch_id}")
            return
        if not name:
            logger.error(f"批次 {batch_id} 還沒有送出，無法復原")
            keep_polling("批次還沒有送出，無法恢復")
            return

        publish("正在恢復批次的結果...")
        try:
            # 復原不驗證模型：升級後模型清單拿掉了送出時的模型，進行中的批次也收得回來
            adapter = reopen_batch_provider(
                stored.get("provider", "google"), stored.get("model", ""), api_key)
        except ValueError as e:
            logger.warning(f"復原批次 {batch_id} 無法建立供應商轉接器: {e}")
            keep_polling("API Key 無效")
            return
        try:
            try:
                status = adapter.poll_batch(name)
            except Exception as e:
                keep_polling(f"查詢批次失敗: {e}")
                return
            logger.info(f"復原批次 {batch_id}: 狀態 = {status.state}")
            if not status.done:
                keep_polling(f"批次仍在進行中 ({status.state})")
                return
            _end_submitted(batch_id, status, publish, _resumed, started_at=started_at)
        finally:
            # 接手批次的轉接器一樣要釋放（見 BatchProvider）
            adapter.release()
    except Exception as e:
        error = without_db_details(e)
        logger.error(f"復原批次 {batch_id} 失敗:\n{''.join(traceback.format_exception(error))}")
        keep_polling(f"恢復批次失敗: {shown_to_user(error)}")


def abandon_batch(task_params_dict: dict) -> None:
    """收尾一個不會再執行的批次（應用程式關閉時還在排隊）：和單檔任務一樣，每個檔案都留下任務紀錄、
    照保留設定處理上傳檔（:meth:`TaskLifecycle.abandon`）；批次記成失敗。

    批次沒有撤銷的入口，不會再執行的只有這一種。
    """
    params = BatchTranscriptionTaskParams.model_validate(task_params_dict)
    try:
        with SessionLocal() as db:
            _create_record(db, params, run_id=None)
            BatchJobRepository().update_job(db, params.batch_id, {"status": "FAILED"})
    except Exception as e:
        # 任務紀錄記在批次紀錄底下，建立不了也照樣處理每個檔案的上傳檔
        logger.error(f"批次 {params.batch_id} 無法建立批次紀錄: {without_db_details(e)}")
    for item in params.files:
        TaskLifecycle(str(uuid.uuid4()), _task(item, params)).abandon(cancelled=False)


# ── 執行 ─────────────────────────────────────────────────────────

@dataclass
class _File:
    """執行中的一個檔案：它的任務生命週期，以及送出之前的語音視圖與上傳的代號。"""

    item: BatchFileItemParams
    lifecycle: TaskLifecycle
    view: Optional[SpeechView] = None
    handle: Any = None
    """:meth:`BatchProvider.upload` 的代號。"""
    ended: bool = False
    """已經交給任務生命週期結束了。"""


class _Run:
    """一個批次的一次執行。"""

    def __init__(self, params: BatchTranscriptionTaskParams, run_id: str):
        self._params = params
        self._batch_id = params.batch_id
        self._run_id = run_id
        self._publish = _publisher(params.batch_id, run_id)
        self._started_at = time.time()
        self._files = [_File(item, TaskLifecycle(str(uuid.uuid4()), _task(item, params)))
                       for item in params.files]

    def run(self) -> None:
        adapter: Optional[BatchProvider] = None
        failure: Optional[Exception] = None
        try:
            with SessionLocal() as db:
                _create_record(db, self._params, run_id=self._run_id)
            self._publish(f"正在初始化批次 ({len(self._files)} 個檔案)...")
            for file in self._files:
                file.lifecycle.start()
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

            status = self._poll(adapter, name, label)
            logger.info(f"批次 {self._batch_id} 結束，狀態: {status.state}")
            _end_submitted(self._batch_id, status, self._publish, self._own_lifecycle,
                           started_at=self._started_at)
            # 存下來的檔案清單少了誰（不該發生）：那個檔案照樣要結束，不停在處理中
            for file in uploaded:
                self._end(file, _BatchError("批次紀錄裡找不到這個檔案，無法取回結果"))
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

    def _end(self, file: _File, result: Union[TranscriptionTaskResult, Exception]) -> None:
        """還沒結束的檔案交給它的任務生命週期結束；已經結束的不動。"""
        if not file.ended:
            file.ended = True
            file.lifecycle.end(result)

    def _own_lifecycle(self, submitted: _Submitted) -> Optional[TaskLifecycle]:
        """執行時結束送出的檔案，用這次執行自己的任務生命週期（:func:`_end_submitted`）。"""
        for file in self._files:
            if file.item.file_uid == submitted.file_uid and not file.ended:
                file.ended = True
                return file.lifecycle
        return None

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
                file.handle = self._retrying(f"上傳 {name} ", adapter.upload, file.view.audio)
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
            name = self._retrying("送出批次", adapter.submit_batch, requests,
                                  f"transcription-{self._batch_id[:8]}")
        except Exception as e:
            raise _BatchError(f"送出批次失敗: {e}") from e
        logger.info(f"批次已送出: {name}")
        return name

    def _save_submitted(self, name: str, uploaded: List[_File]) -> None:
        """存下送出的批次與每個檔案（依送出的順序）：結果回來時（可能在重啟之後）從這裡結束每個
        檔案的任務；語音視圖存它的序列化形式。"""
        files = {
            str(i): {
                "file_uid": file.item.file_uid,
                "original_filename": file.item.original_filename,
                "file_path": file.item.file_path,
                "vad_segments": file.view.serialized(),
            }
            for i, file in enumerate(uploaded)
        }
        with SessionLocal() as db:
            BatchJobRepository().update_job(db, self._batch_id, {
                "gemini_job_name": name,
                "status": "POLLING",
                "file_mapping_json": json.dumps(files),
                "file_durations_json": json.dumps(
                    {file.item.file_uid: file.lifecycle.duration for file in uploaded}),
                "file_log_uuids_json": json.dumps(
                    {file.item.file_uid: file.lifecycle.task_uuid for file in uploaded}),
            })

    def _poll(self, adapter: BatchProvider, name: str, label: str) -> BatchStatus:
        """輪詢到批次結束；查詢遇到暫時錯誤時等一段時間再查（見 :meth:`_retrying`）。"""
        interval = FIRST_POLL_SECONDS
        while True:
            try:
                status = self._retrying("查詢批次狀態", adapter.poll_batch, name)
            except Exception as e:
                raise _BatchError(f"查詢批次狀態失敗: {e}") from e
            if status.done:
                return status
            waited = int(time.time() - self._started_at)
            self._publish(f"{label} 批次處理中... (已等待 {waited} 秒, 狀態: {status.state})")
            time.sleep(interval)
            interval = min(interval * 1.5, MAX_POLL_SECONDS)

    def _retrying(self, step: str, call: Callable[..., T], *args: Any) -> T:
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
                self._publish(notice)
                time.sleep(seconds)

    def _prompt(self, item: BatchFileItemParams) -> str:
        """這個檔案的提示詞：個別檔案的設定優先，沒設定的用批次的。"""
        params = self._params
        return build_prompt(
            source_lang=item.source_lang or params.source_lang,
            target_lang=item.target_lang or params.target_lang,
            multi_speaker=params.multi_speaker if item.multi_speaker is None else item.multi_speaker,
            template=(item.prompt or params.prompt) or None,
        )

    def _fail_batch(self, text: str) -> None:
        """批次沒有正常結束：批次紀錄記成失敗，再宣告批次結束。記不下來只記 log。"""
        try:
            with SessionLocal() as db:
                BatchJobRepository().update_job(db, self._batch_id, {"status": "FAILED"})
        except Exception as e:
            logger.error(f"批次 {self._batch_id} 無法記成失敗: {without_db_details(e)}")
        self._publish(text, TaskStatus.BATCH_COMPLETED)


# ── 結束送出的檔案（執行與復原共用）─────────────────────────────

@dataclass(frozen=True)
class _Submitted:
    """送出的一個檔案，從批次紀錄讀回來的樣子。"""

    position: int
    """送出時的順序，批次的結果也照這個順序。"""
    file_uid: str
    original_filename: str
    task_uuid: str
    duration: float
    file_path: Optional[str]
    """上傳檔；改版前送出的批次沒有存。"""
    timeline: SpeechTimeline
    """送進模型的語音視圖怎麼對回原音檔，從序列化形式讀回。"""


def _resumed(file: _Submitted) -> Optional[TaskLifecycle]:
    """復原時結束送出的檔案：從它的任務紀錄接回任務生命週期；紀錄不在了時是 None。"""
    return TaskLifecycle.resume(file.task_uuid, file_path=file.file_path, duration=file.duration)


def _end_submitted(
    batch_id: str,
    status: BatchStatus,
    publish: Publish,
    lifecycle_of: Callable[[_Submitted], Optional[TaskLifecycle]],
    *,
    started_at: float,
) -> None:
    """結束送出的每個檔案（執行與復原共用），記下批次的結果，再宣告批次結束。

    每個檔案讀送出時存下的資料，由 ``lifecycle_of`` 給它的任務生命週期：執行時用這次執行自己的，
    復原時從任務紀錄接回（:func:`_resumed`）；給不出來的（例如使用者把紀錄刪掉了）略過。供應商的
    結果用存下的語音視圖放回原音檔的時間軸，記下完成或失敗、收尾、宣告；整個批次失敗、或供應商沒給
    某個檔案結果時，那些檔案照失敗結束。一個檔案出錯不影響其他檔案。

    批次紀錄記成完成（整個批次失敗時是失敗），連同每個完成的檔案送給畫面的結果
    （``results_json``，取回結果的端點直接讀它）。
    """
    jobs = BatchJobRepository()
    with SessionLocal() as db:
        job = jobs.get_job(db, batch_id)
        submitted = _submitted(job) if job else []
    publish("批次結束，正在處理結果..." if status.succeeded else _failed_state(status))
    completed: Dict[str, dict] = {}
    for file in submitted:
        try:
            outcome = _result_of(status, file)
        except Exception as e:
            # 結果放不回原音檔的時間軸（例如片段的時間不是數字）：這個檔案照失敗結束
            outcome = _BatchError(f"結果放不回原音檔的時間軸: {e}")
        try:
            lifecycle = lifecycle_of(file)
        except Exception as e:
            logger.error(f"批次 {batch_id} 的 {file.file_uid} 接不回任務: {without_db_details(e)}")
            continue
        if lifecycle is None:
            logger.warning(f"批次 {batch_id} 的 {file.file_uid} 找不到任務，略過")
            continue
        # 拿到任務生命週期之後一定結束：回報進度與 end 都不往上拋例外
        lifecycle.progress.report(
            f"處理結果 ({file.position + 1}/{len(submitted)}): {file.original_filename}")
        result = lifecycle.end(outcome)
        if result is not None:
            completed[file.file_uid] = result
    with SessionLocal() as db:
        jobs.update_job(db, batch_id, {
            "status": "COMPLETED" if status.succeeded else "FAILED",
            "results_json": json.dumps(completed, default=str, ensure_ascii=False),
        })
    logger.info(f"批次 {batch_id}: {len(completed)}/{len(submitted)} 個檔案完成")
    publish(f"批次全部完成 (耗時 {time.time() - started_at:.1f} 秒)" if status.succeeded
            else _failed_state(status), TaskStatus.BATCH_COMPLETED)


def _submitted(job: BatchJob) -> List[_Submitted]:
    """批次紀錄存下的送出的檔案，依送出的順序；沒有任務紀錄 id 的略過（記 log）。

    語音視圖的序列化形式存在每個檔案的 ``vad_segments``，和改版前存的去靜音區間同一個形狀。
    """
    files = json.loads(job.file_mapping_json) if job.file_mapping_json else {}
    durations = json.loads(job.file_durations_json) if job.file_durations_json else {}
    task_uuids = json.loads(job.file_log_uuids_json) if job.file_log_uuids_json else {}
    submitted: List[_Submitted] = []
    for position, key in enumerate(sorted(files, key=int)):
        entry = files[key]
        file_uid = entry["file_uid"]
        task_uuid = task_uuids.get(file_uid)
        if not task_uuid:
            logger.warning(f"批次 {job.batch_id} 的 {file_uid} 沒有任務紀錄 id，略過")
            continue
        submitted.append(_Submitted(
            position=position,
            file_uid=file_uid,
            original_filename=entry.get("original_filename") or file_uid,
            task_uuid=task_uuid,
            duration=float(durations.get(file_uid) or 0.0),
            file_path=entry.get("file_path"),
            timeline=SpeechTimeline.from_serialized(entry.get("vad_segments")),
        ))
    return submitted


def _result_of(status: BatchStatus,
               file: _Submitted) -> Union[TranscriptionTaskResult, Exception]:
    """這個檔案的結果：供應商給的轉錄結果放回原音檔的時間軸；整個批次失敗、或沒有這個檔案的結果時，
    是讓它失敗的原因。"""
    if not status.succeeded:
        return _BatchError(_failed_state(status))
    if file.position >= len(status.results):
        return _BatchError("供應商沒有回傳這個檔案的結果")
    result = status.results[file.position]
    if not result.success:
        return result
    return result.model_copy(update={"segments": file.timeline.in_original_order(result.segments)})


def _failed_state(status: BatchStatus) -> str:
    """整個批次失敗時給使用者看的原因：帶著供應商回報的狀態。"""
    return f"批次失敗，狀態: {status.state}"


# ── 小工具 ───────────────────────────────────────────────────────

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


def _create_record(db: Session, params: BatchTranscriptionTaskParams,
                   run_id: Optional[str]) -> None:
    """建立批次紀錄（上傳中）：每個檔案的任務紀錄記在它底下。存下的任務參數不含 API 金鑰，提示詞
    是批次層級的預設；實際送出的是每個檔案各自的提示詞。"""
    jobs = BatchJobRepository()
    jobs.create_job(db, params.batch_id, json.dumps({
        "model": params.model,
        "provider": params.provider,
        "source_lang": params.source_lang,
        "target_lang": params.target_lang,
        "prompt": build_prompt(
            source_lang=params.source_lang,
            target_lang=params.target_lang,
            multi_speaker=params.multi_speaker,
            template=params.prompt or None,
        ),
    }))
    jobs.update_job(db, params.batch_id, {
        "celery_task_id": run_id,
        "file_count": len(params.files),
        "session_id": params.session_id or params.batch_id,
    })


def _publisher(batch_id: str, run_id: str) -> Publish:
    """批次層級的狀態廣播（沒有 file_uid）：送到批次的連線，帶著 batch_id 與這次執行的代號。"""
    def publish(text: str, status_code: TaskStatus = TaskStatus.PROCESSING) -> None:
        publish_status(batch_id, run_id, text, status_code=status_code,
                       extra={"batch_id": batch_id})
    return publish
