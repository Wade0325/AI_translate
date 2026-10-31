"""錯誤碼：任務失敗的原因分成固定的幾類，每一類一個錯誤碼（#24 門檻 4）。

例外在這裡、而且只在這裡對應成錯誤碼（:func:`describe`）：任務生命週期記下失敗、分段轉錄把供應商的
例外換成失敗的轉錄結果、批次讓一個檔案失敗、端點拒絕請求，都經過它。不是例外的失敗（供應商回應了，
卻沒有轉錄結果，例如 Gemini 擋下了內容）由寫失敗結果的地方在轉錄結果的 ``error_code`` 寫明。

錯誤碼和細節一起記進任務紀錄（``error_code``、``error_message``），也隨失敗的狀態廣播送給畫面；畫面
照錯誤碼顯示中文的原因與下一步（``frontend/src/constants/errorCodes.js``），細節放在下面，使用者回報
問題時連錯誤碼一起附上。細節是給人看的原始原因：供應商回報的錯誤、我們自己寫的固定句子；資料庫
出錯時是空的，原因只記在 log（SQL 原文與資料列不能上畫面）。

錯誤碼會存進資料庫並送到前端，不要改既有的值；``tests/unit/test_error_codes.py`` 確認前端每個錯誤碼
都有文案。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator, Optional, Self

from sqlalchemy.exc import SQLAlchemyError

from app.exceptions import (
    ApiKeyMissingError,
    AppError,
    GeminiFileRejectedError,
    GeminiPermanentError,
    TaskDatabaseError,
    TransientError,
)


class ErrorCode(StrEnum):
    # ── Gemini ──
    GEMINI_NO_API_KEY = "GEMINI_NO_API_KEY"
    """沒有設定 Gemini 的 API 金鑰。"""
    GEMINI_KEY_REJECTED = "GEMINI_KEY_REJECTED"
    """Gemini 不接受這把 API 金鑰：無效、被停用或權限不足（HTTP 401、403，或 400 寫明金鑰無效）。"""
    GEMINI_BILLING = "GEMINI_BILLING"
    """金鑰所屬專案的計費或使用資格有問題：402，或 400 FAILED_PRECONDITION 寫明計費、所在地區不能用
    免費方案。"""
    GEMINI_QUOTA = "GEMINI_QUOTA"
    """用量達到上限（429），重試用完了。"""
    GEMINI_UNAVAILABLE = "GEMINI_UNAVAILABLE"
    """Gemini 暫時無法服務（500、503、504），或其他暫時錯誤重試用完了。"""
    GEMINI_BLOCKED = "GEMINI_BLOCKED"
    """Gemini 的安全機制擋下了請求，或因為安全、版權的理由沒有寫出內容。"""
    GEMINI_REQUEST_FAILED = "GEMINI_REQUEST_FAILED"
    """Gemini 回報的其他錯誤。"""
    NETWORK = "NETWORK"
    """連不上供應商（網路斷線、DNS、逾時）。"""
    # ── 本機 ──
    LOCAL_NO_GPU = "LOCAL_NO_GPU"
    """這台電腦沒有可用的 NVIDIA 顯卡（或沒有裝 NVIDIA 驅動）。"""
    LOCAL_DRIVER_TOO_OLD = "LOCAL_DRIVER_TOO_OLD"
    """NVIDIA 顯卡驅動比 PyTorch 帶的 CUDA 舊。"""
    LOCAL_CUDA_INIT_FAILED = "LOCAL_CUDA_INIT_FAILED"
    """驅動在，CUDA 卻初始化失敗。"""
    LOCAL_TORCH_LOAD_FAILED = "LOCAL_TORCH_LOAD_FAILED"
    """PyTorch 載入失敗，或裝到不支援 CUDA 的版本。"""
    LOCAL_UNSUPPORTED_GPU = "LOCAL_UNSUPPORTED_GPU"
    """目前的 PyTorch 不支援這張顯卡。"""
    LOCAL_MISSING_WEIGHTS = "LOCAL_MISSING_WEIGHTS"
    """所選模型的模型權重還沒下載完。"""
    LOCAL_OUT_OF_MEMORY = "LOCAL_OUT_OF_MEMORY"
    """顯卡記憶體不夠（CUDA out of memory）。"""
    # ── 音檔與轉錄結果 ──
    AUDIO_UNREADABLE = "AUDIO_UNREADABLE"
    """讀不出、切不開音檔，或供應商處理不了上傳的音檔。"""
    NO_TRANSCRIPT = "NO_TRANSCRIPT"
    """供應商正常回應了，卻沒有轉錄出任何內容。"""
    # ── 送出任務 ──
    UNSUPPORTED_REQUEST = "UNSUPPORTED_REQUEST"
    """所選的模型不支援請求的設定（處理模式、提示詞、使用者文稿），或請求帶了明文金鑰。"""
    UPLOAD_MISSING = "UPLOAD_MISSING"
    """伺服器上找不到上傳的檔案（已經被清掉，或檔名不合法）。"""
    SUBMIT_FAILED = "SUBMIT_FAILED"
    """派送前出了非預期的錯誤，任務沒有送出；原因只記在 log。"""
    # ── 任務 ──
    INTERRUPTED = "INTERRUPTED"
    """應用程式在任務排隊或轉錄途中關閉、重新啟動了。"""
    DATABASE = "DATABASE"
    """讀寫資料庫時出錯；原因只記在 log。"""
    BATCH_FAILED = "BATCH_FAILED"
    """整個批次失敗，或批次沒有這個檔案的結果。"""
    INTERNAL = "INTERNAL"
    """其他非預期的錯誤。"""


@dataclass(frozen=True)
class Failure:
    """一個任務為什麼失敗：錯誤碼與細節。"""

    code: ErrorCode
    detail: str = ""
    """給人看的原始原因，見模組說明；沒有可以給人看的原因時是空的。"""

    def fields(self) -> dict:
        """任務紀錄、失敗的狀態廣播與端點回報沒有送出的訊息都帶的欄位：錯誤碼與細節（沒有細節時是
        None），兩邊同名。"""
        return {"error_code": self.code, "error_message": self.detail or None}


class TaskFailedError(AppError):
    """已經歸類好的失敗：帶著錯誤碼與細節，:func:`describe` 原樣採用。

    任務生命週期拿失敗的轉錄結果記下失敗時拋它；批次讓一個檔案失敗時也用它（見
    :mod:`app.tasks.batch_core`）。例外訊息就是細節。
    """

    def __init__(self, code: ErrorCode, detail: str = ""):
        super().__init__(detail)
        self.failure = Failure(code, _clean(detail))

    @classmethod
    def because(cls, step: str, error: BaseException) -> Self:
        """做 ``step`` 這一步時遇到 ``error``：錯誤碼照 ``error`` 歸類，細節寫明是哪一步。"""
        cause = describe(error)
        return cls(cause.code, f"{step}: {cause.detail}" if cause.detail else step)


MAX_DETAIL_CHARS = 500
"""細節最長幾個字：供應商的錯誤偶爾附上很長的內容，畫面與任務紀錄只留開頭。"""


def describe(error: BaseException) -> Failure:
    """把例外對應成錯誤碼與細節。

    沿著 ``raise … from`` 接起來的成因往裡找，認得的第一個說了算：例如 Gemini 轉接器把
    google-genai 的錯誤包成 :class:`~app.exceptions.GeminiTransientError`，錯誤碼看裡面的 HTTP
    狀態碼。都不認得時，照最外層的例外歸類。
    """
    for cause in _causes(error):
        failure = _known(cause)
        if failure is not None:
            return failure
    if isinstance(error, TransientError):
        return Failure(ErrorCode.GEMINI_UNAVAILABLE, _clean(error.reason or str(error)))
    if isinstance(error, GeminiPermanentError):
        return Failure(ErrorCode.GEMINI_REQUEST_FAILED, _clean(str(error)))
    return Failure(ErrorCode.INTERNAL, _clean(str(error)) or type(error).__name__)


def _causes(error: BaseException) -> Iterator[BaseException]:
    """``error`` 與它用 ``raise … from`` 接起來的成因，由外往裡。"""
    seen: set[int] = set()
    current: Optional[BaseException] = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def _known(error: BaseException) -> Optional[Failure]:
    """認得的例外的錯誤碼與細節；不認得時是 None。"""
    if isinstance(error, TaskFailedError):
        return error.failure
    if isinstance(error, (TaskDatabaseError, SQLAlchemyError)):
        # 資料庫例外帶著 SQL 原文與資料列：細節留空，原因只記在 log
        return Failure(ErrorCode.DATABASE)
    if isinstance(error, ApiKeyMissingError):
        return Failure(ErrorCode.GEMINI_NO_API_KEY, str(error))
    if isinstance(error, GeminiFileRejectedError):
        return Failure(ErrorCode.AUDIO_UNREADABLE, str(error))
    return (_gemini_api_error(error) or _network_error(error) or _out_of_memory(error)
            or _app_error(error))


def _gemini_api_error(error: BaseException) -> Optional[Failure]:
    """google-genai 回報的 API 錯誤，照 HTTP 狀態碼歸類（https://ai.google.dev/gemini-api/docs/api-errors
    與 https://ai.google.dev/gemini-api/docs/troubleshooting）。"""
    try:
        from google.genai import errors as genai_errors
    except ImportError:  # pragma: no cover - google-genai 是基本依賴
        return None
    if not isinstance(error, genai_errors.APIError):
        return None
    code, status, message = error.code, error.status or "", error.message or ""
    detail = _clean(f"{code} {status}: {message}" if message else f"{code} {status}")
    if code in (401, 403) or (code == 400 and _says_api_key_invalid(error)):
        return Failure(ErrorCode.GEMINI_KEY_REJECTED, detail)
    if code == 402 or (code == 400 and status == "FAILED_PRECONDITION" and _says_billing(message)):
        return Failure(ErrorCode.GEMINI_BILLING, detail)
    if code == 429:
        return Failure(ErrorCode.GEMINI_QUOTA, detail)
    if code in (500, 502, 503, 504):
        return Failure(ErrorCode.GEMINI_UNAVAILABLE, detail)
    return Failure(ErrorCode.GEMINI_REQUEST_FAILED, detail)


