"""standalone 模式的行程內任務執行器（取代 Celery worker）。

- 兩個執行緒池對齊 Docker 部署的 worker 配置：``local_asr``（max_workers=1，
  對齊主機 GPU worker 的 ``--pool=solo -c 1``，GPU 任務序列化）與 ``celery``
  （max_workers=N，對齊容器 worker 的 gevent 併發）
- registry 記錄任務狀態，提供 :meth:`LocalExecutor.revoke` /
  :meth:`LocalExecutor.is_alive`（取代 ``control.revoke`` 與 ``AsyncResult``）
- retry wrapper 對齊 Celery 的 ``autoretry_for`` + ``retry_backoff``
  （full-jitter，退避上限 ``backoff_max`` 秒）

執行中的任務無法被強制終止（執行緒不可 kill）；取消依賴既有的
cancellation 合作式旗標，與 Docker 模式的 solo pool 行為一致。
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Type

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# 狀態字串與 Celery AsyncResult.state 對齊，方便呼叫端沿用既有語意
PENDING = "PENDING"
STARTED = "STARTED"
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
REVOKED = "REVOKED"

_ACTIVE_STATES = (PENDING, STARTED)


@dataclass
class _TaskEntry:
    state: str = PENDING
    future: Optional[Future] = None


class LocalExecutor:
    def __init__(self, default_concurrency: int = 4):
        self._pools = {
            "local_asr": ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="local-asr"),
            "celery": ThreadPoolExecutor(
                max_workers=default_concurrency, thread_name_prefix="task"),
        }
        self._registry: dict[str, _TaskEntry] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        fn: Callable,
        args: tuple = (),
        *,
        task_id: str,
        queue: str = "celery",
        retry_on: Tuple[Type[BaseException], ...] = (),
        max_retries: int = 3,
        backoff_max: int = 60,
    ) -> str:
        """派發任務至指定佇列的執行緒池，回傳 task_id。"""
        pool = self._pools.get(queue) or self._pools["celery"]
        entry = _TaskEntry()
        with self._lock:
            self._registry[task_id] = entry

        def _run():
            with self._lock:
                if entry.state == REVOKED:
                    logger.info(f"任務 {task_id} 在啟動前已被 revoke，跳過執行")
                    return None
                entry.state = STARTED

            attempt = 0
            while True:
                try:
                    result = fn(*args)
                except retry_on as e:
                    if attempt >= max_retries:
                        entry.state = FAILURE
                        logger.error(
                            f"任務 {task_id} 重試 {max_retries} 次後仍失敗: {e}")
                        raise
                    if entry.state == REVOKED:
                        logger.info(f"任務 {task_id} 已被 revoke，停止重試")
                        return None
                    delay = random.uniform(0, min(2 ** attempt, backoff_max))
                    logger.warning(
                        f"任務 {task_id} 遇暫時性錯誤，{delay:.1f}s 後重試"
                        f"（第 {attempt + 1}/{max_retries} 次）: {e}")
                    time.sleep(delay)
                    attempt += 1
                except BaseException:
                    entry.state = FAILURE
                    raise
                else:
                    entry.state = SUCCESS
                    return result

        entry.future = pool.submit(_run)
        return task_id

    def revoke(self, task_id: str) -> None:
        """標記任務為 REVOKED；尚未啟動者直接取消，執行中者靠合作式旗標停止。"""
        with self._lock:
            entry = self._registry.get(task_id)
            if entry is None:
                return
            entry.state = REVOKED
            if entry.future is not None:
                entry.future.cancel()

    def is_alive(self, task_id: str) -> bool:
        """任務是否仍在等待或執行中。

        未知的 task_id 回 False：單機模式下行程重啟後任務必死，
        比 Celery PENDING 的模糊語意更明確。
        """
        entry = self._registry.get(task_id)
        return entry is not None and entry.state in _ACTIVE_STATES

    def state(self, task_id: str) -> Optional[str]:
        entry = self._registry.get(task_id)
        return entry.state if entry else None

    def shutdown(self) -> None:
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)


_executor: Optional[LocalExecutor] = None
_executor_lock = threading.Lock()


def get_executor() -> LocalExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                from app.core.config import get_settings
                _executor = LocalExecutor(
                    get_settings().standalone_worker_concurrency)
    return _executor


def shutdown_executor() -> None:
    """由 lifespan shutdown 呼叫；同時重置單例（測試亦賴此隔離）。"""
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown()
            _executor = None
