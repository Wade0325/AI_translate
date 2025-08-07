from pydantic import BaseModel, Field
from typing import List, Optional, Tuple


class SpeechSegment(BaseModel):
    """
    語音片段資訊
    """
    start: float = Field(..., description="片段開始時間（秒）")
    end: float = Field(..., description="片段結束時間（秒）")

    @property
    def duration(self) -> float:
        """片段時長"""
        return self.end - self.start


class VADProcessRequest(BaseModel):
    """
    VAD 處理請求
    """
    audio_path: str = Field(..., description="音訊檔案路徑")
    output_dir: str = Field(..., description="輸出目錄路徑")


class SpeechExtractionResult(BaseModel):
    """
    語音提取結果
    """
    success: bool = Field(..., description="是否成功")
    speech_only_path: Optional[str] = Field(None, description="純語音檔案路徑")
    segments: List[SpeechSegment] = Field(
        default_factory=list, description="語音片段列表")
    total_speech_duration: float = Field(0.0, description="總語音時長（秒）")
    total_duration: float = Field(0.0, description="原始音訊總時長（秒）")

    @property
    def speech_ratio(self) -> float:
        """語音佔比"""
        if self.total_duration > 0:
            return self.total_speech_duration / self.total_duration
        return 0.0


class AudioSplitRequest(BaseModel):
    """
    音訊分割請求
    """
    audio_path: str = Field(..., description="音訊檔案路徑")
    output_dir: str = Field(..., description="輸出目錄路徑")
    min_silence_duration: float = Field(1.0, description="最小靜音時長（秒）")


class AudioSplitResult(BaseModel):
    """
    音訊分割結果
    """
    success: bool = Field(..., description="是否成功")
    part1_path: Optional[str] = Field(None, description="第一部分檔案路徑")
    part2_path: Optional[str] = Field(None, description="第二部分檔案路徑")
    split_point: Optional[float] = Field(None, description="分割點時間（秒）")
    error_message: Optional[str] = Field(None, description="錯誤訊息")
