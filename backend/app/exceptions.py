"""集中定義的自訂例外類別。

Celery autoretry_for 與上層錯誤處理依賴此分類來決定是否重試。
"""


class AppError(Exception):
    """所有自訂例外的基底。"""


class GeminiTransientError(AppError):
    """Gemini API 暫時性錯誤（429/503/網路抖動）。Celery 應自動重試。"""


class GeminiPermanentError(AppError):
    """Gemini API 永久性錯誤（API key 無效、prompt 被阻擋、quota 永久耗盡）。不應重試。"""


class VadError(AppError):
    """VAD 處理失敗。一般可繼續使用原始音檔，不重試。"""


class AudioConvertError(AppError):
    """音訊格式轉換失敗。"""
