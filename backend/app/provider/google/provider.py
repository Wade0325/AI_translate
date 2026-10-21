"""Gemini 轉接器：Gemini 的知識都收在這裡，單檔與批次都只經由它呼叫 Gemini。

- 上傳：音檔送進 File API，等 Gemini 處理完才拿來轉錄。一上傳就登記，任務結束時
  （:meth:`GeminiProvider.release`）不論成功或失敗都刪掉遠端檔。
- 轉錄：標準或 Flex（https://ai.google.dev/gemini-api/docs/flex-inference）。Flex 遇到
  429／503 以指數退避重試，用完或遇到其他錯誤就退回標準。實際用到的處理模式以回應的
  header 為準，回報在 ``service_tier_used``，計價據此決定要不要打折。
- LRC 解析：Gemini 寫的 LRC 在這裡解析一次就變成轉錄結果（片段，規則見 :func:`_segments_from_lrc`），
  之後的流程不再碰 LRC 文字。
- 批次：送出與輪詢；成功結束時把每個請求的回應換成轉錄結果。批次暫時還不解析，結果帶的是
  Gemini 寫的 LRC 文字（#115 改）。
- 取消：上傳前、等 Gemini 處理上傳檔的每次輪詢、每次送出生成（含 Flex 的每次重試）之前，都經
  進度與取消物件查一次；使用者取消時拋 :class:`~app.exceptions.TranscriptionCancelledError`，
  音檔不再往外送、也不再送出要收費的請求。已經上傳的遠端檔照樣在 :meth:`GeminiProvider.release`
  刪掉。已經送出的生成不中斷，回應照樣回報：Google 照樣收費，任務生命週期把用量記在已取消的紀錄上。
- 錯誤：429／503 是暫時錯誤（:class:`~app.exceptions.GeminiTransientError`，外層會重試
  整個任務），其他是永久錯誤（:class:`~app.exceptions.GeminiPermanentError`）。

google-genai 用戶端與 sleep 可以從外面傳進來：測試用假的用戶端，也不必真的等。
用 API 金鑰建立用戶端在 :mod:`app.provider.google.gemini`，設定頁的連線測試也用它。
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
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
    ProviderInfo,
    TranscribeRequest,
)
from app.provider.google.gemini import GeminiClient
from app.services.transcription.models import TranscriptionTaskResult
from app.utils.audio import get_mime_type
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# 畫面列出的模型與順序（GET /providers），第一個是預設
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

_UNCANCELLABLE = ProgressAndCancel(report=lambda text: None, cancel_requested=lambda: False)
"""批次的上傳：整批一起送出，沒有單一任務的取消。"""


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


def _transcription_result(
    response: Any, tier: str, speaker_ids: _SpeakerIds,
) -> TranscriptionTaskResult:
    """``speaker_ids`` 是這個任務的說話者代號 → 說話者編號，見 :class:`_SpeakerIds`。"""
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

    segments = _segments_from_lrc(response.text or "", speaker_ids)
    stopped = _abnormal_finish(response)
    if not segments and stopped:
        # 沒有內容又不是正常結束（例如 SAFETY、RECITATION）：不是那段沒人說話，當成功的話
        # 那一段會默默不見
        error_text = f"[[轉錄失敗：Gemini 沒有寫出任何內容就停止（{stopped}）]]"
        logger.warning(error_text)
        return TranscriptionTaskResult(
            success=False, text=error_text, input_tokens=input_tokens,
            output_tokens=output_tokens, total_tokens=total_tokens, service_tier_used=tier)
    # 正常結束卻沒有任何帶時間戳、有文字的行（例如這一段沒人說話）：算成功、沒有片段，不必切段
    # 重試；text 寫為什麼沒有，整個任務合併完都沒有片段時，任務用它回報失敗
    reason = "" if segments else "[[Gemini 的回應沒有任何帶時間戳的文字]]"
    if reason:
        logger.warning("Gemini 的回應沒有任何帶時間戳的文字，這一段沒有片段")
    return TranscriptionTaskResult(
        success=True, text=reason, input_tokens=input_tokens, output_tokens=output_tokens,
        total_tokens=total_tokens, service_tier_used=tier, segments=segments)


_NORMAL_FINISH = frozenset({"STOP", "FINISH_REASON_UNSPECIFIED"})


def _abnormal_finish(response: Any) -> Optional[str]:
    """回應不是正常結束時，停止的原因（例如 SAFETY）；正常結束或沒寫時是 None。"""
    reason = getattr(response.candidates[0], "finish_reason", None)
    if reason is None:
        return None
    name = getattr(reason, "name", None) or str(reason)
    return None if name in _NORMAL_FINISH else name


_LIST_MARKER_RE = re.compile(r"(?:[-+•・]|\*(?!\*))\s*")
_TIMESTAMP_RE = re.compile(r"\[(?:(\d+):)?(\d+):(\d{2}(?:\.\d+)?)\]\s*")
_BOLD = r"(?:\*\*|__)?"
# 字母代號前面要有空白，「Speakers:」才不會被當成說話者「S」
_SPEAKER_CODE_RE = re.compile(
    rf"{_BOLD}\s*speaker(?:\s*([0-9０-９]+)|\s+([a-zａ-ｚ]))\s*{_BOLD}\s*[:：]\s*{_BOLD}\s*",
    re.IGNORECASE)


def _normalized_code(code: str) -> str:
    """說話者代號正規化：全形轉半形、不分大小寫、數字去掉前導零（「Speaker 01」就是「Speaker 1」）。"""
    key = unicodedata.normalize("NFKC", code).upper()
    return str(int(key)) if key.isdigit() else key


class _SpeakerIds:
    """Gemini 寫的說話者代號（「Speaker 1:」「Speaker A:」）→ 說話者編號，一個任務一份。

    依代號在這個任務第一次送進來的順序編成 S0、S1……，同一個代號一律同一個編號，分段轉錄的
    各段也一樣；切段重試時，被放棄的那次轉錄裡出現過的代號也算進順序。各段是 Gemini 分開標的，
    同一個代號不保證是同一個人：跨段一致的說話者編號是 #93。
    """

    def __init__(self) -> None:
        self._ids: Dict[str, str] = {}

    def of(self, code: str) -> str:
        return self._ids.setdefault(code, f"S{len(self._ids)}")


def _parse_line(line: str) -> Optional[Tuple[float, Optional[str], str]]:
    """一行 LRC → （開始秒數, 說話者代號, 文字）；沒有時間戳時是 None。

    行首可以有空白或項目符號；說話者代號可以寫在時間戳前面或後面。
    """
    rest = line.strip()
    marker = _LIST_MARKER_RE.match(rest)
    if marker:
        rest = rest[marker.end():]
    code = _SPEAKER_CODE_RE.match(rest)
    if code:
        rest = rest[code.end():]
    stamp = _TIMESTAMP_RE.match(rest)
    if not stamp:
        return None
    rest = rest[stamp.end():]
    if not code:
        code = _SPEAKER_CODE_RE.match(rest)
        if code:
            rest = rest[code.end():]
    hours, minutes, seconds = stamp.groups()
    start = int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds)
    return start, _normalized_code(code.group(1) or code.group(2)) if code else None, rest.strip()


def _segments_from_lrc(lrc_text: str, speaker_ids: _SpeakerIds) -> List[Dict[str, Any]]:
    """把 Gemini 寫的 LRC 解析成片段，時間軸是送進去的這段音檔。

    - 只在換行斷開。行首可以有空白或項目符號；時間戳可以帶小時，小數兩位、三位或省略。
    - 沒有時間戳的行丟掉；時間戳（和說話者代號）後面沒有文字的行也丟掉。log 只記丟掉幾行，
      不記內容。
    - 說話者代號（「Speaker 1:」「Speaker A:」，寫在時間戳前面或後面都可以）轉成說話者編號，
      規則見 :class:`_SpeakerIds`。代號不分大小寫、可以加 markdown 粗體，全形數字與前導零
      正規化（見 :func:`_normalized_code`）。沒有代號的行沒有說話者編號。
    - 結束時間只用 Gemini 明寫的：照 LRC 的慣例，緊接在文字行後（中間只能有空行）、只有時間戳
      的行是那一行的結束，晚於它的開始才算。其他片段沒有結束時間，不拿下一行的開始來猜：猜的值
      會被字幕當成真實的結束時間。
    """
    segments: List[Dict[str, Any]] = []
    after_text = False  # 上一個帶時間戳的行是文字行
    dropped = 0
    # 只在換行斷開（行尾的 \r 由 _parse_line 去掉）：splitlines() 連 U+2028 之類的字元也會斷，
    # 一行被拆成兩半，沒有時間戳的後半就被丟掉
    for line in lrc_text.split("\n"):
        parsed = _parse_line(line)
        if parsed is None:
            if line.strip():
                # 沒有時間戳的文字擋在中間：後面的只有時間戳的行就不是緊接在文字行後；空行不算
                dropped += 1
                after_text = False
            continue
        start, code, text = parsed
        if not text:
            if after_text and code is None and start > segments[-1]["start"]:
                segments[-1]["end"] = start
            else:
                dropped += 1
            after_text = False
            continue
        speaker = speaker_ids.of(code) if code else None
        segments.append({
            "seg_key": f"{len(segments):04d}", "seq": len(segments),
            "start": start, "end": None,
            "speaker": speaker, "text": text, "source": "gemini",
        })
        after_text = True
    if dropped:
        # 只記行數、不記內容：日誌是使用者自己附上來排查問題的（ADR-0005）
        logger.info(f"Gemini 的 LRC 丟掉 {dropped} 行：沒有時間戳，或時間戳後面沒有文字")
    return segments


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
    """批次裡一個請求的回應；成功時 text 是 Gemini 寫的 LRC（#115 之前批次還處理 LRC 文字），
    失敗時是要存進任務紀錄的錯誤訊息。"""
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
    # 畫面直接顯示模型名稱；轉錄用的是使用者自備的 Gemini API 金鑰
    info = ProviderInfo(label="Gemini", requires_api_key=True)

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
        # 一個轉接器只給一個任務用：分段轉錄的各段依時間先後送進來，同一個說話者代號在各段才會
        # 對到同一個說話者編號
        self._speaker_ids = _SpeakerIds()

    @staticmethod
    def capabilities() -> Dict[str, ModelCapabilities]:
        return {model: _capabilities() for model in MODELS}

    @staticmethod
    def check_ready(model: str, api_key: str) -> str:
        """設定頁的「測試」：用金鑰連一次 Gemini API（列出模型），結果和所選的模型無關。"""
        status = GeminiClient(api_key=api_key).test_connection()
        if not status.success:
            raise ValueError(status.message or "測試失敗，但未提供具體原因。")
        return "Gemini API (Google) 測試成功。"

    def transcribe(
        self, audio_path: Path, request: TranscribeRequest, progress: ProgressAndCancel,
    ) -> TranscriptionTaskResult:
        # 使用者已經取消時，音檔不再往外送
        progress.raise_if_cancelled()
        progress.report("上傳檔案至AI模型...")
        gemini_file = self.upload(audio_path, progress)

        progress.report("AI模型處理中...")
        logger.info(f"正在使用 {request.model} 進行轉錄... "
                    f"(requested service_tier={request.service_tier or 'standard'})")
        logger.info(f"Prompt fingerprint: {_prompt_fingerprint(request.prompt)}")
        contents = [request.prompt, gemini_file]
        # 拿到回應的那次請求是以哪種處理模式送出的
        sent_tier = "flex"
        response = (self._generate_flex(request.model, contents, progress)
                    if request.service_tier == "flex" else None)
        if response is None:
            sent_tier = "standard"
            response = self._generate_standard(request.model, contents, progress)
        return _transcription_result(
            response, _tier_used(response, request.service_tier, sent_tier), self._speaker_ids)

    def _generate_flex(self, model: str, contents: List[Any], progress: ProgressAndCancel) -> Any:
        """Flex：429／503 以指數退避重試；用完或遇到其他錯誤回 None，由呼叫端退回標準。

        每次送出（含每次重試）之前都查一次取消：生成照次收費。
        """
        config = _generation_config(model, "flex")
        logger.info("[FLEX] 準備呼叫 Gemini Flex API (https://ai.google.dev/gemini-api/docs/flex-inference) "
                    f"model={model} config={config.model_dump(exclude_none=True)}")
        last_error: Optional[Exception] = None
        for attempt in range(FLEX_MAX_RETRIES):
            progress.raise_if_cancelled()
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

    def _generate_standard(self, model: str, contents: List[Any], progress: ProgressAndCancel) -> Any:
        progress.raise_if_cancelled()
        logger.info(f"[STANDARD] 呼叫 Gemini 標準同步 API model={model}")
        try:
            return self._client.models.generate_content(
                model=model, contents=contents, config=_generation_config(model, None))
        except Exception as e:
            raise _classify(e) from e

    def upload(self, audio_path: Path, progress: ProgressAndCancel = _UNCANCELLABLE) -> Any:
        """上傳到 File API，等 Gemini 處理完才回傳；遠端檔在 :meth:`release` 刪除。

        等處理的期間使用者取消（``progress``）就不等了，拋
        :class:`~app.exceptions.TranscriptionCancelledError`。
        """
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
            progress.raise_if_cancelled()
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
