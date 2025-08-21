from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class ModelPrice(BaseModel):
    """
    定義了單一模型的 token 價格。
    價格以每 1,000,000 個 token 為單位。
    """
    input_text: float = Field(..., description="每百萬文字輸入 token 的價格")
    input_audio: float = Field(..., description="每百萬音訊輸入 token 的價格")
    output_text: float = Field(..., description="每百萬文字輸出 token 的價格")


class CalculationItem(BaseModel):
    """
    代表一個獨立的計費項目，例如單次 API 呼叫或一個子任務。
    """
    task_name: str = Field(..., description="任務的唯一識別名稱")
    input_tokens: int = Field(0, description="輸入 token 數量")
    output_tokens: int = Field(0, description="輸出 token 數量")
    content_type: str = Field("text", description="內容類型，例如 'text' 或 'audio'")


class PriceCalculationRequest(BaseModel):
    """
    用於計算價格和性能指標的請求模型。
    """
    items: list[CalculationItem] = Field(..., description="計費項目的列表")
    model: str = Field(..., description="使用的模型名稱")
    processing_time_seconds: float | None = Field(
        None, description="任務總處理時間（秒）")
    audio_duration_seconds: float | None = Field(
        None, description="原始音訊總時長（秒）")


class PriceCalculationResponse(BaseModel):
    """
    用於返回計算出的價格和性能指標的回應模型。
    """
    total_tokens: int = Field(..., description="所有項目加總的總 token 數量")
    cost: float = Field(..., description="計算出的總費用")
    model: str = Field(..., description="用於計價的模型名稱")
    # 可選：提供成本細目
    breakdown: list[dict] | None = Field(None, description="每個計費項目的成本細目")
    processing_time_seconds: float | None = Field(
        None, description="任務總處理時間（秒）")
    audio_duration_seconds: float | None = Field(
        None, description="原始音訊總時長（秒）")