def _says_api_key_invalid(error) -> bool:
    """400 的內容寫明金鑰無效：訊息「API key not valid」或 ErrorInfo 的 reason 是 API_KEY_INVALID。"""
    return "api key" in (error.message or "").lower() or "API_KEY_INVALID" in str(error.details)


def _says_billing(message: str) -> bool:
    """FAILED_PRECONDITION 不全是計費：音檔還沒處理好（「File … is not in an ACTIVE state」）也是它。
    只有寫明計費（「Please enable billing」）或所在地區（「User location is not supported」）的才算。"""
    message = message.lower()
    return "billing" in message or "location" in message


def _network_error(error: BaseException) -> Optional[Failure]:
    """連不上供應商：httpx（google-genai 用它連線）的連線與逾時錯誤，或作業系統回報的連線錯誤。"""
    try:
        import httpx
        transport_errors: tuple[type[BaseException], ...] = (httpx.TransportError, ConnectionError)
    except ImportError:  # pragma: no cover - httpx 隨 google-genai 安裝
        transport_errors = (ConnectionError,)
    if isinstance(error, transport_errors):
        return Failure(ErrorCode.NETWORK, _clean(f"{type(error).__name__}: {error}"))
    return None


def _out_of_memory(error: BaseException) -> Optional[Failure]:
    """顯卡記憶體不夠：torch 的 ``torch.cuda.OutOfMemoryError``（舊版是訊息寫著 CUDA out of memory 的
    RuntimeError）。不 import torch：Docker 模式的 API 與 CI 都沒裝。"""
    if type(error).__name__ == "OutOfMemoryError" or "out of memory" in str(error).lower():
        return Failure(ErrorCode.LOCAL_OUT_OF_MEMORY, _clean(str(error)))
    return None


