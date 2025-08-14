import uuid
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from pathlib import Path


class TranscriptionRequest(BaseModel):
    """轉錄請求的資料模型"""
    file_path: str
    model: str
    source_lang: str
    original_filename: Optional[str] = None
    segments_for_remapping: Optional[List[Dict[str, float]]] = None


class TranscriptionTaskResult(BaseModel):
    """
    單次轉錄任務的結果
    """
    success: bool = Field(..., description="轉錄是否成功")
    text: str = Field("", description="轉錄的文字內容")
    input_tokens: int = Field(0, description="輸入 token 數量")
    output_tokens: int = Field(0, description="輸出 token 數量")
    total_tokens_used: int = Field(0, description="使用的 token 總數")


class TranscriptionResponse(BaseModel):
    """
    完整轉錄服務的回應模型
    """
    task_uuid: uuid.UUID = Field(..., description="此次轉錄任務的唯一標識符")
    transcripts: Dict[str, Any] = Field(..., description="各種格式的轉錄結果")
    tokens_used: int = Field(..., description="使用的 token 總數")
    cost: float = Field(..., description="轉錄費用")
    model: str = Field(..., description="使用的模型名稱")
    source_language: str = Field(..., description="來源語言")
    processing_time_seconds: float = Field(..., description="處理時間（秒）")
    audio_duration_seconds: float = Field(..., description="音訊總時長（秒）")
    cost_breakdown: Optional[List[Dict]] = Field(None, description="費用明細")


class ModelConfiguration(BaseModel):
    """
    模型配置資訊
    """
    api_key: str = Field(..., description="API 金鑰")
    model_name: str = Field(..., description="Gemini 模型名稱")
    prompt: str = Field(..., description="轉錄提示詞")
