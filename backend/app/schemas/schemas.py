from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from pydantic import ConfigDict


class ProviderConfigRequest(BaseModel):
    """用於接收前端發送的模型介面設定的請求體。"""
    provider: str
    api_keys: List[str] = Field(..., alias="apiKeys")
    model: str = Field(..., alias="model")
    prompt: Optional[str] = None


class ProviderConfigResponse(BaseModel):
    """用於向前端返回模型介面設定的回應體。"""
    provider: str
    api_keys: List[str] = Field(..., serialization_alias="apiKeys")
    model: str = Field(..., serialization_alias="model")
    prompt: Optional[str] = None


class TestProviderRequest(BaseModel):
    """用於測試模型介面連接的請求體。"""
    provider: str
    api_keys: List[str] = Field(..., alias="apiKeys")
    model: str = Field(..., alias="model")


class ModelConfigurationSchema(BaseModel):
    """
    用於在應用程式內部傳遞和操作的模型設定資料結構。
    """
    provider: str
    api_keys: Optional[str] = None
    model: Optional[str] = Field(None, alias="model")
    prompt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ServiceStatus(BaseModel):
    """
    服務層之間通用的狀態回應模型，用於標準化內部方法的返回結果。
    """
    success: bool
    message: Optional[str] = None


class TestProviderResponse(BaseModel):
    """用於測試模型介面連接的回應體。"""
    success: bool
    message: str
    details: Optional[str] = None
    testedInterface: str


class WebSocketTranscriptionRequest(BaseModel):
    """用於接收 WebSocket 轉錄請求的資料模型"""
    filename: str
    original_filename: str
    provider: str
    model: str
    api_keys: str  # 注意：這是單個字符串，不是列表
    source_lang: str
    target_lang: Optional[str] = None  # 新增: 目標語言
    prompt: Optional[str] = None
    original_text: Optional[str] = None  # <--- 新增此行
    multi_speaker: bool = False


class BatchFileItem(BaseModel):
    """批次處理中的單一檔案項目"""
    filename: str
    original_filename: str
    file_uid: str


class WebSocketBatchRequest(BaseModel):
    """用於接收 WebSocket 批次轉錄請求的資料模型"""
    files: List[BatchFileItem]
    provider: str
    model: str
    api_keys: str
    source_lang: str
    target_lang: Optional[str] = None
    prompt: Optional[str] = None
    multi_speaker: bool = False


# ==================== Batch Recovery ====================

class PendingBatchFile(BaseModel):
    """恢復流程中的檔案項目"""
    file_uid: str
    original_filename: str


class PendingBatchResponse(BaseModel):
    """GET /batch/pending 的回應"""
    batch_id: str
    status: str
    created_at: str
    files: List[PendingBatchFile]


class RecoverBatchRequest(BaseModel):
    """POST /batch/{batch_id}/recover 的請求"""
    api_keys: str


class RecoverFileResult(BaseModel):
    """恢復流程中單一檔案的結果"""
    file_uid: str
    original_filename: str
    status: str  # "COMPLETED" or "FAILED"
    result: Optional[dict] = None
    error: Optional[str] = None


class RecoverBatchResponse(BaseModel):
    """POST /batch/{batch_id}/recover 的回應"""
    batch_id: str
    files: List[RecoverFileResult]


# ==================== History ====================

class HistoryLogResponse(BaseModel):
    """歷史紀錄中的單筆任務回應"""
    task_uuid: str
    request_timestamp: Optional[str] = None
    completed_at: Optional[str] = None
    status: Optional[str] = None
    original_filename: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    processing_time_seconds: Optional[float] = None
    model_used: Optional[str] = None
    provider: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    total_tokens: Optional[int] = None
    cost: Optional[float] = None
    error_message: Optional[str] = None
    is_batch: Optional[bool] = None
    batch_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class HistoryListResponse(BaseModel):
    """GET /history 的分頁回應"""
    items: List[HistoryLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class HistoryStatsResponse(BaseModel):
    """GET /history/stats 的回應"""
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    success_rate: float
    total_cost: float
    total_tokens: int
    total_audio_duration_seconds: float
    avg_processing_time_seconds: float
