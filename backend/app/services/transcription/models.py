import uuid
from pydantic import BaseModel, Field
from typing import Dict, Optional, Any


class TranscriptionTaskResult(BaseModel):
    """
    單次轉錄任務的結果
    """
    success: bool = Field(..., description="轉錄是否成功")
    text: str = Field("", description="轉錄的文字內容")
    input_tokens: int = Field(0, description="輸入 token 數量")
    output_tokens: int = Field(0, description="輸出 token 數量")
    total_tokens: int = Field(0, description="使用的 token 總數")
    service_tier_used: Optional[str] = Field(
        None, description="實際採用的 service tier：'flex' 或 'standard'（None 表示 standard）"
    )


class TranscriptionResponse(BaseModel):
    """
    完整轉錄結果（WS 推送與 BatchJob.results_json 儲存的 payload）。
    僅保留前端實際消費的欄位；細部費用/耗時另存於 transcription_logs。
    """
    task_uuid: uuid.UUID = Field(..., description="此次轉錄任務的唯一標識符")
    transcripts: Dict[str, Any] = Field(..., description="各種格式的轉錄結果")
    tokens_used: int = Field(..., description="使用的 token 總數")
    cost: float = Field(..., description="轉錄費用")
    model: str = Field(..., description="使用的模型名稱")
    source_language: str = Field(..., description="來源語言")
    audio_duration_seconds: float = Field(..., description="音訊總時長（秒）")
