from pydantic import BaseModel


class SubtitleFormats(BaseModel):
    """
    一個 Pydantic 模型，用於存放所有轉換後的字幕格式。
    """
    lrc: str
    srt: str
    vtt: str
    txt: str
