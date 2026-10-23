"""標準答案與轉錄結果的讀取。只讀不寫：標準答案是人工聽打的，壞了沒有備份以外的辦法救回。

標準答案的格式（一個檔案是評測集裡的一段連續音訊）：

    # demo_A  01:00.00-02:30.50
    # A=主持人 B=來賓
    [01:02.10] A: 今天先介紹設定檔。
    ~B: 嗯
    [01:15.40] B: 那個 [聽不清] 要放在哪裡？

  * 第一個符合「# 名稱 起-訖」的註解行是表頭，計分只看這段時間內的轉錄結果
  * 行首的時間戳可有可無，只是給人定位用，計分不使用
  * ``~`` 開頭＝對方講話時插進來的附和，可單獨排除計分
  * ``[聽不清]`` 是聽不出來的地方，那個位置怎麼轉錄都不計分
  * ``A?:`` 與 ``(?)`` 是草稿標記，正式的標準答案不該有；沒有允許草稿時拒絕讀取

轉錄結果讀的是 LRC（見 :mod:`.lrc`），依片段時間範圍裁切。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import lrc

# 表頭：名稱 + 時間範圍
HEADER_RE = re.compile(
    r"^#\s*(?P<name>[\w.-]+)\s+(?P<start>\d+:\d+(?:\.\d+)?)\s*-\s*(?P<end>\d+:\d+(?:\.\d+)?)")
# 對話行：可選時間戳 + 可選 ~ + 說話者代號 + 可選 ? + 冒號 + 文字
UTT_RE = re.compile(
    r"^(?:\[(?P<ts>[\d:.]+)\]\s*)?(?P<ov>~)?\s*(?P<spk>[A-Za-z][\w-]*)(?P<doubt>\?)?\s*[:：]\s*(?P<text>.*)$")

UNCLEAR = "[聽不清]"
DOUBT_RE = re.compile(r"\(\?[^)]*\)")

# 轉錄結果裡沒有說話者標記的行，全部算這一位說話者
UNLABELED_SPEAKER = "S?"


class ReferenceSetError(ValueError):
    """標準答案讀不進來；訊息寫明是哪個檔案、該怎麼改。"""


@dataclass
class Utterance:
    """一句話。speaker 是代號（標準答案為 A/B，轉錄結果為 S0/S1）。"""

    speaker: str
    text: str
    overlap: bool = False


@dataclass
class Excerpt:
    """評測集裡的一段連續音訊，連同它的標準答案。"""

    name: str
    start: float
    end: float
    utterances: list[Utterance] = field(default_factory=list)
    path: Path | None = None
    draft_marks: int = 0


def _ts_to_sec(s: str) -> float:
    parts = s.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"無法解析時間：{s}")


def read_reference(path: str | Path, allow_draft: bool = False) -> Excerpt:
    """讀一份標準答案。草稿標記（(?) 或 A?:）存在且未允許時拒絕。"""
    p = Path(path)
    raw = p.read_text(encoding="utf-8").splitlines()

    name, start, end = p.stem, None, None
    for line in raw:
        m = HEADER_RE.match(line.strip())
        if m:
            name = m.group("name")
            start = _ts_to_sec(m.group("start"))
            end = _ts_to_sec(m.group("end"))
            break
    if start is None or end is None:
        raise ReferenceSetError(f"{p.name} 缺少表頭時間範圍（# 名稱 mm:ss.xx-mm:ss.xx）")

    utts: list[Utterance] = []
    marks = 0
    for line in raw:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = UTT_RE.match(s)
        if not m:
            raise ReferenceSetError(f"{p.name} 無法解析此行（缺少「代號:」？）：{s[:60]}")
        text = m.group("text").strip()
        if m.group("doubt"):
            marks += 1
        marks += len(DOUBT_RE.findall(text))
        if not text:
            continue
        utts.append(Utterance(speaker=m.group("spk"), text=text,
                              overlap=bool(m.group("ov"))))

    if marks and not allow_draft:
        raise ReferenceSetError(
            f"{p.name} 還有 {marks} 處草稿標記（(?) 或 代號?:）未確認。\n"
            f"確認完請刪掉標記；若只是想先試跑工具，加 --allow-draft。")

    return Excerpt(name=name, start=start, end=end, utterances=utts, path=p,
                   draft_marks=marks)


def clip_hyp(lrc_path: str | Path, start: float, end: float) -> list[Utterance]:
    """讀轉錄結果的 LRC，取出落在 [start, end) 的行。"""
    return [
        Utterance(speaker=line.speaker or UNLABELED_SPEAKER, text=line.text)
        for line in lrc.read(lrc_path).lines
        if start <= line.seconds < end
    ]


def hyp_warnings(lrc_path: str | Path) -> list[str]:
    """轉錄結果裡會影響計分、但不至於讀不進來的地方，給人看的說明。"""
    text = lrc.read(lrc_path)
    out = []
    unlabeled = sum(1 for line in text.lines if line.speaker is None)
    if unlabeled:
        out.append(f"{unlabeled} 行沒有說話者標記，全部算同一位說話者（{UNLABELED_SPEAKER}）")
    if text.skipped:
        out.append(f"{len(text.skipped)} 行沒有時間戳，不計分（第一行：{text.skipped[0][:40]}）")
    return out
