# import google.generativeai as genai
# from app.schemas.schemas import ServiceStatus
# from app.utils.logger import setup_logger
# from .models import GeminiConfig

# logger = setup_logger(__name__)


# class GeminiService:
#     """
#     與 Google Gemini API 進行互動的服務。
#     負責客戶端初始化和連接測試。
#     """
#     _client: genai.Client | None = None

#     @classmethod
#     def initialize(cls, config: GeminiConfig):
#         """
#         使用提供的 API 金鑰初始化 Gemini 客戶端。
#         :param config: 包含 API 金鑰的 GeminiConfig 物件。
#         """
#         if not config.api_key:
#             cls._client = None
#             logger.warning("GeminiService: 未提供 API 金鑰，客戶端未初始化。")
#             return

#         try:
#             cls._client = genai.Client(api_key=config.api_key)
#             logger.info("GeminiService 初始化成功")
#         except Exception as e:
#             cls._client = None
#             logger.error(f"初始化 GeminiService 失敗: {e}")

#     @classmethod
#     def get_client(cls) -> genai.Client:
#         """
#         獲取 Gemini 客戶端實例。
#         如果客戶端未初始化，則會引發 Exception。
#         """
#         if cls._client is None:
#             raise Exception("GeminiService 未初始化。請先呼叫 initialize。")
#         return cls._client

#     @classmethod
#     def test_connection(cls) -> ServiceStatus:
#         """
#         透過列出可用模型來測試與 Gemini API 的連接。
#         """
#         if not cls._client:
#             error_message = "GeminiService: 客戶端未初始化，無法測試連接。"
#             logger.error(error_message)
#             return ServiceStatus(success=False, message=error_message)

#         try:
#             list(cls._client.models.list())
#             return ServiceStatus(success=True, message="Gemini API 測試成功。")
#         except Exception as e:
#             message = str(e)
#             logger.error(f"Gemini 連接測試失敗: {message}")
#             return ServiceStatus(success=False, message=message)
