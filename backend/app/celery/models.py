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
    client_id: str  # 新增: 用於 WebSocket 通訊
    file_uid: str   # 新增: 前端的檔案唯一ID
    prompt: Optional[str] = None
    original_text: Optional[str] = None  # 新增: 前端傳來的文字稿
    target_lang: Optional[str] = None  # 新增: 前端指定的輸出語言
    multi_speaker: bool = False  # 新增: 多人對話模式


class BatchFileItemParams(BaseModel):
    """批次任務中的單一檔案參數"""
    file_path: str
    original_filename: str
    file_uid: str


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
