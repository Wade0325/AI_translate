"""免安裝模式的行程內任務執行器（取代 Celery worker）。

- 兩個執行緒池對齊 Docker 部署的 worker 配置：``local_asr``（max_workers=1，
  對齊主機 GPU worker 的 ``--pool=solo -c 1``，GPU 任務序列化）與 ``celery``
  （max_workers=N，對齊容器 worker 的 gevent 併發）
- registry 記錄任務狀態，提供 :meth:`LocalExecutor.revoke` /
  :meth:`LocalExecutor.is_alive`（取代 ``control.revoke`` 與 ``AsyncResult``）

不重試任務，和 Docker 模式的 Celery 任務一樣：暫時錯誤由任務自己重做出錯的那一步。

撤銷之後不會再執行的任務（還沒開始的），改呼叫派送時給的 ``on_abandoned`` 收尾，對齊
Celery 丟掉被撤銷的任務訊息。執行中的任務無法被強制終止（執行緒不可 kill），照常跑完，
由任務自己看取消旗標合作式停止、收尾，與 Docker 模式的 solo pool 行為一致。
由 :class:`app.runtime.in_process.InProcessRunMode` 持有與關閉。
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# 狀態字串與 Celery AsyncResult.state 對齊，方便呼叫端沿用既有語意
PENDING = "PENDING"
STARTED = "STARTED"
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
REVOKED = "REVOKED"

_ACTIVE_STATES = (PENDING, STARTED)

Abandoned = Callable[[bool], None]
"""任務不會再執行時呼叫一次；參數是「被撤銷」（False 代表關閉時還在排隊）。"""


@dataclass
class _TaskEntry:
    state: str = PENDING
    future: Optional[Future] = None
    on_abandoned: Optional[Abandoned] = None


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
        on_abandoned: Optional[Abandoned] = None,
    ) -> str:
        """派發任務至指定佇列的執行緒池，回傳 task_id。

        任務撤銷之後不會再執行（還沒開始）、或關閉時還在排隊時，改呼叫 ``on_abandoned``。
        """
        pool = self._pools.get(queue) or self._pools["celery"]
        entry = _TaskEntry(on_abandoned=on_abandoned)
        with self._lock:
            self._registry[task_id] = entry

        def _run():
            with self._lock:
                # 撤銷時 future 已經交給執行緒、取消不了：照常執行，由任務自己看取消旗標停下
                entry.state = STARTED
            try:
                result = fn(*args)
            except BaseException:
                entry.state = FAILURE
                raise
            entry.state = SUCCESS
            return result

        entry.future = pool.submit(_run)
        return task_id

    def revoke(self, task_id: str) -> None:
        """撤銷任務：還沒開始的不再執行，呼叫它的 ``on_abandoned``。

        已經開始的照常跑完（執行緒不可 kill，靠合作式旗標停止），跑完之前都還算存活。
        """
        with self._lock:
            entry = self._registry.get(task_id)
            if entry is None or entry.state != PENDING:
                return
            entry.state = REVOKED
            abandoned = entry.future is not None and entry.future.cancel()
        if abandoned:
            self._abandon(task_id, entry, revoked=True)

    def is_alive(self, task_id: str) -> bool:
        """任務是否仍在等待或執行中。

        未知的 task_id 回 False：免安裝模式下行程重啟後任務必死，
        比 Celery PENDING 的模糊語意更明確。
        """
        entry = self._registry.get(task_id)
        return entry is not None and entry.state in _ACTIVE_STATES

    def state(self, task_id: str) -> Optional[str]:
        entry = self._registry.get(task_id)
        return entry.state if entry else None

    def shutdown(self, wait: bool = False) -> None:
        """關閉執行緒池；還在排隊的任務不再執行，呼叫它們的 ``on_abandoned``。

        ``wait=True`` 等執行中的任務跑完。
        """
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            abandoned = [(task_id, entry) for task_id, entry in self._registry.items()
                         if entry.state == PENDING and entry.future is not None
                         and entry.future.cancelled()]
            for _, entry in abandoned:
                entry.state = REVOKED
        for task_id, entry in abandoned:
            self._abandon(task_id, entry, revoked=False)
        if wait:
            for pool in self._pools.values():
                pool.shutdown(wait=True)

    @staticmethod
    def _abandon(task_id: str, entry: _TaskEntry, *, revoked: bool) -> None:
        if entry.on_abandoned is None:
            return
        try:
            entry.on_abandoned(revoked)
        except Exception as e:
            logger.error(f"任務 {task_id} 沒有開始，收尾時失敗: {e}")
