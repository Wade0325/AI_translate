from pydantic import BaseModel, Field
from typing import Optional


class AudioSplitRequest(BaseModel):
    """
    音訊分割請求
    """
    audio_path: str = Field(..., description="音訊檔案路徑")
    output_dir: str = Field(..., description="輸出目錄路徑")
    min_silence_duration: float = Field(default=1.0, description="最小靜音時長（秒）")


class AudioSplitResult(BaseModel):
    """
    音訊分割結果
    """
    success: bool = Field(..., description="是否成功")
    part1_path: Optional[str] = Field(default=None, description="第一部分檔案路徑")
    part2_path: Optional[str] = Field(default=None, description="第二部分檔案路徑")
    split_point: Optional[float] = Field(default=None, description="分割點時間（秒）")
    error_message: Optional[str] = Field(default=None, description="錯誤訊息")
