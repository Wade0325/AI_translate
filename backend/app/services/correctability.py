"""哪些任務能校正（#347，畫面的共同規則見 #345 第 1 節）。

能校正的任務：已完成、有片段，而且不是轉錄並翻譯的任務。History 的清單照這裡決定要不要給「校正」的
入口；直接開校正頁的網址時，畫面照 :func:`reason` 回的原因寫出一句說明。
"""

from enum import StrEnum
from typing import Optional, cast

from app.core.task_status import TaskStatus
from app.database.models import TranscriptionLog


class Uncorrectable(StrEnum):
    """不能校正的原因。字串會送到前端（``frontend/src/utils/correction.js`` 照它寫說明），不要改既有的值。"""

    NOT_COMPLETED = "not_completed"
    """還在轉錄、失敗或已取消：只有完成的任務有可以校正的轉錄結果。"""
    WITH_TRANSLATION = "with_translation"
    """轉錄並翻譯的任務：v0.2 不校正翻譯過的結果（#25 不做的事）。"""
    NO_SEGMENTS = "no_segments"
    """沒有片段：片段上線前的任務、#110 之前的 Gemini 任務、#115 之前批次裡的任務只有凍結的原始轉錄副本。"""


def with_translation(source_language: Optional[str], target_language: Optional[str]) -> bool:
    """轉錄並翻譯的任務：有目標語言而且和來源不同。和提示詞判斷要不要加翻譯指令的規則相同
    （``app.core.default_prompt.build_prompt``）；轉錄頁不送目標語言，只有直接呼叫 API 的任務會是。"""
    return bool(target_language) and target_language != source_language


def reason(log: TranscriptionLog, *, has_segments: bool) -> Optional[Uncorrectable]:
    """這個任務為什麼不能校正；能校正時是 None。

    原因不只一個時回最根本的那個：沒完成的任務談不上有沒有片段，轉錄並翻譯的任務就算有片段也不能校正。
    """
    if cast(Optional[str], log.status) != TaskStatus.COMPLETED:
        return Uncorrectable.NOT_COMPLETED
    if with_translation(cast(Optional[str], log.source_language), cast(Optional[str], log.target_language)):
        return Uncorrectable.WITH_TRANSLATION
    if not has_segments:
        return Uncorrectable.NO_SEGMENTS
    return None
