"""哪些任務能校正（#347，畫面的共同規則見 #345 第 1 節）。

能校正的任務：已完成、有片段，而且不是翻譯的任務。History 的清單照這裡決定要不要給「校正」的入口；
直接開校正頁的網址時，畫面照 :func:`reason` 回的原因寫出一句說明。
"""

from enum import StrEnum
from typing import Optional

from app.core.task_status import TaskStatus


class Uncorrectable(StrEnum):
    """不能校正的原因。字串會送到前端（``frontend/src/utils/correction.js`` 照它寫說明），不要改既有的值。"""

    NOT_COMPLETED = "not_completed"
    """還在轉錄、失敗或已取消：只有完成的任務有可以校正的轉錄結果。"""
    TRANSLATION = "translation"
    """翻譯的任務：v0.2 不校正翻譯結果（#25 不做的事）。"""
    NO_SEGMENTS = "no_segments"
    """沒有片段：片段上線前的任務、#110 之前的 Gemini 任務、#115 之前批次裡的任務只有凍結的原始轉錄副本。"""


def is_translation(source_language: Optional[str], target_language: Optional[str]) -> bool:
    """有目標語言而且和來源不同，就是翻譯的任務；和提示詞判斷要不要翻譯的規則相同
    （``app.core.default_prompt.build_prompt``）。"""
    return bool(target_language) and target_language != source_language


def reason(
    status: Optional[str],
    source_language: Optional[str],
    target_language: Optional[str],
    has_segments: bool,
) -> Optional[Uncorrectable]:
    """這個任務為什麼不能校正；能校正時是 None。

    原因不只一個時回最根本的那個：沒完成的任務談不上有沒有片段，翻譯的任務就算有片段也不能校正。
    """
    if status != TaskStatus.COMPLETED:
        return Uncorrectable.NOT_COMPLETED
    if is_translation(source_language, target_language):
        return Uncorrectable.TRANSLATION
    if not has_segments:
        return Uncorrectable.NO_SEGMENTS
    return None
