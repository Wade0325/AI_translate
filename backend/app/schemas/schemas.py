from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID
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
    """用於測試模型介面連接的請求體。api_keys 只能是設定頁顯示的遮罩值，明文會被拒收（#16 Q8b）。"""
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
    api_keys: str = ""  # 可省略或只帶遮罩值，後端用資料庫裡的金鑰；明文會被拒收（#16 Q8b）
    source_lang: str
    target_lang: Optional[str] = None
    prompt: Optional[str] = None  # 補充說明：接在設定頁存的提示詞範本後面送出（#144）
    user_supplied_text: Optional[str] = None
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
    api_keys: str = ""  # 可省略或只帶遮罩值，後端用資料庫裡的金鑰；明文會被拒收（#16 Q8b）
    source_lang: str
    target_lang: Optional[str] = None
    prompt: Optional[str] = None  # 補充說明：補給沒帶自己的檔案，一樣接在提示詞範本後面
    multi_speaker: bool = False
    session_id: Optional[str] = None


# ==================== Batch Recovery ====================

class RecoverBatchRequest(BaseModel):
    """POST /batch/{batch_id}/recover 的請求；api_keys 省略或只帶遮罩值時用資料庫裡的金鑰，明文會被拒收"""
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
    recoverable: bool = False  # 任務頁要不要給「恢復」（app.tasks.batch_core.recoverable）


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
    error_code: Optional[str] = None  # 失敗的錯誤碼（app.core.error_codes）；畫面照它顯示原因與下一步
    error_message: Optional[str] = None  # 失敗時是錯誤碼的細節，取消時是取消的說明
    is_batch: Optional[bool] = None
    session_id: Optional[str] = None
    file_uid: Optional[str] = None
    service_tier_used: Optional[str] = None
    # 可能掉尾的起點（原音檔的秒數，app.services.tail_loss）；畫面照它寫「從 mm:ss 起可能沒有轉錄到」
    tail_loss_from_seconds: Optional[float] = None
    # 能不能校正（app.services.correctability）：History 照它決定要不要給「校正」的入口（#347）
    correctable: bool = False
    # 有沒有校正紀錄（改回原樣的也算）：History 的下載選單照它決定要不要多一組「原始轉錄」（#346）
    has_corrections: bool = False

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
    """單日用量彙總：token 與費用含失敗與取消的任務記下的用量，檔案數只算完成的"""
    date: str
    tokens: int
    cost: float
    files: int


class ModelUsage(BaseModel):
    """單一模型的用量彙總：token 與費用含失敗與取消的任務記下的用量，檔案數只算完成的"""
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
    """GET /history/usage 的回應，供 Billing 頁與轉錄頁的費用估算使用"""
    daily: List[DailyUsage]
    by_model: List[ModelUsage]
    pricing: List[ModelPriceInfo]


class TranscriptWord(BaseModel):
    """逐字時間戳（去靜音前的時間軸，秒）"""
    text: Optional[str] = None
    start: float
    end: Optional[float] = None


class TranscriptSegmentResponse(BaseModel):
    """一個轉錄片段：``text`` 與 ``speaker`` 是校正後版本，另外帶著原始轉錄（#341，算法見
    ``app.repositories.correction_repository``）。text_alt 是另一個模型對同一段的結果，供分歧標示用。"""
    seg_key: str
    seq: int
    start: float
    end: Optional[float] = None
    speaker: Optional[str] = None
    """校正後版本的說話者；沒有說話者是 None。"""
    text: str = ""
    """校正後版本的文字；刪掉的片段是空字串。"""
    original_speaker: Optional[str] = None
    original_text: str = ""
    corrected: bool = False
    """文字或說話者和原始轉錄不同。"""
    deleted: bool = False
    """校正後的文字是空的（刪掉的片段，下載的校正後版本裡沒有它）。"""
    deleted_text: Optional[str] = None
    """使用者刪掉的片段，刪掉之前的文字：校正頁的「還原」把它送回去（#348）。沒刪掉、或原始轉錄就沒有文字的
    片段是 None。"""
    has_correction_records: bool = False
    """有校正紀錄；改回和原始轉錄相同之後仍是 True。"""
    text_alt: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[float] = None
    review_state: Optional[str] = None
    """確認狀態：verified（已確認）、flagged（待查）或 None。"""
    words: Optional[List[TranscriptWord]] = None


