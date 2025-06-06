from typing import Any, Dict
from openai import OpenAI, AuthenticationError, APIConnectionError, APIStatusError
import ast

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

    def test_connection(self) -> Dict[str, Any]:
        """
        透過列出可用模型來測試與 Gemini API 的連接。
        這是在 OpenAI 相容模式下的標準做法。
        """
        if not self.client:
            error_message = "GeminiClient: 客戶端未初始化，無法測試連接。"
            print(error_message)
            return {"success": False, "message": error_message}

        try:
            # 使用 client.models.list() 來驗證 API 金鑰和連接
            models_response = self.client.models.list()

            # 提取模型名稱
            model_names = [model.id for model in models_response.data]

            if model_names:
                # 為了簡潔，只顯示部分模型名稱
                display_names = [
                    name for name in model_names if 'gemini' in name][:3]
                response_str = f"成功獲取 {len(model_names)} 個模型，例如: {', '.join(display_names)}{'...' if len(display_names) >= 3 else ''}"
                return {
                    "success": True,
                    "message": "成功連接到 Gemini API (OpenAI 相容模式) 並獲取可用模型列表。",
                }
            else:
                return {
                    "success": False,
                    "message": "已連接到 Gemini API，但未返回任何可用模型。請檢查您的 API 金鑰權限。",
                }
    
        except Exception as e:
            dict_part_string = str(e).split(' - ', 1)[1]
            data_dict = ast.literal_eval(dict_part_string)
            message = data_dict['error']['message']
            print(message)
            return {
                "success": False,
                "message": message,
            }
