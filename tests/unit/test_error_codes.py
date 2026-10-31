"""錯誤碼：例外對應成哪個錯誤碼與細節，以及前端每個錯誤碼都有中文文案（#24 門檻 4）。

只從 :func:`app.core.error_codes.describe` 的輸出觀察。google-genai 的錯誤用 tests/support/fake_genai.py
造，和 Gemini 真的回報的錯誤同一個類別與內容格式。
"""
import re
from pathlib import Path

import httpx
import pytest
from google.genai import errors as genai_errors
from sqlalchemy.exc import OperationalError

from app.core.error_codes import MAX_DETAIL_CHARS, ErrorCode, Failure, TaskFailedError, describe
from app.exceptions import (
    ApiKeyMissingError,
    GeminiFileRejectedError,
    GeminiPermanentError,
    GeminiTransientError,
    TaskDatabaseError,
)
from app.provider.local.weights import LocalNotReady
from app.provider.registry import UnsupportedInputError, UnsupportedModelError
from app.runtime.run_mode import RunModeClosedError
from app.services.api_keys import PlaintextApiKeyError
from app.utils.paths import MissingUploadError, UnsafeUploadFilenameError
from tests.support.fake_genai import invalid_argument, rate_limited, unavailable

FRONTEND_CONSTANTS = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "constants" / "errorCodes.js"
)


def _genai_error(code: int, status: str, message: str, details=None) -> genai_errors.APIError:
    """Gemini 回報的錯誤，內容格式見 https://ai.google.dev/gemini-api/docs/api-errors 。"""
    error = {"code": code, "message": message, "status": status}
    if details is not None:
        error["details"] = details
    cls = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    return cls(code, {"error": error}, None)


def _wrapped(cause: BaseException, outer: BaseException) -> BaseException:
    """``raise outer from cause``，和 Gemini 轉接器包裝 google-genai 錯誤的方式一樣。"""
    try:
        raise outer from cause
    except BaseException as e:  # noqa: BLE001 - 只是為了接上 __cause__
        return e


# ── Gemini 回報的錯誤 ──


@pytest.mark.parametrize("error, code", [
    (_genai_error(401, "UNAUTHENTICATED", "Request had invalid authentication credentials."),
     ErrorCode.GEMINI_KEY_REJECTED),
    (_genai_error(403, "PERMISSION_DENIED", "Your API key was reported as leaked."),
     ErrorCode.GEMINI_KEY_REJECTED),
    (_genai_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."),
     ErrorCode.GEMINI_KEY_REJECTED),
    (_genai_error(400, "INVALID_ARGUMENT", "Bad request.",
                  details=[{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "API_KEY_INVALID"}]),
     ErrorCode.GEMINI_KEY_REJECTED),
    (_genai_error(402, "PAYMENT_REQUIRED", "Billing account required."),
     ErrorCode.GEMINI_BILLING),
    (_genai_error(400, "FAILED_PRECONDITION",
                  "Gemini API free tier is not available in your country. Please enable billing "
                  "on your project in Google AI Studio."),
     ErrorCode.GEMINI_BILLING),
    (_genai_error(400, "FAILED_PRECONDITION", "User location is not supported for the API use."),
     ErrorCode.GEMINI_BILLING),
    (rate_limited(), ErrorCode.GEMINI_QUOTA),
    (unavailable(), ErrorCode.GEMINI_UNAVAILABLE),
    (_genai_error(500, "INTERNAL", "An internal error has occurred."), ErrorCode.GEMINI_UNAVAILABLE),
    (_genai_error(504, "DEADLINE_EXCEEDED", "Deadline exceeded."), ErrorCode.GEMINI_UNAVAILABLE),
    (invalid_argument("Request contains an invalid argument."), ErrorCode.GEMINI_REQUEST_FAILED),
    (_genai_error(404, "NOT_FOUND", "models/gemini-x is not found."),
     ErrorCode.GEMINI_REQUEST_FAILED),
])
def test_gemini_api_errors_by_http_status(error, code):
    assert describe(error).code == code


def test_failed_precondition_without_billing_is_not_a_billing_problem():
    # 音檔還沒處理好時 Gemini 也回 FAILED_PRECONDITION，說成計費問題會誤導
    error = _genai_error(400, "FAILED_PRECONDITION", "The File files/abc is not in an ACTIVE state.")
    assert describe(error).code == ErrorCode.GEMINI_REQUEST_FAILED


