from pydantic import BaseModel
from typing import Optional, List


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
    # 補充說明（轉錄頁填的提示詞），接在提示詞範本後面送出（app.core.default_prompt.build_prompt）
    prompt: Optional[str] = None
    # 設定頁為這個供應商存的提示詞範本，派送時從資料庫讀出；None 時用系統內建的範本
    prompt_template: Optional[str] = None
    user_supplied_text: Optional[str] = None
    target_lang: Optional[str] = None
    multi_speaker: bool = False
    service_tier: Optional[str] = None  # 'flex' 啟用 Flex 推論，其餘視為 Standard
    session_id: Optional[str] = None


class BatchFileItemParams(BaseModel):
    """批次中的單一檔案參數；per-file 設定為 None 時套用批次層級的 fallback 值"""
    file_path: str
    original_filename: str
    file_uid: str
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    prompt: Optional[str] = None  # 這個檔案的補充說明；None 時用批次層級的
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
    # 批次層級的補充說明：補給沒帶自己補充說明的檔案
    prompt: Optional[str] = None
    # 設定頁為這個供應商存的提示詞範本，派送時從資料庫讀出；每個檔案共用，None 時用系統內建的範本
    prompt_template: Optional[str] = None
    client_id: str
    batch_id: str
    session_id: Optional[str] = None
