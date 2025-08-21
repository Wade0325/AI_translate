# from pydantic import BaseModel, Field
# from typing import Optional


# class GeminiConfig(BaseModel):
#     """
#     Gemini API 的設定模型
#     """
#     api_key: str = Field(..., description="Google AI Studio API 金鑰")


# class TranscriptionResult(BaseModel):
#     """
#     轉錄結果的模型
#     """
#     success: bool
#     text: str
#     input_tokens: int = 0
#     output_tokens: int = 0
#     total_tokens_used: int
#     error_message: Optional[str] = None
