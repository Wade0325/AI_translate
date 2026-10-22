"""執行模式的行程內轉接器（免安裝模式）。

- 派送：:class:`~app.runtime.executor.LocalExecutor` 的執行緒池取代 Celery worker
- 狀態廣播：行程內 bus，worker 執行緒的訊息經 ``call_soon_threadsafe`` 丟進
  每個訂閱者 event loop 的 :class:`asyncio.Queue`，取代 Redis pub/sub
- 取消旗標與任務登記：記憶體 + Lock；全部在同一行程內，行程生命週期即旗標生命週期

不 import celery / redis / gevent，免安裝版因此不需要這些套件。
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import AsyncIterator, Optional

from app.exceptions import GeminiTransientError
from app.runtime.executor import LocalExecutor
from app.runtime.run_mode import RegisteredTask
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class InProcessRunMode:
    def __init__(self, concurrency: int = 4, retry_backoff_max: int = 60):
        """``retry_backoff_max``：批次遇到暫時錯誤、重試整個批次前最多等幾秒，對齊 Celery 批次任務
        的 ``retry_backoff_max``；測試傳 0，不必真的等。"""
        self._executor = LocalExecutor(concurrency)
        self._retry_backoff_max = retry_backoff_max
        self._lock = threading.Lock()
        self._cancel_flags: set[str] = set()
        self._tasks: dict[str, RegisteredTask] = {}
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

    # ── 派送與控制 ────────────────────────────────────────────────
    def submit_transcription(self, task_id: str, task_params_dict: dict, queue: str) -> None:
        from app.tasks.transcribe_core import abandon_transcription, run_transcription

        def abandoned(revoked: bool) -> None:
            # 在佇列中被撤銷、或關閉時還在排隊：任務不會執行，照樣收尾
            abandon_transcription(task_params_dict, task_id, cancelled=revoked)

        # 不重試整個任務：暫時錯誤在分段轉錄裡重試出錯的那一段，和 Docker 模式相同
        self._executor.submit(
            run_transcription,
            args=(task_params_dict, task_id),
            task_id=task_id,
            queue=queue,
            on_abandoned=abandoned,
        )

    def submit_batch(self, task_params_dict: dict) -> str:
        from app.tasks.batch_core import run_batch

        task_id = str(uuid.uuid4())
        self._executor.submit(
            run_batch,
            args=(task_params_dict, task_id),
            task_id=task_id,
            retry_on=(GeminiTransientError,),
            backoff_max=self._retry_backoff_max,
        )
        return task_id

    def submit_recover(self, batch_id: str, api_key: str) -> str:
        from app.tasks.batch_core import run_recover

        task_id = str(uuid.uuid4())
        self._executor.submit(
            run_recover, args=(batch_id, api_key), task_id=task_id)
        return task_id

    def revoke(self, task_id: str, terminate: bool = False) -> None:
        # 執行緒無法強制終止，terminate 不適用
        self._executor.revoke(task_id)

    def is_alive(self, task_id: str) -> Optional[bool]:
        if not task_id:
            return None
        return self._executor.is_alive(task_id)

    # ── 狀態廣播 ──────────────────────────────────────────────────
    def publish(self, message: dict) -> None:
        # JSON round-trip：與 Redis 路徑相同的序列化語意（datetime 等統一轉字串）
        payload = json.loads(json.dumps(message, default=str, ensure_ascii=False))
        with self._lock:
            subscribers = list(self._subscribers)
        if not subscribers:
            logger.warning("沒有狀態訂閱者，狀態訊息被丟棄")
            return
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except RuntimeError:
                # event loop 已關閉（應用程式 shutdown 中）
                logger.warning("event loop 已關閉，狀態訊息未送出")

    async def subscribe(self) -> AsyncIterator[dict]:
        queue: asyncio.Queue = asyncio.Queue()
        subscriber = (asyncio.get_running_loop(), queue)
        with self._lock:
            self._subscribers.append(subscriber)
        logger.info("已訂閱行程內狀態 bus。")
        try:
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                self._subscribers.remove(subscriber)

    # ── 取消旗標與任務登記 ────────────────────────────────────────
    def request_cancel(self, file_uid: str) -> None:
        with self._lock:
            self._cancel_flags.add(file_uid)

    def is_cancel_requested(self, file_uid: str) -> bool:
        with self._lock:
            return file_uid in self._cancel_flags

    def clear_cancel(self, file_uid: str) -> None:
        with self._lock:
            self._cancel_flags.discard(file_uid)

    def register_task(self, file_uid: str, task_id: str, *, can_terminate: bool) -> None:
        with self._lock:
            self._tasks[file_uid] = RegisteredTask(task_id, can_terminate)

    def registered_task(self, file_uid: str) -> Optional[RegisteredTask]:
        with self._lock:
            return self._tasks.get(file_uid)

    def task_ended(self, file_uid: str, task_id: str) -> None:
        with self._lock:
            registered = self._tasks.get(file_uid)
            if registered is not None and registered.task_id != task_id:
                return
            self._tasks.pop(file_uid, None)
            self._cancel_flags.discard(file_uid)

    # ── 生命週期 ──────────────────────────────────────────────────
    def close(self, wait: bool = False) -> None:
        """``wait=True`` 等執行中的任務結束（測試收尾用）；關閉應用程式時不等。"""
        self._executor.shutdown(wait=wait)
