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
    api_key: str
    source_lang: str
    original_filename: str
    prompt: Optional[str] = None
    segments_for_remapping: Optional[List[Dict[str, float]]] = None
