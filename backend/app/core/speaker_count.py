"""說話者人數（GLOSSARY「說話者人數」，#351）：使用者在轉錄前替一個任務選的說話者數目。

照模型判斷（:data:`AUTO`，預設），或 1 到 :data:`MAX` 人；超過 8 人選照模型判斷。選 1 人時整份
音檔當成同一位說話者。人數是轉錄時用的，轉錄完不能改成別的數字。

人數影響兩件事，各在一處：

* Gemini 的提示詞（:mod:`app.core.default_prompt`）：照模型判斷時請它有多位說話者才標，2 到 8 人時
  寫明有幾位，1 人時不請它分。本機的模型不吃提示詞，照舊自己分說話者、存下說話者編號（ADR-0007）；
  選了 2 到 8 人（:func:`several_count`）、分出的比所選多時，轉錄完照聲音收斂到所選人數（#377，
  :func:`app.services.speaker_alignment.converge`），存的是收斂後的編號。
* 輸出帶不帶說話者標記（:func:`app.services.output_format.speaker_labels`）。

請求、任務參數與完成時送給畫面的結果寫成 ``"auto"`` 或 1 到 8 的整數。任務紀錄存成字串（見
:func:`to_column`），人數做出來之前的任務是 NULL，照當時 Multi-Speaker 開關的規則。
"""

from typing import Annotated, Final, Literal, Optional, Union, cast

from pydantic import Field

AUTO: Final = "auto"
"""照模型判斷。"""

MAX: Final = 8
"""選單上最多的人數；更多人的音檔選照模型判斷。"""

SpeakerCount = Union[Literal["auto"], Annotated[int, Field(strict=True, ge=1, le=MAX)]]
"""照模型判斷（``"auto"``），或 1 到 8 人。

當成 pydantic 欄位的型別時，``"2"`` 這種字串與 ``true`` 都不收：嚴格的整數才不會把 ``true`` 當成 1 人。
"""

DEFAULT: Final[SpeakerCount] = AUTO
"""沒選時的人數：照模型判斷（#351 第 1 點）。"""


def is_single(speaker_count: SpeakerCount) -> bool:
    """選了 1 人：整份音檔當成同一位說話者。"""
    return speaker_count == 1


def several_count(speaker_count: SpeakerCount) -> Optional[int]:
    """選了 2 到 8 人時是那個人數；照模型判斷與 1 人是 None。"""
    return speaker_count if isinstance(speaker_count, int) and speaker_count >= 2 else None


def to_column(speaker_count: Optional[SpeakerCount]) -> Optional[str]:
    """寫進任務紀錄的值：``"auto"``，或人數的數字（``"2"``）；接回人數做出來之前的任務時（None）照舊是 NULL。"""
    return None if speaker_count is None else str(speaker_count)


def from_column(value: Optional[str]) -> Optional[SpeakerCount]:
    """任務紀錄存的值換回人數；人數做出來之前的任務（NULL）是 None。

    認不得的值（只有手動改過資料庫才會有）當成照模型判斷，不讓下載或結果頁出錯。
    """
    if value is None:
        return None
    if value.isdigit() and 1 <= int(value) <= MAX:
        return int(value)
    return cast(SpeakerCount, AUTO)
