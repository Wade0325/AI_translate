"""Gemini 轉接器：Gemini 的知識都收在這裡，單檔與批次都只經由它呼叫 Gemini。

- 上傳：音檔送進 File API，等 Gemini 處理完才拿來轉錄。一上傳就登記，任務結束時
  （:meth:`GeminiProvider.release`）不論成功或失敗都刪掉遠端檔。
- 轉錄：標準或 Flex（https://ai.google.dev/gemini-api/docs/flex-inference）。Flex 遇到
  429／503 以指數退避重試，用完或遇到其他錯誤就退回標準。實際用到的處理模式以回應的
  header 為準，回報在 ``service_tier_used``，計價據此決定要不要打折。
- 批次：送出與輪詢；成功結束時把每個請求的回應換成轉錄結果。
- 錯誤：429／503 是暫時錯誤（:class:`~app.exceptions.GeminiTransientError`，外層會重試
  整個任務），其他是永久錯誤（:class:`~app.exceptions.GeminiPermanentError`）。

google-genai 用戶端與 sleep 可以從外面傳進來：測試用假的用戶端，也不必真的等。
用 API 金鑰建立用戶端在 :mod:`app.provider.google.gemini`，設定頁的連線測試也用它。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from google.genai import types

from app.core.config import get_settings
from app.exceptions import GeminiPermanentError, GeminiTransientError
from app.provider.base import (
    DEFAULT_QUEUE,
    BatchStatus,
    ModelCapabilities,
    ProgressAndCancel,
    TranscribeRequest,
)
from app.provider.google.gemini import GeminiClient
from app.services.transcription.models import TranscriptionTaskResult
from app.utils.audio import get_mime_type
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# 與前端 frontend/src/constants/modelConfig.js 的 Google 選項一致
MODELS = (
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
)

UPLOAD_POLL_SECONDS = 2
"""上傳之後多久查一次 Gemini 處理完了沒有。"""
FLEX_MAX_RETRIES = 3
FLEX_BASE_DELAY = 5
"""Flex 第一次重試前等幾秒，之後每次加倍。"""
FLEX_TIMEOUT_MS = 900_000
"""Flex 的請求逾時：15 分鐘，官方建議至少 10 分鐘。"""


def _capabilities() -> ModelCapabilities:
    return ModelCapabilities(
        single_pass_seconds=get_settings().long_audio_split_threshold_seconds,
        queue=DEFAULT_QUEUE,
        # 容器 worker 是 gevent pool，支援 terminate
        can_terminate=True,
        split_retry_on_failure=True,
        accepts_prompt=True,
        accepts_user_text=True,
        supports_batch=True,
        pricing="per_token",
        remove_silence=True,
    )


def _prompt_fingerprint(prompt: str) -> str:
    """提示詞的長度與 md5 前綴：log 裡不寫完整內容。"""
    digest = hashlib.md5(prompt.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"len={len(prompt)} md5={digest}"


def _is_retryable(err: Exception) -> bool:
    """429／503 之類的錯誤：稍後重試可能會好。"""
    code = getattr(err, "code", None)
    if code in (429, 503):
        return True
    status_code = getattr(err, "status_code", None)
    if status_code in (429, 503):
        return True
    message = str(err).lower()
    return ("429" in message or "503" in message
            or "resource_exhausted" in message
            or "service unavailable" in message
            or "unavailable" in message)


def _classify(err: Exception) -> Exception:
    """把 google-genai 的例外分成暫時與永久；呼叫端 ``raise _classify(e) from e``。"""
    if _is_retryable(err):
        return GeminiTransientError(str(err))
    return GeminiPermanentError(str(err))


def _thinking_config(model: str) -> types.ThinkingConfig:
    """依模型世代選擇思考設定（參考 Gemini 3.5 遷移指南）。"""
    if model.startswith("gemini-3"):
        # Gemini 3.x 用 thinking_level，不再建議 thinking_budget；
        # 轉錄屬分析型任務，low 在品質與延遲／成本間較平衡
        return types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    return types.ThinkingConfig(thinking_budget=128)


def _generation_config(model: str, service_tier: Optional[str]) -> types.GenerateContentConfig:
    """Flex 另外帶 service_tier 與延長的逾時。"""
    if service_tier == "flex":
        return types.GenerateContentConfig(
            thinking_config=_thinking_config(model),
            service_tier=types.ServiceTier.FLEX,
            http_options=types.HttpOptions(timeout=FLEX_TIMEOUT_MS),
        )
    return types.GenerateContentConfig(thinking_config=_thinking_config(model))


def _served_tier(response: Any) -> Optional[str]:
    """回應 header ``x-gemini-service-tier`` 寫的處理模式：flex、standard 或 priority。

    google-genai < 1.69.0 沒有 sdk_http_response，讀不到時回 None。
    """
    try:
        headers = getattr(getattr(response, "sdk_http_response", None), "headers", None)
        if headers is None or not hasattr(headers, "get"):
            return None
        tier = headers.get("x-gemini-service-tier") or headers.get("X-Gemini-Service-Tier")
        return str(tier).strip().lower() if tier else None
    except Exception as e:  # pragma: no cover - 防呆
        logger.debug(f"讀取 x-gemini-service-tier header 失敗: {e}")
        return None


def _tier_used(response: Any, requested: Optional[str], sent_tier: str) -> str:
    """實際用到的處理模式：以回應 header 為準，讀不到時照送出的請求判定。"""
    served = _served_tier(response)
    if not served:
        logger.info(
            "[TIER] 無法從回應讀取 x-gemini-service-tier header"
            f"（可能 google-genai SDK < 1.69.0），維持以請求端判定 tier_used={sent_tier}")
        return sent_tier
    if requested == "flex" and served == "flex":
        logger.info("[FLEX VERIFIED] Gemini 回應 header x-gemini-service-tier=flex"
                    "（已確認使用 Flex API，享 50% 折扣）")
    elif requested == "flex":
        logger.warning(f"[FLEX DOWNGRADED] 請求送出 service_tier=flex，但回應 header "
                       f"x-gemini-service-tier={served}（API 端降級或未套用 Flex）")
    else:
        logger.info(f"[TIER] Gemini 回應 header x-gemini-service-tier={served}")
    return served if served in ("flex", "standard", "priority") else sent_tier


def _usage(response: Any) -> Tuple[int, int, int]:
    """(輸入, 輸出, 總) token 數；某些回應（thinking 模式、部分阻擋、極短內容）的欄位可能是 None。"""
    usage = response.usage_metadata
    if usage is None:
        return 0, 0, 0
    return (usage.prompt_token_count or 0, usage.candidates_token_count or 0,
            usage.total_token_count or 0)


def _transcription_result(response: Any, tier: str) -> TranscriptionTaskResult:
    input_tokens, output_tokens, total_tokens = _usage(response)

    # 被安全機制阻擋的回應沒有 candidates：回報失敗，不能把空結果當成功
    if not response.candidates:
        error_text = "[[轉錄失敗：Gemini 回應被阻擋]]"
        try:
            error_text = f"[[轉錄失敗：請求被 Gemini 以 '{response.prompt_feedback.block_reason}' 原因阻擋。]]"
        except Exception:
            pass
        logger.warning(f"Gemini 沒有回傳任何內容: {error_text}")
        return TranscriptionTaskResult(
            success=False, text=error_text, input_tokens=input_tokens,
            output_tokens=output_tokens, total_tokens=total_tokens, service_tier_used=tier)

    thoughts_tokens = response.usage_metadata.thoughts_token_count if response.usage_metadata else None
    logger.info("Token 使用統計:")
    logger.info(f"  Input (Prompt) tokens: {input_tokens:>8,}")
    logger.info(f"  Output (Candidates) tokens: {output_tokens:>8,}")
    logger.info(f"  Thoughts tokens: {(thoughts_tokens if thoughts_tokens is not None else 'N/A'):>8}")
    logger.info(f"  Total tokens: {total_tokens:>8,}")
    return TranscriptionTaskResult.model_validate({
        "success": True,
        "text": response.text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "service_tier_used": tier,
    })


BATCH_DONE_STATES = frozenset({
    "JOB_STATE_SUCCEEDED",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",
    "JOB_STATE_EXPIRED",
})


def _batch_request(gemini_file: Any, prompt: str) -> Dict[str, Any]:
    return {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"file_data": {"file_uri": gemini_file.uri, "mime_type": gemini_file.mime_type}},
            ],
            "role": "user",
        }]
    }


def _batch_item_result(inline: Any) -> TranscriptionTaskResult:
    """批次裡一個請求的回應；失敗時 text 是要存進任務紀錄的錯誤訊息。"""
    response = inline.response
    if not response:
        return _batch_failure(f"轉錄失敗: {inline.error or '未知錯誤'}")
    if not response.candidates:
        text = "轉錄失敗：Gemini 回應被阻擋"
        try:
            text = f"轉錄失敗：請求被 Gemini 以 '{response.prompt_feedback.block_reason}' 原因阻擋"
        except Exception:
            pass
        return _batch_failure(text)
    input_tokens, output_tokens, total_tokens = _usage(response)
    return TranscriptionTaskResult(
        success=True, text=response.text or "", input_tokens=input_tokens,
        output_tokens=output_tokens, total_tokens=total_tokens, service_tier_used="batch")


def _batch_failure(text: str) -> TranscriptionTaskResult:
    return TranscriptionTaskResult(
        success=False, text=text, input_tokens=0, output_tokens=0, total_tokens=0,
        service_tier_used="batch")


class GeminiProvider:
    def __init__(
        self,
        model: str,
        api_key: str = "",
        *,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """client 沒給時用 api_key 建立 google-genai 用戶端；測試傳入假的用戶端與 sleep。"""
        self._client: Any = client if client is not None else GeminiClient(api_key).client
        if not self._client:
            raise ValueError("Failed to initialize Gemini Client. Check API key.")
        self._model = model
        self._sleep = sleep
        self._uploaded: List[Any] = []

    @staticmethod
    def capabilities() -> Dict[str, ModelCapabilities]:
        return {model: _capabilities() for model in MODELS}

    def transcribe(
        self, audio_path: Path, request: TranscribeRequest, progress: ProgressAndCancel,
    ) -> TranscriptionTaskResult:
        progress.report("上傳檔案至AI模型...")
        gemini_file = self.upload(audio_path)

        progress.report("AI模型處理中...")
        logger.info(f"正在使用 {request.model} 進行轉錄... "
                    f"(requested service_tier={request.service_tier or 'standard'})")
        logger.info(f"Prompt fingerprint: {_prompt_fingerprint(request.prompt)}")
        contents = [request.prompt, gemini_file]
        # 拿到回應的那次請求是以哪種處理模式送出的
        sent_tier = "flex"
        response = self._generate_flex(request.model, contents) if request.service_tier == "flex" else None
        if response is None:
            sent_tier = "standard"
            response = self._generate_standard(request.model, contents)
        return _transcription_result(response, _tier_used(response, request.service_tier, sent_tier))

    def _generate_flex(self, model: str, contents: List[Any]) -> Any:
        """Flex：429／503 以指數退避重試；用完或遇到其他錯誤回 None，由呼叫端退回標準。"""
        config = _generation_config(model, "flex")
        logger.info("[FLEX] 準備呼叫 Gemini Flex API (https://ai.google.dev/gemini-api/docs/flex-inference) "
                    f"model={model} config={config.model_dump(exclude_none=True)}")
        last_error: Optional[Exception] = None
        for attempt in range(FLEX_MAX_RETRIES):
            try:
                return self._client.models.generate_content(
                    model=model, contents=contents, config=config)
            except Exception as e:
                last_error = e
                if not _is_retryable(e) or attempt == FLEX_MAX_RETRIES - 1:
                    logger.warning(f"[FLEX] 呼叫失敗 (attempt {attempt + 1}/{FLEX_MAX_RETRIES}): {e}，停止重試")
                    break
                delay = FLEX_BASE_DELAY * (2 ** attempt)
                logger.warning(f"[FLEX] 呼叫失敗 (attempt {attempt + 1}/{FLEX_MAX_RETRIES}): {e}，"
                               f"{delay} 秒後重試...")
                self._sleep(delay)
        logger.warning(f"[FLEX] 推論耗盡，自動降級改以 Standard 層級重試: {last_error}")
        return None

    def _generate_standard(self, model: str, contents: List[Any]) -> Any:
        logger.info(f"[STANDARD] 呼叫 Gemini 標準同步 API model={model}")
        try:
            return self._client.models.generate_content(
                model=model, contents=contents, config=_generation_config(model, None))
        except Exception as e:
            raise _classify(e) from e

    def upload(self, audio_path: Path) -> Any:
        """上傳到 File API，等 Gemini 處理完才回傳；遠端檔在 :meth:`release` 刪除。"""
        if not audio_path.exists():
            raise ValueError("檔案不存在。")

        logger.info(f"正在上傳檔案至 Gemini API: {audio_path.name}")
        config = {"display_name": audio_path.stem}
        mime_type = get_mime_type(audio_path)
        if mime_type:
            config["mime_type"] = mime_type
            logger.info(f"使用 MIME 類型: {mime_type}")

        try:
            with open(audio_path, "rb") as f:
                gemini_file = self._client.files.upload(file=f, config=config)
        except Exception as e:
            raise _classify(e) from e
        # 一上傳就登記：之後處理失敗或查詢出錯，任務結束時也要刪掉它
        self._uploaded.append(gemini_file)

        polls = 0
        while gemini_file.state.name == "PROCESSING":
            polls += 1
            if polls % 10 == 1:
                logger.info("Gemini 檔案處理中...")
            self._sleep(UPLOAD_POLL_SECONDS)
            try:
                gemini_file = self._client.files.get(name=gemini_file.name)
            except Exception as e:
                raise _classify(e) from e

        if gemini_file.state.name == "FAILED":
            raise GeminiPermanentError(f"Gemini 檔案處理失敗: {gemini_file.state}")

        logger.info(f"檔案 '{audio_path.name}' 上傳並處理完畢")
        return gemini_file

    def submit_batch(self, requests: Sequence[Tuple[Any, str]], display_name: str) -> str:
        """用 Batch API 送出：費用是標準的一半，結果要輪詢。"""
        logger.info(f"建立批次: {len(requests)} 個請求, 模型: {self._model}")
        fingerprints = sorted({_prompt_fingerprint(prompt) for _, prompt in requests})
        logger.info(f"Batch prompt fingerprints ({len(fingerprints)} 種): {fingerprints}")
        try:
            batch_job = self._client.batches.create(
                model=self._model,
                src=[_batch_request(gemini_file, prompt) for gemini_file, prompt in requests],
                config={"display_name": display_name},
            )
        except Exception as e:
            raise _classify(e) from e
        logger.info(f"批次已建立: {batch_job.name}")
        return batch_job.name

    def poll_batch(self, name: str) -> BatchStatus:
        try:
            batch_job = self._client.batches.get(name=name)
        except Exception as e:
            raise _classify(e) from e
        state = batch_job.state.name if hasattr(batch_job.state, "name") else str(batch_job.state)
        if state not in BATCH_DONE_STATES:
            return BatchStatus(state=state, done=False)
        if state != "JOB_STATE_SUCCEEDED":
            return BatchStatus(state=state, done=True)
        inlined = batch_job.dest.inlined_responses if batch_job.dest else None
        return BatchStatus(state=state, done=True, succeeded=True,
                           results=tuple(_batch_item_result(r) for r in inlined or ()))

    def release(self) -> None:
        for gemini_file in self._uploaded:
            try:
                self._client.files.delete(name=gemini_file.name)
                logger.info(f"已從 Gemini API 清理檔案: {gemini_file.name}")
            except Exception as e:
                logger.warning(f"清理 Gemini 檔案 {gemini_file.name} 失敗: {e}")
        self._uploaded.clear()