def test_gemini_detail_is_the_status_and_message():
    error = _genai_error(403, "PERMISSION_DENIED", "Your API key was reported as leaked.")
    assert describe(error).detail == "403 PERMISSION_DENIED: Your API key was reported as leaked."


@pytest.mark.parametrize("cause, outer, code", [
    (rate_limited(), GeminiTransientError("429 …", reason="429 RESOURCE_EXHAUSTED"),
     ErrorCode.GEMINI_QUOTA),
    (unavailable(), GeminiTransientError("503 …", reason="503 UNAVAILABLE"),
     ErrorCode.GEMINI_UNAVAILABLE),
    (_genai_error(403, "PERMISSION_DENIED", "Permission denied."), GeminiPermanentError("403 …"),
     ErrorCode.GEMINI_KEY_REJECTED),
])
def test_wrapped_gemini_errors_are_classified_by_the_cause(cause, outer, code):
    # Gemini 轉接器 raise _classify(e) from e：錯誤碼看裡面 google-genai 的狀態碼
    assert describe(_wrapped(cause, outer)).code == code


def test_transient_error_without_a_known_cause_uses_its_reason():
    failure = describe(GeminiTransientError("很長的錯誤內容", reason="503 UNAVAILABLE"))
    assert failure == Failure(ErrorCode.GEMINI_UNAVAILABLE, "503 UNAVAILABLE")


def test_permanent_gemini_error_without_a_known_cause():
    failure = describe(GeminiPermanentError("Gemini 回報這個請求失敗"))
    assert failure == Failure(ErrorCode.GEMINI_REQUEST_FAILED, "Gemini 回報這個請求失敗")


def test_rejected_upload_is_an_audio_problem_not_a_gemini_problem():
    error = GeminiFileRejectedError("Gemini 處理不了上傳的音檔（檔案狀態是 FAILED）")
    assert describe(error) == Failure(
        ErrorCode.AUDIO_UNREADABLE, "Gemini 處理不了上傳的音檔（檔案狀態是 FAILED）")


def test_missing_api_key():
    assert describe(ApiKeyMissingError("沒有設定 Gemini 的 API 金鑰")).code == ErrorCode.GEMINI_NO_API_KEY


# ── 網路、本機 ──


@pytest.mark.parametrize("error", [
    httpx.ConnectError("[Errno -3] Temporary failure in name resolution"),
    httpx.ReadTimeout("The read operation timed out"),
    ConnectionResetError("Connection reset by peer"),
])
def test_network_errors(error):
    failure = describe(_wrapped(error, GeminiTransientError(str(error))))
    assert failure.code == ErrorCode.NETWORK
    assert failure.detail.startswith(type(error).__name__ + ": ")


@pytest.mark.parametrize("reason, code", [
    ("no_gpu", ErrorCode.LOCAL_NO_GPU),
    ("unsupported_gpu", ErrorCode.LOCAL_UNSUPPORTED_GPU),
    ("missing_weights", ErrorCode.LOCAL_MISSING_WEIGHTS),
])
def test_local_not_ready(reason, code):
    assert describe(LocalNotReady(reason, "本機還不能轉錄")) == Failure(code, "本機還不能轉錄")


def test_gpu_out_of_memory():
    class OutOfMemoryError(RuntimeError):  # 和 torch.cuda.OutOfMemoryError 同名
        pass

    assert describe(OutOfMemoryError("CUDA out of memory.")).code == ErrorCode.LOCAL_OUT_OF_MEMORY
    # 舊版 torch：訊息寫著 out of memory 的 RuntimeError
    old = RuntimeError("CUDA error: out of memory")
    assert describe(old).code == ErrorCode.LOCAL_OUT_OF_MEMORY


# ── 送出任務、任務 ──


@pytest.mark.parametrize("error, code", [
    (UnsupportedModelError("所選的模型不支援批次"), ErrorCode.UNSUPPORTED_REQUEST),
    (UnsupportedInputError("所選的模型不吃提示詞"), ErrorCode.UNSUPPORTED_REQUEST),
    (PlaintextApiKeyError(), ErrorCode.UNSUPPORTED_REQUEST),
    (MissingUploadError("a.mp3"), ErrorCode.UPLOAD_MISSING),
    (UnsafeUploadFilenameError("../a.mp3"), ErrorCode.UPLOAD_MISSING),
    (RunModeClosedError("執行模式已經關閉"), ErrorCode.INTERRUPTED),
])
def test_refused_requests(error, code):
    failure = describe(error)
    assert failure.code == code
    assert failure.detail == str(error)


