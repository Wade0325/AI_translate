from pydantic import BaseModel, Field
from typing import List, Optional
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
    model: Optional[str] = Field(None, serialization_alias="model")
    prompt: Optional[str] = None


class ProviderTestRequest(BaseModel):
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


class ProviderTestResponse(BaseModel):
    """用於測試模型介面連接的回應體。"""
    success: bool
    message: str


class WebSocketTranscriptionRequest(BaseModel):
    """用於接收 WebSocket 轉錄請求的資料模型"""
    filename: str
    original_filename: str
    provider: str
    model: str
    api_keys: str
    source_lang: str
    target_lang: Optional[str] = None
    prompt: Optional[str] = None
    original_text: Optional[str] = None
    multi_speaker: bool = False
    service_tier: Optional[str] = None  # 'flex' 啟用 Flex 推論
    session_id: Optional[str] = None  # 同一次 Start 的任務群組 ID


class BatchFileItem(BaseModel):
    """批次處理中的單一檔案項目；per-file 設定為 None 時套用批次層級的 fallback 值"""
    filename: str
    original_filename: str
    file_uid: str
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    prompt: Optional[str] = None
    multi_speaker: Optional[bool] = None


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
    session_id: Optional[str] = None


# ==================== Batch Recovery ====================

class RecoverBatchRequest(BaseModel):
    """POST /batch/{batch_id}/recover 的請求"""
    api_keys: Optional[str] = None


class RecoverFileResult(BaseModel):
    """恢復流程中單一檔案的結果"""
    file_uid: str
    original_filename: str
    status: str  # "COMPLETED" or "FAILED"
    result: Optional[dict] = None


class RecoverBatchResponse(BaseModel):
    """POST /batch/{batch_id}/recover 的回應"""
    batch_id: str
    files: List[RecoverFileResult]


# ==================== Task Page ====================

class BatchTaskFile(BaseModel):
    """Task 頁面中的檔案項目"""
    file_uid: str
    original_filename: str


class BatchTaskResponse(BaseModel):
    """GET /batch/tasks 的回應項目"""
    batch_id: str
    status: str
    file_count: int
    is_alive: Optional[bool] = None
    created_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    files: List[BatchTaskFile]
    session_id: Optional[str] = None


# ==================== History ====================

class HistoryLogResponse(BaseModel):
    """歷史紀錄中的單筆任務回應（只含前端實際顯示/分組會用到的欄位）"""
    task_uuid: str
    request_timestamp: Optional[str] = None
    completed_at: Optional[str] = None
    status: Optional[str] = None
    original_filename: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    model_used: Optional[str] = None
    source_language: Optional[str] = None
    total_tokens: Optional[int] = None
    cost: Optional[float] = None
    error_message: Optional[str] = None
    is_batch: Optional[bool] = None
    session_id: Optional[str] = None
    file_uid: Optional[str] = None
    service_tier_used: Optional[str] = None

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


class DailyUsage(BaseModel):
    """單日用量彙總（僅 COMPLETED 任務）"""
    date: str
    tokens: int
    cost: float
    files: int


class ModelUsage(BaseModel):
    """單一模型的用量彙總（僅 COMPLETED 任務）"""
    model: str
    tokens: int
    cost: float
    files: int


class ModelPriceInfo(BaseModel):
    """模型計費資訊（每百萬 token，美元）"""
    model: str
    input_text: float
    input_audio: float
    output_text: float


class HistoryUsageResponse(BaseModel):
    """GET /history/usage 的回應，供 Dashboard / Billing 頁使用"""
    daily: List[DailyUsage]
    by_model: List[ModelUsage]
    pricing: List[ModelPriceInfo]
