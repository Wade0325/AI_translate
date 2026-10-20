"""集中定義的自訂例外類別。

Celery autoretry_for 與上層錯誤處理依賴此分類來決定是否重試。
"""


class AppError(Exception):
    """所有自訂例外的基底。"""


class TransientError(AppError):
    """供應商的暫時錯誤（429/503/網路抖動）：不是失敗，整個任務交給執行模式重試。

    任務生命週期不寫 FAILED、保留輸入音檔給重試；分段轉錄不把它當成這一段失敗。
    """


class GeminiTransientError(TransientError):
    """Gemini API 暫時性錯誤（429/503/網路抖動）。"""


class GeminiPermanentError(AppError):
    """Gemini API 永久性錯誤（API key 無效、prompt 被阻擋、quota 永久耗盡）。不應重試。"""


class TranscriptionCancelledError(AppError):
    """使用者取消轉錄任務。任務生命週期據此把任務記為 CANCELLED 而非 FAILED。"""

    def __init__(self, message: str = "使用者已取消任務", used=None):
        super().__init__(message)
        self.used = used
        """取消前已經向供應商轉錄完的段落的用量（``TranscriptionTaskResult``，只看 token 數與
        處理模式），沒有時是 None。供應商照樣收費，任務生命週期把它記在已取消的紀錄上。"""
