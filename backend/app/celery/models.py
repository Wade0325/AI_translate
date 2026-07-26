from pydantic import BaseModel
from typing import Optional, List, Dict


class TranscriptionTaskParams(BaseModel):
    """
    定義非同步轉錄任務所需的所有參數。
    這個模型將在 API 層被序列化，然後在 Celery worker 中被反序列化。
    """
    file_path: str
    provider: str
    model: str
    api_keys: str
    source_lang: str
    original_filename: str
    client_id: str
    file_uid: str
    prompt: Optional[str] = None
    original_text: Optional[str] = None
    target_lang: Optional[str] = None
    multi_speaker: bool = False
    service_tier: Optional[str] = None  # 'flex' 啟用 Flex 推論，其餘視為 Standard
    session_id: Optional[str] = None


class BatchFileItemParams(BaseModel):
    """批次任務中的單一檔案參數；per-file 設定為 None 時套用批次層級的 fallback 值"""
    file_path: str
    original_filename: str
    file_uid: str
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    prompt: Optional[str] = None
    multi_speaker: Optional[bool] = None


class BatchTranscriptionTaskParams(BaseModel):
    """
    定義批次轉錄任務所需的所有參數。
    使用 Gemini Batch API 以 50% 的費用非同步處理多個檔案。
    """
    files: List[BatchFileItemParams]
    provider: str
    model: str
    api_keys: str
    source_lang: str
    target_lang: Optional[str] = None
    multi_speaker: bool = False
    prompt: Optional[str] = None
    client_id: str
    batch_id: str
    session_id: Optional[str] = None
