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
