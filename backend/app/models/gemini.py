from typing import Any, Dict
import ast
from google import genai
from google.genai import types
from pathlib import Path
import time
import json

from app.schemas.schemas import ServiceStatus


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
            print("GeminiClient: 未提供 API 金鑰，客戶端未初始化。")
            return

        try:
            # 使用 google-genai SDK 初始化客戶端
            self.client = genai.Client(api_key=api_key)
            print("GeminiClient initialized successfully.")
        except Exception as e:
            self.client = None
            print(f"Failed to initialize GeminiClient: {e}")

    def test_connection(self) -> ServiceStatus:
        """
        透過列出可用模型來測試與 Gemini API 的連接。
        """
        if not self.client:
            error_message = "GeminiClient: 客戶端未初始化，無法測試連接。"
            print(error_message)
            return ServiceStatus(success=False, message=error_message)

        try:
            list(self.client.models.list())  # 如果此調用失敗，將引發異常
            return ServiceStatus(success=True, message="Gemini API 測試成功。")

        except Exception as e:
            message = str(e)
            print(f"Gemini connection test failed: {message}")
            return ServiceStatus(success=False, message=message)


def upload_file_to_gemini(file_path: Path, client: genai.Client):
    """
    上傳檔案到 Gemini API，返回 gemini_file 物件
    """
    if not file_path.exists():
        raise ValueError("檔案不存在。")

    print(f"正在上傳檔案至 Gemini API: {file_path.name}")
    gemini_file = client.files.upload(file=file_path)

    # 等待檔案處理完成
    while gemini_file.state.name == "PROCESSING":
        print('.', end='', flush=True)
        time.sleep(2)
        gemini_file = client.files.get(name=gemini_file.name)

    if gemini_file.state.name == "FAILED":
        raise ValueError(f"Gemini 檔案處理失敗: {gemini_file.state}")

    print(f"\n檔案 '{file_path.name}' 上傳並處理完畢。")
    return gemini_file


def count_tokens_with_uploaded_file(client, gemini_file, model_name: str) -> int:
    """
    使用已上傳的檔案計算 token 數量
    """
    print(f"正在計算檔案的輸入 tokens...")
    response = client.models.count_tokens(
        model=model_name, contents=[gemini_file])
    return response.total_tokens


def transcribe_with_uploaded_file(
    client,
    gemini_file,
    model_name: str,
    prompt: str
) -> Dict[str, Any]:
    """
    使用已上傳的檔案進行轉錄
    """
    print(f"正在使用 {model_name} 進行轉錄...")
    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, gemini_file],
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        )
    )

    # 檢查回應是否被阻擋
    if not response.candidates:
        print("\n--- Gemini 回應錯誤 ---")
        print("警告: Gemini 沒有回傳任何內容。回應可能已被其安全機制阻擋。")
        error_text = "[[轉錄失敗：Gemini 回應被阻擋]]"
        try:
            print(f"阻擋原因: {response.prompt_feedback.block_reason}")
            error_text = f"[[轉錄失敗：請求被 Gemini 以 '{response.prompt_feedback.block_reason}' 原因阻擋。]]"
        except Exception:
            print("無法取得明確的阻擋原因。")
        print("-----------------------")

        # 即使被阻擋，也嘗試讀取 prompt token
        total_tokens_used = 0
        if hasattr(response.usage_metadata, 'prompt_token_count'):
            total_tokens_used = response.usage_metadata.prompt_token_count

        return {
            "success": False,
            "text": error_text,
            "total_tokens_used": total_tokens_used
        }

    # 從回傳中提取 token 用量
    total_tokens_used = response.usage_metadata.total_token_count
    print("prompt_token_count:", response.usage_metadata.prompt_token_count)
    print("candidates_token_count:",
          response.usage_metadata.candidates_token_count)
    print("thoughts_token_count:",
          response.usage_metadata.thoughts_token_count)

    return {
        "success": True,
        "text": response.text,
        "total_tokens_used": total_tokens_used
    }


def cleanup_gemini_file(client, gemini_file):
    """
    清理 Gemini API 上的檔案
    """
    client.files.delete(name=gemini_file.name)
    print(f"已從 Gemini API 清理檔案: {gemini_file.name}")
