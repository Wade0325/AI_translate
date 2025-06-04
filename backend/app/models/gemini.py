from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions
from typing import Dict, Any


class GeminiClient:
    def __init__(self, api_key: str):
        """
        初始化 Gemini 客戶端並配置 API 金鑰。
        根據最新的 google-genai SDK (例如 1.0.0 及更高版本)
        不再使用 genai.configure()，而是直接建立一個 client 實例。

        Args:
            api_key: 用於 Gemini API 的 API 金鑰。
        """
        self.api_key = api_key
        try:
            # 根據最新文件，這樣建立 client
            self.client = genai.Client(api_key=self.api_key)
            print("GeminiClient: genai.Client initialized successfully.")
        except Exception as e:
            print(
                f"GeminiClient: Error during genai.Client initialization: {e}")
            # 如果客戶端初始化失敗，後續操作將無法進行，可以選擇拋出異常
            # 或者讓 test_connection 處理這種情況 (例如 self.client 可能為 None)
            self.client = None  # 標記 client 初始化失敗
            # raise RuntimeError(f"Failed to initialize Gemini Client: {e}") from e

    def test_connection(self, model_name: str = "gemini-pro") -> Dict[str, Any]:
        """
        測試與 Gemini API 的連接。
        使用 self.client.models.generate_content 進行請求。
        """
        final_print_message = None

        if not self.client:
            error_message = "GeminiClient: Client was not initialized. Cannot test connection."
            print(error_message)
            return {"success": False, "message": error_message, "response": None}

        try:
            for m in self.client.models.list():
                for action in m.supported_actions:
                    if action == "generateContent":
                        print(m.name)

            client = genai.Client(api_key=self.api_key)
            # 發送一個簡單的提示來測試連接性
            response = client.models.list()
            print(response)
            if response:
                return {
                    "success": True,
                    "message": f"成功連接到 Gemini 模型 '{model_name}' 並收到回應。",
                    "response": "AAA"
                }
            # 檢查是否有因安全設定等原因被阻擋的提示
            elif response.prompt_feedback and response.prompt_feedback.block_reason:
                block_reason_message = getattr(response.prompt_feedback, 'block_reason_message', str(
                    response.prompt_feedback.block_reason))
                return {
                    "success": False,
                    "message": f"已連接到 Gemini 模型 '{model_name}'，但提示被阻擋。原因: {block_reason_message}",
                    "response": None
                }
            else:
                # 若 response.text 為空，但沒有明確的 block_reason
                parts_str = ""
                try:
                    parts_str = str(response.parts)
                except Exception:
                    parts_str = "Could not serialize response parts."
                return {
                    "success": False,
                    "message": f"已連接到 Gemini 模型 '{model_name}' 但收到空的或非預期的回應結構。回應部分: {parts_str}",
                    "response": None
                }

        except google_exceptions.PermissionDenied as e:
            return {
                "success": False,
                "message": f"Gemini API 金鑰無效或缺乏對模型 '{model_name}' 的權限。詳細資訊: {e.message}",
                "response": None
            }
        except google_exceptions.Unauthenticated as e:
            return {
                "success": False,
                "message": f"Gemini API 請求未經驗證 (模型 '{model_name}')。請檢查 API 金鑰。詳細資訊: {e.message}",
                "response": None
            }
        except google_exceptions.InvalidArgument as e:
            # 通常是模型名稱錯誤或請求格式錯誤
            return {
                "success": False,
                "message": f"Gemini API 的參數無效，可能是模型名稱 ('{model_name}') 不正確或請求格式錯誤。詳細資訊: {e.message}",
                "response": None
            }
        except google_exceptions.GoogleAPIError as e:  # 捕獲其他 Google API 錯誤
            return {
                "success": False,
                "message": f"測試 Gemini 模型 '{model_name}' 時發生 Google API 錯誤。詳細資訊: {e.message}",
                "response": None
            }
        except Exception as e:  # 通用錯誤捕獲
            return {
                "success": False,
                "message": f"測試 Gemini 模型 '{model_name}' 時發生未預期錯誤。錯誤: {str(e)}",
                "response": None
            }
