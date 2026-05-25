from typing import Any, Dict, Optional
from google import genai
from google.genai import types
from pathlib import Path
import hashlib
import time

from app.exceptions import GeminiPermanentError, GeminiTransientError
from app.schemas.schemas import ServiceStatus
from app.utils.logger import setup_logger
from app.utils.audio import get_mime_type

logger = setup_logger(__name__)


def _prompt_fingerprint(prompt: str) -> str:
    """回傳 prompt 的長度與 md5 前綴，避免將完整內容寫入 log。"""
    digest = hashlib.md5(prompt.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"len={len(prompt)} md5={digest}"


def _classify_gemini_error(err: Exception) -> Exception:
    """將原始 Gemini SDK 例外分類為 Transient / Permanent。

    呼叫端應立刻 raise 回傳值，例如：
        raise _classify_gemini_error(e) from e
    """
    if _is_flex_retryable_error(err):
        return GeminiTransientError(str(err))
    return GeminiPermanentError(str(err))


# Flex 推論設定（參考 Google 官方文件）
# https://ai.google.dev/gemini-api/docs/flex-inference
FLEX_MAX_RETRIES = 3
FLEX_BASE_DELAY = 5  # 初始退避秒數
FLEX_TIMEOUT_MS = 900_000  # 15 分鐘，Flex 建議至少 10 分鐘以上


def _is_flex_retryable_error(err: Exception) -> bool:
    """判斷 Flex 請求是否遇到 429 / 503 之類可重試錯誤"""
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


def _extract_actual_service_tier(response) -> Optional[str]:
    """
    從 Gemini 回應的 HTTP header 取得實際使用的 service tier。
    參考: https://ai.google.dev/gemini-api/docs/flex-inference (cookbook 範例)
    回應 header `x-gemini-service-tier` 可能為:
        'flex' / 'standard' / 'priority'
    若 SDK 版本不支援 sdk_http_response（< 1.69.0）或 header 不存在則回 None。
    """
    try:
        sdk_http_response = getattr(response, "sdk_http_response", None)
        if sdk_http_response is None:
            return None
        headers = getattr(sdk_http_response, "headers", None)
        if headers is None:
            return None
        # headers 可能是 dict 或類 dict 物件
        tier = None
        if hasattr(headers, "get"):
            tier = headers.get("x-gemini-service-tier") or headers.get("X-Gemini-Service-Tier")
        if tier:
            return str(tier).strip().lower()
    except Exception as e:  # pragma: no cover - 防呆
        logger.debug(f"讀取 x-gemini-service-tier header 失敗: {e}")
    return None


class GeminiClient:
    """
    與 Google Gemini API 進行互動的客戶端。
    """

    def __init__(self, api_key: str):
        """
        初始化客戶端。
        :param api_key: 您的 Google AI Studio API 金鑰。
        """
        if not api_key:
            self.client = None
            logger.warning("GeminiClient: 未提供 API 金鑰，客戶端未初始化。")
            return

        try:
            self.client = genai.Client(api_key=api_key)
            logger.info("GeminiClient 初始化成功")
        except Exception as e:
            self.client = None
            logger.error(f"初始化 GeminiClient 失敗: {e}")

    def test_connection(self) -> ServiceStatus:
        """
        透過列出可用模型來測試與 Gemini API 的連接。
        """
        if not self.client:
            error_message = "GeminiClient: 客戶端未初始化，無法測試連接。"
            logger.error(error_message)
            return ServiceStatus(success=False, message=error_message)

        try:
            list(self.client.models.list())
            return ServiceStatus(success=True, message="Gemini API 測試成功。")

        except Exception as e:
            message = str(e)
            logger.error(f"Gemini 連接測試失敗: {message}")
            return ServiceStatus(success=False, message=message)


def upload_file_to_gemini(file_path: Path, client: genai.Client, status_callback=None):
    """
    上傳檔案到 Gemini API，返回 gemini_file 物件
    """
    if not file_path.exists():
        raise ValueError("檔案不存在。")

    logger.info(f"正在上傳檔案至 Gemini API: {file_path.name}")
    if status_callback:
        status_callback(f"上傳檔案至AI模型...")

    mime_type = get_mime_type(file_path)
    config = {"display_name": file_path.stem}
    if mime_type:
        config["mime_type"] = mime_type
        logger.info(f"使用 MIME 類型: {mime_type}")

    try:
        with open(file_path, "rb") as f:
            gemini_file = client.files.upload(file=f, config=config)
    except Exception as e:
        raise _classify_gemini_error(e) from e

    # 等待檔案處理完成
    processing_dots = 0
    while gemini_file.state.name == "PROCESSING":
        processing_dots += 1
        if processing_dots % 10 == 1:  # 每10個點換行顯示一次
            logger.info(f"檔案處理中{'.' * (processing_dots % 10)}")
        time.sleep(2)
        try:
            gemini_file = client.files.get(name=gemini_file.name)
        except Exception as e:
            raise _classify_gemini_error(e) from e

    if gemini_file.state.name == "FAILED":
        raise GeminiPermanentError(f"Gemini 檔案處理失敗: {gemini_file.state}")

    logger.info(f"檔案 '{file_path.name}' 上傳並處理完畢")
    return gemini_file


def _is_gemini_3_model(model: str) -> bool:
    """Gemini 3.x 系列使用 thinking_level，不再建議 thinking_budget。"""
    return model.startswith("gemini-3")


def _build_thinking_config(model: str) -> types.ThinkingConfig:
    """依模型世代選擇思考設定（參考 Gemini 3.5 遷移指南）。"""
    if _is_gemini_3_model(model):
        # 轉錄屬分析型任務，low 在品質與延遲/成本間較平衡
        return types.ThinkingConfig(thinking_level="low")
    return types.ThinkingConfig(thinking_budget=128)


def _build_transcription_config(
    model: str,
    service_tier: Optional[str],
) -> types.GenerateContentConfig:
    """建構 generate_content 的 config；Flex 會加上 service_tier 與延長逾時"""
    kwargs: Dict[str, Any] = {
        "thinking_config": _build_thinking_config(model),
    }
    if service_tier == "flex":
        kwargs["service_tier"] = "flex"
        kwargs["http_options"] = types.HttpOptions(timeout=FLEX_TIMEOUT_MS)
    return types.GenerateContentConfig(**kwargs)


def transcribe_with_uploaded_file(
    client,
    gemini_file,
    model: str,
    prompt: str,
    service_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用已上傳的檔案進行轉錄。

    service_tier:
      - None / "standard": 使用標準同步 API（原有行為）
      - "flex": 使用 Flex 推論（50% 折扣、分鐘級延遲、可捨棄）；
                當遇到 429/503 時以指數退避重試 FLEX_MAX_RETRIES 次，
                若仍失敗則自動降級回 Standard 層級重送一次。
    回傳字典額外帶有 `service_tier_used`，讓上層可據此決定是否套用費用折扣。
    """
    logger.info(f"正在使用 {model} 進行轉錄... (requested service_tier={service_tier or 'standard'})")
    logger.info(f"Prompt fingerprint: {_prompt_fingerprint(prompt)}")

    response = None
    tier_used = "standard"

    if service_tier == "flex":
        flex_config = _build_transcription_config(model, "flex")
        # 驗證 log: 確認真的把 service_tier=flex 包進 config 才送出
        try:
            cfg_dump = flex_config.model_dump(exclude_none=True)  # type: ignore[attr-defined]
        except Exception:
            cfg_dump = {"service_tier": getattr(flex_config, "service_tier", None)}
        logger.info(
            f"[FLEX] 準備呼叫 Gemini Flex API (https://ai.google.dev/gemini-api/docs/flex-inference) "
            f"model={model} config={cfg_dump}"
        )
        last_error: Optional[Exception] = None
        for attempt in range(FLEX_MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[prompt, gemini_file],
                    config=flex_config,
                )
                tier_used = "flex"
                last_error = None
                break
            except Exception as e:
                last_error = e
                if _is_flex_retryable_error(e) and attempt < FLEX_MAX_RETRIES - 1:
                    delay = FLEX_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"[FLEX] 呼叫失敗 (attempt {attempt + 1}/{FLEX_MAX_RETRIES}): {e}，"
                        f"{delay} 秒後重試..."
                    )
                    time.sleep(delay)
                    continue
                # 不可重試或重試次數用盡
                logger.warning(
                    f"[FLEX] 呼叫失敗 (attempt {attempt + 1}/{FLEX_MAX_RETRIES}): {e}，停止重試"
                )
                break

        if response is None:
            logger.warning(
                f"[FLEX] 推論耗盡，自動降級改以 Standard 層級重試: {last_error}"
            )
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[prompt, gemini_file],
                    config=_build_transcription_config(model, None),
                )
            except Exception as e:
                raise _classify_gemini_error(e) from e
            tier_used = "standard"
    else:
        logger.info(f"[STANDARD] 呼叫 Gemini 標準同步 API model={model}")
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt, gemini_file],
                config=_build_transcription_config(model, None),
            )
        except Exception as e:
            raise _classify_gemini_error(e) from e
        tier_used = "standard"

    # === 從回應 HTTP header 驗證 API 實際使用的 service tier ===
    actual_tier = _extract_actual_service_tier(response)
    if actual_tier:
        if service_tier == "flex" and actual_tier == "flex":
            logger.info(
                f"[FLEX VERIFIED] Gemini 回應 header x-gemini-service-tier=flex"
                f"（已確認使用 Flex API，享 50% 折扣）"
            )
        elif service_tier == "flex" and actual_tier != "flex":
            logger.warning(
                f"[FLEX DOWNGRADED] 請求送出 service_tier=flex，但回應 header "
                f"x-gemini-service-tier={actual_tier}（API 端降級或未套用 Flex）"
            )
        else:
            logger.info(
                f"[TIER] Gemini 回應 header x-gemini-service-tier={actual_tier}"
            )
        # 以 header 為權威來源（避免 SDK 端聲明與實際處理不一致）
        tier_used = actual_tier if actual_tier in ("flex", "standard", "priority") else tier_used
    else:
        logger.info(
            f"[TIER] 無法從回應讀取 x-gemini-service-tier header"
            f"（可能 google-genai SDK < 1.69.0），維持以請求端判定 tier_used={tier_used}"
        )

    # 檢查回應是否被阻擋
    if not response.candidates:
        logger.warning("--- Gemini 回應錯誤 ---")
        logger.warning("警告: Gemini 沒有回傳任何內容。回應可能已被其安全機制阻擋。")
        error_text = "[[轉錄失敗：Gemini 回應被阻擋]]"
        try:
            logger.warning(f"阻擋原因: {response.prompt_feedback.block_reason}")
            error_text = f"[[轉錄失敗：請求被 Gemini 以 '{response.prompt_feedback.block_reason}' 原因阻擋。]]"
        except Exception:
            logger.warning("無法取得明確的阻擋原因。")
        logger.warning("-----------------------")

    # 從回傳中提取 token 用量
    # 注意：某些回應（如 thinking 模式、部分阻擋、極短內容）可能讓單一欄位為 None，
    # 這裡統一防護避免後續 log 格式化或費用計算炸鍋
    input_tokens = response.usage_metadata.prompt_token_count or 0
    output_tokens = response.usage_metadata.candidates_token_count or 0
    total_tokens = response.usage_metadata.total_token_count or 0
    thoughts_tokens = response.usage_metadata.thoughts_token_count

    logger.info(f"Token 使用統計:")
    logger.info(
        f"  Input (Prompt) tokens: {input_tokens:>8,}")
    logger.info(
        f"  Output (Candidates) tokens: {output_tokens:>8,}")
    logger.info(
        f"  Thoughts tokens: {(thoughts_tokens if thoughts_tokens is not None else 'N/A'):>8}")
    logger.info(f"  Total tokens: {total_tokens:>8,}")

    return {
        "success": True,
        "text": response.text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "service_tier_used": tier_used,
    }


def cleanup_gemini_file(client, gemini_file):
    """
    清理 Gemini API 上的檔案。失敗時僅警告，不中斷流程。
    """
    try:
        client.files.delete(name=gemini_file.name)
        logger.info(f"已從 Gemini API 清理檔案: {gemini_file.name}")
    except Exception as e:
        logger.warning(f"清理 Gemini 檔案 {gemini_file.name} 失敗: {e}")


# ==================== Batch API ====================

BATCH_COMPLETED_STATES = frozenset({
    'JOB_STATE_SUCCEEDED',
    'JOB_STATE_FAILED',
    'JOB_STATE_CANCELLED',
    'JOB_STATE_EXPIRED',
})


def create_batch_transcription_job(
    client: genai.Client,
    gemini_files: list,
    model: str,
    prompt: str,
    display_name: str = "transcription-batch"
) -> Any:
    """
    使用 Gemini Batch API 建立批次轉錄任務。
    將多個已上傳的音訊檔案打包為 inline requests 提交，
    享有標準 API 50% 的費用折扣。
    """
    inline_requests = []
    for gemini_file in gemini_files:
        request = {
            'contents': [{
                'parts': [
                    {'text': prompt},
                    {'file_data': {
                        'file_uri': gemini_file.uri,
                        'mime_type': gemini_file.mime_type
                    }}
                ],
                'role': 'user'
            }]
        }
        inline_requests.append(request)

    logger.info(f"建立批次任務: {len(inline_requests)} 個請求, 模型: {model}")
    logger.info(f"Batch prompt fingerprint: {_prompt_fingerprint(prompt)}")
    try:
        batch_job = client.batches.create(
            model=model,
            src=inline_requests,
            config={'display_name': display_name},
        )
    except Exception as e:
        raise _classify_gemini_error(e) from e
    logger.info(f"批次任務已建立: {batch_job.name}")
    return batch_job


def poll_batch_job_status(client: genai.Client, job_name: str) -> Any:
    """查詢 Gemini Batch API 任務狀態"""
    try:
        return client.batches.get(name=job_name)
    except Exception as e:
        raise _classify_gemini_error(e) from e


def get_batch_job_state_name(batch_job) -> str:
    """安全地取得批次任務狀態名稱"""
    if hasattr(batch_job.state, 'name'):
        return batch_job.state.name
    return str(batch_job.state)