class SegmentCorrectionRequest(BaseModel):
    """PATCH /transcripts/{task_uuid}/segments/{seg_key}：帶 text、speaker、review_state 其中一個或多個，
    沒帶的不改。text 是空的（去掉前後的空白之後）就是刪掉這個片段；speaker 與 review_state 的 null 是清除。
    各欄位的規則在 ``app.api.transcripts`` 檢查，錯誤時回一句中文的 detail。"""
    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = None
    speaker: Optional[str] = None
    review_state: Optional[str] = None


class SegmentCorrectionResponse(BaseModel):
    """改一個片段的結果：這個片段的新內容，與這次記下的校正紀錄共用的操作編號（復原時用）。
    沒有記任何一筆（只改了確認狀態，或內容和現在的相同）時沒有操作編號。"""
    operation_id: Optional[UUID] = None
    segment: TranscriptSegmentResponse


class UndoOperationResponse(BaseModel):
    """復原一次操作的結果。"""
    restored: int
    """還原了幾筆校正紀錄。"""
    skipped: int
    """略過幾筆：那次操作之後又被改過。"""
    operation_id: Optional[UUID] = None
    """這次復原自己的操作編號（復原也可以再復原）；一筆都沒有還原時是 None。"""
    segments: List[TranscriptSegmentResponse] = []
    """那次操作改到的片段的新內容，還原的與略過的都在內。"""


class CorrectionRecordResponse(BaseModel):
    """一筆校正紀錄（校正的歷程，#355）。"""
    id: int
    """編號：同一個任務裡的先後看它，不看時間。"""
    field: str
    """改了什麼：text（文字）或 speaker（說話者）。"""
    old_value: Optional[str] = None
    """改前。文字的「沒有」是空字串（刪掉的片段），說話者的「沒有」是 None。"""
    new_value: Optional[str] = None
    """改後；規則和改前相同。回到這一筆就是把這一項改回它。"""
    operation_id: UUID
    created_at: Optional[str] = None
    """什麼時候改的：伺服器的本地時間（ISO 8601，到秒，不帶時區）。"""
    operation_record_count: int
    """那次操作一共記了幾筆。"""
    operation_segment_count: int
    """那次操作改到幾個片段；超過一個就是一次改很多個片段的操作，可以整批復原。"""


class SegmentCorrectionHistoryResponse(BaseModel):
    """GET /transcripts/{task_uuid}/segments/{seg_key}/correction-records：一個片段的歷程。

    records 是這個片段的文字與說話者的校正紀錄，依編號排序（舊的在前）；說話者名稱的紀錄（對象是說話者）與
    確認狀態（不是校正）不在裡面。原始轉錄是歷程最早的一版，一起帶著。"""
    seg_key: str
    original_text: str = ""
    original_speaker: Optional[str] = None
    records: List[CorrectionRecordResponse] = []


class TranscriptResponse(BaseModel):
    """GET /transcripts/{task_uuid} 的回應，供校正介面使用"""
    task_uuid: str
    status: Optional[str] = None
    original_filename: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    audio_available: bool = False
    # 能不能校正，不能時的原因（app.services.correctability.Uncorrectable 的值）：直接開校正頁的網址時，
    # 畫面照原因寫出一句說明（#347）。schemas 不依賴 services，所以型別寫 str
    correctable: bool = False
    uncorrectable_reason: Optional[str] = None
    segment_count: int = 0
    segments: List[TranscriptSegmentResponse] = []


class RetainedAudioResponse(BaseModel):
    """保留音檔的設定與目前的用量（#231 Q1）。天數與開關只能用環境變數改。"""
    enabled: bool
    retention_days: int
    """超過這個天數的在下次啟動時刪除；0 是不自動刪除。"""
    folder: str
    file_count: int
    total_bytes: int


class LocalDataResponse(BaseModel):
    """GET /local-data：設定頁「資料與隱私」顯示的內容（#231 Q1、Q7）"""
    data_folder: Optional[str] = None
    """免安裝版放所有資料的資料夾；Docker 模式沒有單一的資料夾，是 None。"""
    retained_audio: RetainedAudioResponse


class DeleteRetainedAudioResponse(BaseModel):
    """DELETE /local-data/retained-audio：刪掉與刪不掉（例如正被開著）的保留音檔數量。"""
    deleted: int
    failed: int
