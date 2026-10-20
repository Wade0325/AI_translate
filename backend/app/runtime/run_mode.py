"""執行模式模組：API 與任務只依賴這裡的介面。

免安裝模式與 Docker 模式的差異（派送、撤銷、存活查詢、狀態廣播與訂閱、
取消旗標、任務登記）都藏在兩個轉接器後面：

- :class:`app.runtime.in_process.InProcessRunMode`：執行緒池、行程內 bus、記憶體旗標
- :class:`app.runtime.celery_redis.CeleryRedisRunMode`：Celery 派送、Redis pub/sub 與旗標

轉接器在第一次 :func:`get` 時依執行模式選一次（FastAPI 在 lifespan 啟動時、
Celery worker 在第一個任務時），import 本模組不做任何選擇。測試直接建立轉接器，
用 :func:`use` 換上，不必 reload 模組。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, AsyncIterator, Optional, Protocol

from app.core.task_status import TaskStatus
from app.utils.logger import setup_logger

if TYPE_CHECKING:
    from app.core.config import Settings

logger = setup_logger(__name__)

TRANSIENT_RETRIES = 3
"""單檔任務遇到暫時錯誤時，兩個轉接器都最多再重試幾次（不含第一次執行）。"""


class RunMode(Protocol):
    # ── 派送與控制 ────────────────────────────────────────────────
    def submit_transcription(self, task_params_dict: dict, queue: str) -> str:
        """派發單檔轉錄任務，回傳 task_id（同時是 TranscriptionLog 主鍵）。"""

    def submit_batch(self, task_params_dict: dict) -> str:
        """派發批次轉錄任務，回傳 task_id。"""

    def submit_recover(self, batch_id: str, api_key: str) -> str:
        """派發批次結果恢復任務（不重試），回傳 task_id。"""

    def revoke(self, task_id: str, terminate: bool = False) -> None:
        """撤銷任務：佇列中的不再啟動；執行中的靠取消旗標合作式停止。

        ``terminate`` 只有 Celery 的 gevent pool 支援，其餘轉接器忽略。
        """

    def is_alive(self, task_id: str) -> Optional[bool]:
        """True=等待或執行中, False=已結束/已死, None=無法判斷。"""

    # ── 狀態廣播 ──────────────────────────────────────────────────
    def publish(self, message: dict) -> None:
        """從任意執行緒或行程廣播一則狀態訊息。

        訊息以 JSON 序列化（``default=str``），訂閱端收到的是 round-trip 後的 dict。
        """

    def subscribe(self) -> AsyncIterator[dict]:
        """在 event loop 內訂閱狀態訊息；訂閱之後廣播的訊息依序送達，直到被取消。"""

    # ── 取消旗標與任務登記（以 file_uid 為鍵）────────────────────
    def request_cancel(self, file_uid: str) -> None: ...

    def is_cancel_requested(self, file_uid: str) -> bool: ...

    def clear_cancel(self, file_uid: str) -> None: ...

    def register_task(self, file_uid: str, task_id: str) -> None:
        """記錄這個檔案最近一次派發的 task_id；再派發時覆蓋。"""

    def registered_task(self, file_uid: str) -> Optional[str]: ...

    # ── 生命週期 ──────────────────────────────────────────────────
    def close(self) -> None: ...


def select(settings: Optional["Settings"] = None) -> RunMode:
    """依執行模式建立轉接器；不給 settings 時用目前的設定。"""
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings()

    if settings.is_standalone:
        from app.runtime.in_process import InProcessRunMode
        return InProcessRunMode(settings.standalone_worker_concurrency)

    from app.runtime.celery_redis import CeleryRedisRunMode
    return CeleryRedisRunMode.from_url(settings.redis_url)


_current: Optional[RunMode] = None
_lock = threading.Lock()


def get() -> RunMode:
    """目前的轉接器；第一次呼叫時依執行模式選一次。"""
    global _current
    if _current is None:
        with _lock:
            if _current is None:
                _current = select()
    return _current


def use(mode: Optional[RunMode]) -> Optional[RunMode]:
    """換上指定的轉接器（None 代表下次 get 時重新選），回傳原本的。"""
    global _current
    with _lock:
        previous, _current = _current, mode
    return previous


def close() -> None:
    """由 lifespan shutdown 呼叫：關閉並卸下目前的轉接器。"""
    mode = use(None)
    if mode is not None:
        mode.close()


def publish_status(
    client_id: str,
    task_uuid: str,
    status_text: str,
    status_code: TaskStatus = TaskStatus.PROCESSING,
    *,
    file_uid: Optional[str] = None,
    result_data: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> None:
    """組出狀態訊息並廣播至前端；廣播失敗只記 log，不讓任務因此失敗。

    Args:
        client_id: WebSocket 對應的 client_id（單檔轉錄為 file_uid，批次為 batch_id）。
        task_uuid: 任務唯一識別碼。
        status_text: 顯示給使用者的訊息。
        status_code: 機器可讀的狀態碼，例如 PROCESSING/COMPLETED/FAILED/BATCH_COMPLETED。
        file_uid: 批次中，單一檔案的識別碼。
        result_data: 任務完成時的結果 payload。
        extra: 其他需要併入訊息的欄位（例如 batch_id）。
    """
    message = {
        "client_id": client_id,
        "task_uuid": task_uuid,
        "status_code": status_code,
        "status_text": status_text,
    }
    if file_uid:
        message["file_uid"] = file_uid
    if result_data:
        message["result"] = result_data
    if extra:
        message.update(extra)

    try:
        get().publish(message)
    except Exception as e:
        logger.error(f"發布狀態更新時失敗: {e}")
