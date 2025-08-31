from typing import Any, Dict
from google import genai
from google.genai import types
from pathlib import Path
import time

from app.schemas.schemas import ServiceStatus
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


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

    gemini_file = client.files.upload(file=file_path)

    # 等待檔案處理完成
    processing_dots = 0
    while gemini_file.state.name == "PROCESSING":
        processing_dots += 1
        if processing_dots % 10 == 1:  # 每10個點換行顯示一次
            logger.info(f"檔案處理中{'.' * (processing_dots % 10)}")
        time.sleep(2)
        gemini_file = client.files.get(name=gemini_file.name)

    if gemini_file.state.name == "FAILED":
        raise ValueError(f"Gemini 檔案處理失敗: {gemini_file.state}")

    logger.info(f"檔案 '{file_path.name}' 上傳並處理完畢")
    return gemini_file


def count_tokens_with_uploaded_file(client, gemini_file, model: str) -> int:
    """
    使用已上傳的檔案計算 token 數量
    """
    logger.info("正在計算檔案的輸入 tokens...")
    response = client.models.count_tokens(
        model=model, contents=[gemini_file])
    return response.total_tokens


def transcribe_with_uploaded_file(
    client,
    gemini_file,
    model: str,
    prompt: str
) -> Dict[str, Any]:
    """
    使用已上傳的檔案進行轉錄
    """
    logger.info(f"正在使用 {model} 進行轉錄...")
    response = client.models.generate_content(
        model=model,
        contents=[prompt, gemini_file],
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=128)
        )
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
    input_tokens = response.usage_metadata.prompt_token_count
    output_tokens = response.usage_metadata.candidates_token_count
    total_tokens = response.usage_metadata.total_token_count

    logger.info(f"Token 使用統計:")
    logger.info(
        f"  Input (Prompt) tokens: {input_tokens:>8,}")
    logger.info(
        f"  Output (Candidates) tokens: {output_tokens:>8,}")
    logger.info(
        f"  Thoughts tokens: {response.usage_metadata.thoughts_token_count or 'N/A':>8}")
    logger.info(f"  Total tokens: {total_tokens:>8,}")

    return {
        "success": True,
        "text": response.text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens
    }


def translate_text(
    client: genai.Client,
    model: str,
    prompt: str,
    text_to_translate: str
) -> Dict[str, Any]:
    """
    使用 Gemini API 進行文字翻譯。
    """
    logger.info(f"正在使用 {model} 進行翻譯...")
    try:
        contents = [prompt, text_to_translate]
        response = client.models.generate_content(
            model=model,
            contents=contents
        )

        if not response.candidates:
            logger.warning("警告: Gemini 沒有回傳任何內容。回應可能已被其安全機制阻擋。")
            error_text = "[[翻譯失敗：Gemini 回應被阻擋]]"
            try:
                error_text = f"[[翻譯失敗：請求被 Gemini 以 '{response.prompt_feedback.block_reason}' 原因阻擋。]]"
            except Exception:
                pass

            total_tokens = 0
            if hasattr(response.usage_metadata, 'prompt_token_count'):
                total_tokens = response.usage_metadata.prompt_token_count

            return {
                "success": False,
                "translated_text": error_text,
                "input_tokens": total_tokens,
                "output_tokens": 0,
                "total_tokens": total_tokens
            }

        input_tokens = response.usage_metadata.prompt_token_count
        output_tokens = response.usage_metadata.candidates_token_count
        total_tokens = response.usage_metadata.total_token_count

        return {
            "success": True,
            "translated_text": response.text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens
        }
    except Exception as e:
        logger.error(f"Gemini 翻譯 API 呼叫時發生錯誤: {e}", exc_info=True)
        return {
            "success": False,
            "translated_text": f"[[翻譯錯誤: {str(e)}]]",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }


def cleanup_gemini_file(client, gemini_file):
    """
    清理 Gemini API 上的檔案
    """
    client.files.delete(name=gemini_file.name)
    logger.info(f"已從 Gemini API 清理檔案: {gemini_file.name}")
