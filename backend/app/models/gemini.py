from typing import Any, Dict
from openai import OpenAI
import ast
import google.generativeai as genai
from pathlib import Path
import time
import json

from app.schemas.schemas import ServiceStatus


class GeminiClient:
    """
    使用 OpenAI 相容性層與 Google Gemini API 進行互動的客戶端。
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
            # 使用 OpenAI SDK 格式初始化客戶端，連接到 Gemini
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            print("GeminiClient (OpenAI-compat) initialized successfully.")
        except Exception as e:
            self.client = None
            print(f"Failed to initialize GeminiClient (OpenAI-compat): {e}")

    def test_connection(self) -> ServiceStatus:
        """
        透過列出可用模型來測試與 Gemini API 的連接。
        """
        if not self.client:
            error_message = "GeminiClient: 客戶端未初始化，無法測試連接。"
            print(error_message)
            return ServiceStatus(success=False, message=error_message)

        try:
            self.client.models.list()  # 如果此調用失敗，將引發異常
            return ServiceStatus(success=True, message="Gemini API 測試成功。")

        except Exception as e:
            message = str(e)  # 預設為完整的錯誤訊息
            try:
                # API 錯誤通常包含一個字串化的字典，我們嘗試解析它以獲得更清晰的訊息
                error_body_str = str(e).split(' - ', 1)[1]
                error_body = ast.literal_eval(error_body_str)
                if isinstance(error_body, dict):
                    # 安全地提取 'message'
                    message = error_body.get(
                        'error', {}).get('message', message)
            except (IndexError, ValueError, SyntaxError):
                # 如果解析失敗，我們將使用原始的完整異常字串。
                pass

            print(f"Gemini connection test failed: {message}")
            return ServiceStatus(success=False, message=message)


def count_tokens_for_file(file_path: Path, api_key: str, model_name: str) -> int:
    """
    計算給定媒體檔案和提示所需的輸入 token 數量。
    """
    if not all([file_path.exists(), api_key, model_name]):
        raise ValueError("缺少檔案路徑、API 金鑰或模型名稱。")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=model_name)

    print(f"正在為檔案 '{file_path.name}' 計算輸入 tokens...")
    gemini_file = genai.upload_file(path=file_path)

    try:
        response = model.count_tokens(contents=[gemini_file])
        return response.total_tokens
    finally:
        # 計算完 token 後也應該清理檔案
        genai.delete_file(name=gemini_file.name)
        print(f"已從 Gemini API 清理用於計算 token 的檔案: {gemini_file.name}")


def transcribe_video_with_gemini(
    file_path: Path,
    api_key: str,
    model_name: str,
    prompt: str
) -> Dict[str, Any]:
    """
    使用指定的 Gemini 模型與提示詞轉錄媒體檔案，並回傳轉錄結果與 token 用量。
    """
    if not all([api_key, model_name, prompt]):
        raise ValueError("缺少 API 金鑰、模型名稱或提示詞。")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=model_name)

    print(f"正在上傳檔案至 Gemini API 進行轉錄: {file_path.name}")
    gemini_file = genai.upload_file(path=file_path)

    try:
        while gemini_file.state.name == "PROCESSING":
            print('.', end='', flush=True)
            time.sleep(2)
            gemini_file = genai.get_file(name=gemini_file.name)

        if gemini_file.state.name == "FAILED":
            raise ValueError(f"Gemini 檔案處理失敗: {gemini_file.state}")

        print(f"\n檔案處理完畢。正在使用 {model_name} 進行轉錄...")
        response = model.generate_content(
            [prompt, gemini_file], request_options={"timeout": 600})

        # 從回傳中提取 token 用量
        total_tokens_used = response.usage_metadata.total_token_count

        return {
            "text": response.text,
            "total_tokens_used": total_tokens_used
        }
    finally:
        # 確保無論成功或失敗，都清理檔案
        genai.delete_file(name=gemini_file.name)
        print(f"已從 Gemini API 清理用於轉錄的檔案: {gemini_file.name}")
