import uuid
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any

from app.core.error_codes import ErrorCode
from app.core.speaker_count import SpeakerCount


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
    covered_until: Optional[float] = Field(
        default=None,
        description="轉接器擔保轉錄到哪一秒（送進轉接器的那段音檔的時間軸）：模型可能提早停止輸出時"
                    "（例如本機的 MOSS 用完生成預算或輸出結尾不完整），之後的內容可能"
                    "沒有轉錄到；模型在最後一個片段之後還轉了一段、卻沒有文字時（例如 MOSS 在長段無聲處"
                    "只輸出說話者標籤，#325），是它轉到的地方。都不是時是 None。分段轉錄照它決定要不要接續"
                    "（app.services.continuation），只在轉接器回傳與分段轉錄內部使用，不記進任務紀錄。",
    )
    truncated: bool = Field(
        default=False,
        description="轉接器的輸出被截斷（例如本機的 MOSS 用完生成預算或輸出結尾不完整）：covered_until 之後"
                    "幾乎一定還有沒轉到的話，掉尾的檢查不等一分鐘的聲音（app.services.tail_loss，#326）。"
                    "最後一段沒有文字（#325）不算。只在轉接器回傳與分段轉錄內部使用，不記進任務紀錄。",
    )
    model_versions: List[str] = Field(
        default_factory=list,
        description="回應寫明的模型版本（Gemini 回應的 model_version），依出現的順序、不重複；分段轉錄的"
                    "各段是分開的請求，版本不同時都列出。沒寫的供應商（本機）是空的。任務完成時補記進轉錄"
                    "環境（#343）。",
    )
    tail_loss_from: Optional[float] = Field(
        default=None,
        description="可能掉尾的起點（原音檔的時間軸，秒）：從這裡起可能有內容沒有轉錄到，例如供應商"
                    "提早停止輸出（app.services.tail_loss）；沒有掉尾時是 None。分段轉錄與批次放回"
                    "原音檔的時間軸時寫，任務完成時記進任務紀錄。",
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
        ..., description="這份輸出裡有幾位說話者，結果頁顯示它：整份當成同一位說話者時是 1，否則是不同的"
                         "說話者編號有幾個，行都沒有說話者編號時算一位；沒有任何一行時是 0"
                         "（app.services.output_format.speakers_in_output）")
    selected_speaker_count: Optional[SpeakerCount] = Field(
        default=None,
        description="使用者選的說話者人數（\"auto\" 或 1 到 8）；人數做出來之前的任務是 None。選了 2 到 8 人、"
                    "和 speaker_count 不同時，結果頁多一行提醒（#351 第 4 點）")
    tail_loss_from_seconds: Optional[float] = Field(
        default=None,
        description="可能掉尾的起點（原音檔的秒數）：檔案卡、結果頁與 History 照它寫「從 mm:ss 起"
                    "可能沒有轉錄到」；沒有掉尾時是 None（app.services.tail_loss）")
