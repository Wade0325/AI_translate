# import time
# from pathlib import Path
# from typing import Any, Dict
# import google.generativeai as genai
# from google.generativeai import types

# from app.utils.logger import setup_logger
# from .service import GeminiService
# from .models import TranscriptionResult

# logger = setup_logger(__name__)


# def _upload_file_to_gemini(client: genai.Client, file_path: Path) -> genai.File:
#     """
#     上傳檔案到 Gemini API，返回 gemini_file 物件
#     """
#     if not file_path.exists():
#         raise ValueError("檔案不存在。")

#     logger.info(f"正在上傳檔案至 Gemini API: {file_path.name}")
#     gemini_file = client.files.upload(file=file_path)

#     processing_dots = 0
#     while gemini_file.state.name == "PROCESSING":
#         processing_dots += 1
#         if processing_dots % 10 == 1:
#             logger.info(f"檔案處理中{'.' * (processing_dots % 10)}")
#         time.sleep(2)
#         gemini_file = client.files.get(name=gemini_file.name)

#     if gemini_file.state.name == "FAILED":
#         raise ValueError(f"Gemini 檔案處理失敗: {gemini_file.state}")

#     logger.info(f"檔案 '{file_path.name}' 上傳並處理完畢")
#     return gemini_file


# def _cleanup_gemini_file(client: genai.Client, gemini_file: genai.File):
#     """
#     清理 Gemini API 上的檔案
#     """
#     client.files.delete(name=gemini_file.name)
#     logger.info(f"已從 Gemini API 清理檔案: {gemini_file.name}")


# def transcribe_audio_with_gemini(
#     file_path: Path,
#     model: str,
#     prompt: str
# ) -> TranscriptionResult:
#     """
#     使用已上傳的檔案進行轉錄的完整流程
#     """
#     client = GeminiService.get_client()
#     gemini_file = None
#     try:
#         gemini_file = _upload_file_to_gemini(client, file_path)

#         logger.info(f"正在使用 {model} 進行轉錄...")
#         response = client.models.generate_content(
#             model=model,
#             contents=[prompt, gemini_file],
#             config=types.GenerateContentConfig(
#                 thinking_config=types.ThinkingConfig(thinking_budget=0)
#             )
#         )

#         if not response.candidates:
#             logger.warning("--- Gemini 回應錯誤 ---")
#             logger.warning("警告: Gemini 沒有回傳任何內容。回應可能已被其安全機制阻擋。")
#             error_text = "[[轉錄失敗：Gemini 回應被阻擋]]"
#             try:
#                 logger.warning(
#                     f"阻擋原因: {response.prompt_feedback.block_reason}")
#                 error_text = f"[[轉錄失敗：請求被 Gemini 以 '{response.prompt_feedback.block_reason}' 原因阻擋。]]"
#             except Exception:
#                 logger.warning("無法取得明確的阻擋原因。")
#             logger.warning("-----------------------")

#             total_tokens_used = 0
#             if hasattr(response.usage_metadata, 'prompt_token_count'):
#                 total_tokens_used = response.usage_metadata.prompt_token_count

#             return TranscriptionResult(
#                 success=False,
#                 text=error_text,
#                 input_tokens=total_tokens_used,
#                 output_tokens=0,
#                 total_tokens_used=total_tokens_used,
#                 error_message=error_text
#             )

#         input_tokens = response.usage_metadata.prompt_token_count
#         output_tokens = response.usage_metadata.candidates_token_count
#         total_tokens_used = response.usage_metadata.total_token_count

#         logger.info(f"Token 使用統計:")
#         logger.info(
#             f"  - Prompt tokens:     {input_tokens:>8,}")
#         logger.info(
#             f"  - Candidates tokens: {output_tokens:>8,}")
#         logger.info(
#             f"  - Thoughts tokens:   {response.usage_metadata.thoughts_token_count or 'N/A':>8}")
#         logger.info(f"  - Total tokens:      {total_tokens_used:>8,}")

#         return TranscriptionResult(
#             success=True,
#             text=response.text,
#             input_tokens=input_tokens,
#             output_tokens=output_tokens,
#             total_tokens_used=total_tokens_used
#         )

#     except Exception as e:
#         logger.error(f"執行 Gemini 轉錄流程時發生錯誤: {e}")
#         return TranscriptionResult(
#             success=False,
#             text="",
#             total_tokens_used=0,
#             error_message=str(e)
#         )
#     finally:
#         if gemini_file:
#             _cleanup_gemini_file(client, gemini_file)
