"""集中定義的自訂例外類別。

Celery autoretry_for 與上層錯誤處理依賴此分類來決定是否重試。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.services.transcription.models import TranscriptionTaskResult


class AppError(Exception):
    """所有自訂例外的基底。"""


class TransientError(AppError):
    """供應商的暫時錯誤（429/503/網路抖動）：稍後再試可能就會好，不是這一段失敗。

    單檔任務由分段轉錄等一段時間再轉出錯的那一段（見 :mod:`app.services.chunked_transcription`）；
    批次交給執行模式重試整個批次。
    """

    def __init__(self, message: str = "", retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after
        """供應商建議等幾秒再試（例如回應的 Retry-After）；沒有建議時是 None。"""


class GeminiTransientError(TransientError):
    """Gemini API 暫時性錯誤（429/503/網路抖動）。"""


class GeminiPermanentError(AppError):
    """Gemini API 永久性錯誤（API key 無效、prompt 被阻擋、quota 永久耗盡）。不應重試。"""


class TaskDatabaseError(AppError):
    """任務讀寫資料庫時出錯，訊息只有資料庫例外的類型與資料庫回報的原因
    （:func:`~app.database.session.describe_db_error`）。

    任務生命週期把資料庫例外換成它，再記進 log、往上拋給執行模式：原本的例外帶著 SQL 原文與
    資料庫附上的資料列。
    """


class TranscriptionCancelledError(AppError):
    """使用者取消轉錄任務。任務生命週期據此把任務記為 CANCELLED 而非 FAILED。"""

    def __init__(self, message: str = "使用者已取消任務"):
        super().__init__(message)
        self.billed_usage: Optional[TranscriptionTaskResult] = None
        """取消前已經向供應商轉錄完的段落的用量（只帶 token 數與處理模式的
        ``TranscriptionTaskResult``），沒有時是 None。供應商照樣收費，任務生命週期把它記在
        已取消的紀錄上。"""
