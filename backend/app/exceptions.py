"""集中定義的自訂例外類別。

上層錯誤處理依賴此分類來決定是否重試。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.services.transcription.models import TranscriptionTaskResult


class AppError(Exception):
    """所有自訂例外的基底。"""


class TransientError(AppError):
    """供應商的暫時錯誤（429/503/網路抖動）：稍後再試可能就會好，不是這一段失敗。

    在出錯的那一步等一段時間（:meth:`wait_seconds`）再做一次，已經做完的不重做：單檔任務由分段轉錄
    重轉出錯的那一段（見 :mod:`app.services.chunked_transcription`），批次重做上傳、送出或查詢的那一次
    （見 :mod:`app.tasks.batch_core`）。執行模式不重試整個任務或批次。
    """

    def __init__(self, message: str = "", retry_after: Optional[float] = None,
                 reason: Optional[str] = None):
        super().__init__(message)
        self.retry_after = retry_after
        """供應商建議等幾秒再試（例如回應的 Retry-After）；沒有建議時是 None。"""
        self.reason = reason
        """給使用者看的簡短原因，例如「503 UNAVAILABLE」；沒有時用例外訊息。例外訊息照錄供應商的錯誤，
        可能長得不適合放在畫面上。"""

    def wait_seconds(self, retry: int) -> float:
        """第 ``retry`` 次重試（從 1 起算）之前等幾秒：供應商建議了等待秒數時照它，沒有時從起始等待
        （``TRANSIENT_ERROR_INITIAL_WAIT_SECONDS``）開始每次加倍；都不超過上限
        （``TRANSIENT_ERROR_MAX_WAIT_SECONDS``）。最多重試幾次是 ``TRANSIENT_ERROR_RETRIES``。"""
        settings = get_settings()
        suggested = self.retry_after
        if suggested is None:
            suggested = settings.transient_error_initial_wait_seconds * 2 ** (retry - 1)
        return max(0.0, min(suggested, settings.transient_error_max_wait_seconds))


class GeminiTransientError(TransientError):
    """Gemini API 暫時性錯誤（429/503/網路抖動）。"""


class GeminiPermanentError(AppError):
    """Gemini API 永久性錯誤（API key 無效、prompt 被阻擋、quota 永久耗盡）。不應重試。"""


class TaskDatabaseError(AppError):
    """讀寫資料庫時出錯，訊息只有資料庫例外的類型與資料庫回報的原因
    （:func:`~app.database.session.describe_db_error`）。

    資料庫例外記進 log、往上拋給執行模式之前，先由 :func:`~app.database.session.without_db_details`
    換成它：原本的例外帶著 SQL 原文與資料庫附上的資料列。最早只用在任務生命週期，現在批次、啟動
    清掃、HTTP 與 WebSocket 端點記 log 時也用它。
    """


class TranscriptionCancelledError(AppError):
    """使用者取消轉錄任務。任務生命週期據此把任務記為 CANCELLED 而非 FAILED。"""

    def __init__(self, message: str = "使用者已取消任務"):
        super().__init__(message)
        self.billed_usage: Optional[TranscriptionTaskResult] = None
        """取消前已經向供應商轉錄完的段落的用量（只帶 token 數與處理模式的
        ``TranscriptionTaskResult``），沒有時是 None。供應商照樣收費，任務生命週期把它記在
        已取消的紀錄上。"""