def _app_error(error: BaseException) -> Optional[Failure]:
    """其他模組定義、訊息寫給使用者看的例外；延遲 import，免得和那些模組互相 import。"""
    from app.provider.local.weights import LocalNotReady
    from app.provider.registry import UnsupportedModelError
    from app.runtime.run_mode import RunModeClosedError
    from app.services.api_keys import PlaintextApiKeyError
    from app.utils.paths import MissingUploadError, UnsafeUploadFilenameError

    if isinstance(error, LocalNotReady):
        code = _LOCAL_NOT_READY.get(error.reason)
        return Failure(code, str(error)) if code else None
    if isinstance(error, (UnsupportedModelError, PlaintextApiKeyError)):
        return Failure(ErrorCode.UNSUPPORTED_REQUEST, str(error))
    if isinstance(error, (MissingUploadError, UnsafeUploadFilenameError)):
        return Failure(ErrorCode.UPLOAD_MISSING, str(error))
    if isinstance(error, RunModeClosedError):
        return Failure(ErrorCode.INTERRUPTED, str(error))
    return None


_LOCAL_NOT_READY = {
    "no_gpu": ErrorCode.LOCAL_NO_GPU,
    "driver_too_old": ErrorCode.LOCAL_DRIVER_TOO_OLD,
    "cuda_init_failed": ErrorCode.LOCAL_CUDA_INIT_FAILED,
    "torch_load_failed": ErrorCode.LOCAL_TORCH_LOAD_FAILED,
    "unsupported_gpu": ErrorCode.LOCAL_UNSUPPORTED_GPU,
    "missing_weights": ErrorCode.LOCAL_MISSING_WEIGHTS,
}
"""本機還不能轉錄的原因（:class:`~app.provider.local.weights.LocalNotReady` 的 ``reason``）→ 錯誤碼。"""


def _clean(text: str) -> str:
    """細節：去掉頭尾空白與舊寫法的 ``[[…]]`` 外框，太長的只留開頭。"""
    text = text.strip().removeprefix("[[").removesuffix("]]").strip()
    return text if len(text) <= MAX_DETAIL_CHARS else text[:MAX_DETAIL_CHARS] + "…"
