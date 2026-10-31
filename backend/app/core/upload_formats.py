"""上傳格式與大小：轉錄頁收哪些檔案、最大多大，只寫在這裡（#258）。

前端從 ``GET /api/v1/upload/limits``（:func:`listed`）讀這份清單，不另寫一份；上傳端點用
:func:`check_upload` 檢查每個上傳檔。

- 格式只看副檔名，不看瀏覽器給的 MIME 類型：Windows 上的瀏覽器照登錄檔給 MIME，常常是空的或對不上
  （同一個 .m4a 有 audio/x-m4a、audio/mp4，沒登錄的格式是空字串）；後面的 ffmpeg 與送到 Gemini 的
  MIME 類型也都照副檔名。
- 影片（``kind == "video"``）在上傳時就在本機抽出音訊，影片本身刪掉，之後的任務、保留音檔與供應商
  都只碰得到音訊（#76 的決定，見 :mod:`app.api.upload`）。WebM 列在影片：瀏覽器錄的純音訊 WebM
  一樣抽成 FLAC，沒有壞處。
- 大小上限容得下 2 小時的 WAV：48 kHz 立體聲 16-bit 約 1.38 GB，24-bit 約 2.07 GB，都在 2 GiB 之內。
  畫面寫「2 GB」：以 1024 進位，和 Windows 檔案總管顯示檔案大小的算法相同。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal, Tuple, Union

MAX_UPLOAD_BYTES = 2 * 1024 ** 3
"""上傳檔的大小上限（位元組）：2 GiB，見模組說明。"""

Kind = Literal["audio", "video"]


@dataclass(frozen=True)
class UploadFormat:
    """收的一種檔案格式。"""

    extension: str
    """小寫、帶點的副檔名，例如 ``.mp3``。"""
    label: str
    """畫面上的名稱，例如 ``MP3``。"""
    kind: Kind
    """``audio`` 照原檔轉錄；``video`` 上傳時先在本機抽出音訊。"""


def _formats(kind: Kind, *labels: str) -> Tuple[UploadFormat, ...]:
    return tuple(UploadFormat(f".{label.lower()}", label, kind) for label in labels)


UPLOAD_FORMATS: Tuple[UploadFormat, ...] = (
    *_formats("audio", "MP3", "WAV", "M4A", "FLAC"),
    *_formats("video", "MP4", "MOV", "MKV", "WebM", "AVI", "WMV", "M4V", "MPG", "MPEG"),
)
"""收的格式，依畫面列出的順序：先音檔，再影片，各自從常見的排起。"""

_BY_EXTENSION = {f.extension: f for f in UPLOAD_FORMATS}


@dataclass(frozen=True)
class Rejected:
    """上傳檔不收；``reason`` 是給使用者看的原因，會顯示在轉錄頁的檔案卡上。"""

    reason: str


def check_upload(filename: str, size: int) -> Union[UploadFormat, Rejected]:
    """收不收這個上傳檔：收的話回傳它的格式，不收的話回傳原因。

    ``filename`` 是使用者電腦上的檔名，只看副檔名（大小寫都可以）；``size`` 是位元組數。
    """
    extension = PurePath(filename).suffix.lower()
    upload_format = _BY_EXTENSION.get(extension)
    if upload_format is None:
        shown = extension or "沒有副檔名"
        return Rejected(f"不支援這種檔案格式（{shown}）。可以上傳的音檔：{_labels('audio')}；"
                        f"影片：{_labels('video')}")
    if size <= 0:
        return Rejected("檔案是空的（0 位元組），請確認檔案沒有損壞")
    if size > MAX_UPLOAD_BYTES:
        return Rejected(f"檔案太大（{_size_text(size)}），上限是 {_size_text(MAX_UPLOAD_BYTES)}。"
                        "音檔可以先轉成 FLAC 或 MP3，影片可以先剪成幾段再上傳")
    return upload_format


def listed() -> dict:
    """``GET /api/v1/upload/limits`` 的內容：收的格式（依畫面列出的順序）與大小上限。"""
    return {
        "formats": [{"extension": f.extension, "label": f.label, "kind": f.kind}
                    for f in UPLOAD_FORMATS],
        "max_bytes": MAX_UPLOAD_BYTES,
    }


def _labels(kind: Kind) -> str:
    return "、".join(f.label for f in UPLOAD_FORMATS if f.kind == kind)


def _size_text(size: int) -> str:
    """位元組數寫成 GB（以 1024 進位），無條件進位到一位小數，整數不帶小數，例如 2 GB、2.1 GB：
    剛超過上限的檔案不會寫成和上限一樣大。"""
    tenths = math.ceil(size * 10 / 1024 ** 3)
    return f"{tenths // 10} GB" if tenths % 10 == 0 else f"{tenths / 10:.1f} GB"
