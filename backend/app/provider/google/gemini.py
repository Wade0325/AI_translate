"""google-genai 用戶端：用 API 金鑰建立，設定頁也用它測試金鑰。

上傳、轉錄、刪除遠端檔與批次都在 Gemini 轉接器（:mod:`app.provider.google.provider`）。
"""

from google import genai

from app.schemas.schemas import ServiceStatus
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class GeminiClient:
    """Gemini SDK client 的薄包裝；金鑰無效時 self.client 為 None。"""

    def __init__(self, api_key: str):
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
        """透過列出可用模型來測試與 Gemini API 的連接。"""
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
