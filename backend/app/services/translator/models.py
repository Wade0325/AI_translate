import uuid
from pydantic import BaseModel, Field
from typing import List, Dict, Optional


class TranslationRequest(BaseModel):
    """翻譯請求的資料模型"""
    text: str = Field(..., description="要翻譯的文字")
    provider: str = Field(..., description="提供商名稱 (例如 'google')")
    model: str = Field(..., description="模型名稱 (例如 'gemini-1.5-flash')")
    api_key: str = Field(..., description="API 金鑰")
    source_lang: str = Field(..., description="來源語言")
    target_lang: str = Field(..., description="目標語言")
    prompt: Optional[str] = Field(None, description="用於指導翻譯的提示")


class TranslationTaskResult(BaseModel):
    """
    單次翻譯任務的結果
    """
    success: bool = Field(..., description="翻譯是否成功")
    translated_text: str = Field("", description="翻譯後的文字內容")
    input_tokens: int = Field(0, description="輸入 token 數量")
    output_tokens: int = Field(0, description="輸出 token 數量")
    total_tokens_used: int = Field(0, description="使用的 token 總數")


class TranslationResponse(BaseModel):
    """
    完整翻譯服務的回應模型
    """
    task_uuid: uuid.UUID = Field(..., description="此次翻譯任務的唯一標識符")
    translated_text: str = Field(..., description="翻譯結果")
    tokens_used: int = Field(..., description="使用的 token 總數")
    cost: float = Field(..., description="翻譯費用")
    model: str = Field(..., description="使用的模型名稱")
    source_language: str = Field(..., description="來源語言")
    target_language: str = Field(..., description="目標語言")
    processing_time_seconds: float = Field(..., description="處理時間（秒）")
    cost_breakdown: Optional[List[Dict]] = Field(None, description="費用明細")
