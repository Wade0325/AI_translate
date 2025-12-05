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
    segments_for_remapping: Optional[List[Dict[str, float]]] = None
    target_lang: Optional[str] = None  # 新增: 前端指定的輸出語言