@pytest.mark.parametrize("error", [
    TaskDatabaseError("OperationalError: no such table: transcription_logs"),
    OperationalError("INSERT INTO transcription_logs VALUES (?)", ("祕密的檔名.mp3",), Exception("locked")),
])
def test_database_errors_have_no_detail(error):
    # SQL 原文與資料列不能上畫面：細節留空，原因只記在 log
    assert describe(error) == Failure(ErrorCode.DATABASE)


def test_database_error_inside_another_error_still_has_no_detail():
    wrapped = _wrapped(OperationalError("SELECT 1", ("祕密",), Exception("locked")), RuntimeError("寫不進去"))
    assert describe(wrapped) == Failure(ErrorCode.DATABASE)


def test_task_failed_error_keeps_its_code_and_detail():
    assert describe(TaskFailedError(ErrorCode.NO_TRANSCRIPT, "沒有轉錄出任何內容")) == Failure(
        ErrorCode.NO_TRANSCRIPT, "沒有轉錄出任何內容")


def test_because_names_the_step_and_keeps_the_cause_code():
    error = TaskFailedError.because("檔案上傳失敗", _wrapped(rate_limited(), GeminiTransientError("…")))
    assert error.failure == Failure(
        ErrorCode.GEMINI_QUOTA, "檔案上傳失敗: 429 RESOURCE_EXHAUSTED: Resource has been exhausted.")


def test_because_with_a_database_error_names_only_the_step():
    error = TaskFailedError.because("送出批次失敗", TaskDatabaseError("OperationalError: locked"))
    assert error.failure == Failure(ErrorCode.DATABASE, "送出批次失敗")


def test_unknown_errors_are_internal():
    assert describe(KeyError("segments")) == Failure(ErrorCode.INTERNAL, "'segments'")
    # 沒有訊息時至少寫出例外的類型
    assert describe(RuntimeError()) == Failure(ErrorCode.INTERNAL, "RuntimeError")


def test_detail_is_trimmed():
    failure = describe(RuntimeError("[[ " + "長" * (MAX_DETAIL_CHARS + 50) + " ]]"))
    assert failure.detail == "長" * MAX_DETAIL_CHARS + "…"
    assert describe(RuntimeError("  [[分段 1 失敗]]  ")).detail == "分段 1 失敗"


# ── 錯誤碼本身 ──


def test_error_code_values_are_unchanged():
    # 存在資料庫裡、送到前端的字串，改了舊紀錄就對不上前端的文案
    assert {c.value for c in ErrorCode} == {
        "GEMINI_NO_API_KEY", "GEMINI_KEY_REJECTED", "GEMINI_BILLING", "GEMINI_QUOTA",
        "GEMINI_UNAVAILABLE", "GEMINI_BLOCKED", "GEMINI_REQUEST_FAILED", "NETWORK",
        "LOCAL_NO_GPU", "LOCAL_UNSUPPORTED_GPU", "LOCAL_MISSING_WEIGHTS", "LOCAL_OUT_OF_MEMORY",
        "AUDIO_UNREADABLE", "NO_TRANSCRIPT",
        "UNSUPPORTED_REQUEST", "UPLOAD_MISSING", "SUBMIT_FAILED",
        "INTERRUPTED", "DATABASE", "BATCH_FAILED", "INTERNAL",
    }
    assert all(c.name == c.value for c in ErrorCode)


def _frontend_error_codes(source: str) -> set[str]:
    block = re.search(r"export const ERROR_CODES = Object\.freeze\(\{(.*?)\n\}\);", source, re.S)
    assert block, "errorCodes.js 找不到 ERROR_CODES 常數"
    return set(re.findall(r"^  (\w+): \{", block.group(1), re.M))


def test_every_error_code_has_frontend_copy():
    # 後端映像的 build context 只有 backend/，兩邊各自宣告一份，由這個測試對齊
    frontend = _frontend_error_codes(FRONTEND_CONSTANTS.read_text(encoding="utf-8"))
    assert {c.value for c in ErrorCode} <= frontend
