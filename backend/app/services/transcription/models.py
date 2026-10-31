import uuid
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any

from app.core.error_codes import ErrorCode


class TranscriptionTaskResult(BaseModel):
    """
    單次轉錄任務的結果
    """
    success: bool = Field(..., description="轉錄是否成功")
    text: str = Field(
        default="",
        description="給使用者看的說明：失敗時是原因；成功但沒有片段時是為什麼沒有（例如 Gemini "
                    "的回應沒有任何帶時間戳的文字），整個任務都沒有片段時任務生命週期拿它回報失敗。"
                    "有片段時是空的：轉錄結果就是 segments。",
    )
    error_code: Optional[ErrorCode] = Field(
        default=None,
        description="失敗、或沒有片段時的錯誤碼（app.core.error_codes），由寫下 text 的地方一起寫；"
                    "沒寫時任務生命週期把失敗當成 INTERNAL、沒有片段當成 NO_TRANSCRIPT。",
    )
    # 預設值寫成 default=：寫成第一個位置參數時，型別檢查看不出欄位有預設值
    input_tokens: int = Field(default=0, description="輸入 token 數量")
    output_tokens: int = Field(default=0, description="輸出 token 數量")
    total_tokens: int = Field(default=0, description="使用的 token 總數")
    service_tier_used: Optional[str] = Field(
        default=None, description="實際採用的 service tier：'flex' 或 'standard'（None 表示 standard）"
    )
    segments: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="轉錄結果的片段：說話者編號、開始與結束時間、文字，本機另有逐字時間。"
                    "Gemini 的片段只有 Gemini 寫明結束的才有結束時間，沒有說話者代號的行也沒有"
                    "說話者編號。"
                    "供應商回傳時的時間軸是送進去的那段音檔，分段轉錄負責平移與還原回原音檔；"
                    "四種輸出格式都從這裡產生。",
    )


class TranscriptionResponse(BaseModel):
    """
    完整轉錄結果（任務完成時 WS 推送的 payload；批次取回結果時從任務紀錄與片段重新產生，
    見 app.tasks.lifecycle.completed_result）。
    僅保留前端實際消費的欄位；細部費用/耗時另存於 transcription_logs。
    """
    task_uuid: uuid.UUID = Field(..., description="此次轉錄任務的唯一標識符")
    transcripts: Dict[str, Any] = Field(..., description="各種格式的轉錄結果")
    tokens_used: int = Field(..., description="使用的 token 總數")
    cost: float = Field(..., description="轉錄費用")
    model: str = Field(..., description="使用的模型名稱")
    source_language: str = Field(..., description="來源語言")
    audio_duration_seconds: float = Field(..., description="音訊總時長（秒）")
    speaker_count: int = Field(
        ..., description="片段裡出現幾個不同的說話者編號，結果頁顯示的人數；沒有片段帶說話者編號時"
                         "（例如 Gemini 沒寫說話者代號）是 0")
