"""接續模組：分段轉錄的某一段提早停止輸出時，從停下的地方附近再轉錄一次並接回，以免掉尾（#94）。

本機的 MOSS 轉長音檔時可能約輸出 16k token 就自己停下（實測日文 ASMR 約 50 分鐘、中文對話約 45 分鐘；
朗讀的 61 分鐘音檔則一次轉完），片段照樣回來，只是少了後面。接續的迴圈在 :mod:`app.services.chunked_transcription`（它送音檔進轉接器、
切音檔、清暫存檔），模型能力的 ``continuation`` 開著才接續；這裡是不碰音檔的規則，時間軸都是那一段
送進轉接器的音檔。

1. 要不要接續，分兩層判斷：
   - 轉接器回報擔保轉錄到哪一秒（``covered_until``）：MOSS 用完生成預算或輸出結尾不完整（輸出被截斷）
     時回報，但它不知道後面還有沒有語音。MOSS 在約 16k token 自己停下時輸出是完整的，不回報；最後幾段
     只有說話者標籤、被丟掉時（#325）照樣回報，擔保點是那幾段的結束。
   - 分段轉錄照掉尾的規則（:mod:`app.services.tail_loss`）看語音視圖：從停下的地方（有回報時是
     ``covered_until``，沒有時是最後一個片段的結束）到這一段的結尾，扣掉靜音還有至少
     ``TAIL_LOSS_MIN_SECONDS`` 秒的聲音才接續。沒有回報也照樣看，抓得到模型自己不知道停早了的情況，
     例如在約 16k token 自己停下，或長段非語音之後就結束。
2. 從哪裡接續（:func:`resume_point`）：停下的地方往前重疊 ``CONTINUATION_OVERLAP_SECONDS`` 秒，起點對齊
   靜音。不把前文當提示詞：MOSS 不吃提示詞。
3. 接回與去重（:func:`splice`）：重疊區前段與接續段各轉了一次。接續點之前信前段、之後信接續段；
   接續點挑兩邊都在換句的地方，片段整句保留。
4. 說話者編號（:func:`match_speakers`）：接續段的說話者分離是另外做的，靠重疊區配對回前段的編號；
   接續段把同一個人分成兩位時，證據夠就兩位都配回同一個編號（#322）。
5. 放棄：接續失敗、一次沒有推進 ``CONTINUATION_MIN_PROGRESS_SECONDS`` 秒（卡住），或已經接續了
   ``CONTINUATION_MAX_ATTEMPTS`` 次。放棄時保留已轉的部分，任務照樣完成，停下的地方照掉尾的提示告訴
   使用者「從 mm:ss 起可能沒有轉錄到」（#94 第 1 題）。接續了幾次只寫進日誌，畫面不顯示（第 3 題）。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.core.config import get_settings
from app.services.silence_removal import Span
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

Segment = Mapping[str, Any]

_SPEAKER_RE = re.compile(r"S(\d+)")

# 多對一（#322）的證據，見 :func:`_same_person`；門檻的依據是研究區
# research_notes/322-continuation-speakers 的離線實驗
SAME_PERSON_MIN_SECONDS = 2.0
SAME_PERSON_MIN_SHARE = 0.8
SAME_PERSON_MAX_SIMULTANEOUS_SECONDS = 0.1


def resume_point(stopped: float, silences: Optional[Sequence[float]]) -> float:
    """停在 ``stopped`` 秒時，接續從哪裡開始。

    往前重疊 ``CONTINUATION_OVERLAP_SECONDS`` 秒，但最多重疊到 ``stopped`` 的一半：停在開頭附近時，從
    0 秒接續等於把同一段再轉一次，結果也相同。起點對齊 ``silences``（這一段裡已知的靜音位置）：取那個點
    往前半個重疊之內最晚的靜音；沒有時就是那個點，重疊區照樣接得回去。取到毫秒，和切音檔時 ffmpeg 收到
    的起點相同。
    """
    overlap = get_settings().continuation_overlap_seconds
    target = max(stopped - overlap, stopped / 2)
    earliest = max(target - overlap / 2, stopped / 2)
    candidates = [b for b in silences or () if earliest <= b <= target]
    return round(max(candidates, default=target), 3)


def splice(earlier: Sequence[Segment], later: Sequence[Segment], *,
           overlap: Span) -> List[Dict[str, Any]]:
    """把接續段 ``later`` 接在前段 ``earlier`` 後面，回傳新的片段，依前段、接續段的順序。

    ``overlap`` 是（接續段的起點, 前段停下的地方），兩邊都轉了這一段。接續點（:func:`_junction`）
    之前的片段用前段的，之後用接續段的：片段的中點在接續點之前算前段，之後算接續段。接續點兩邊都不在
    片段中間時，每個片段整個落在一邊，句子不會被切開。接續段的說話者編號換成前段的
    （:func:`match_speakers`）。
    """
    begin, stopped = overlap
    cut = _junction(earlier, later, begin, stopped)
    speakers = match_speakers(earlier, later, overlap=overlap)
    kept = [dict(segment) for segment in earlier if _middle(segment) < cut]
    for segment in later:
        if _middle(segment) >= cut:
            speaker = segment.get("speaker")
            kept.append({**segment,
                         "speaker": None if speaker is None else speakers.get(speaker, speaker)})
    return kept


def match_speakers(earlier: Sequence[Segment], later: Sequence[Segment], *,
                   overlap: Span) -> Dict[str, str]:
    """接續段的說話者編號對到前段的哪一個，回傳 {接續段的編號: 換成的編號}。

    接續段的說話者分離和前段無關，編號照它自己出場的先後，同一個人在兩邊的編號可能不同。``overlap``
    （接續段的起點, 前段停下的地方）裡兩邊都轉了：同一時間說話的時間加總起來，從最長的一對開始配對。

    - 前段的編號還沒配給別人時，直接配。
    - 已經配給接續段的另一位時，只有證據夠才也配給這一位（多對一，#322）：接續段的說話者分離可能把
      同一個人分成兩位，例如語氣在重疊區裡變了。證據是 :func:`_same_person` 的三個條件；不夠時照
      一對一，繼續看這一位的下一對。
    - 接續段裡配不到的人用新的編號，接在前段用過的最大編號之後，不和前段的任何人共用：沒有證據時，
      寧可同一個人多一個編號，也不把不同的人併成同一個。

    重疊區裡兩邊沒有任何同時說話的地方時（例如重疊區只有音樂），沒有可以依據的，照接續段原本的編號。
    #93 的跨段說話者編號也可以拿重疊區當證據。配對的依據（同時說話幾秒）寫進日誌，不寫文字。

    沒有說話者編號的片段（None）不參與配對。
    """
    begin, end = overlap
    heard = [s for s in later if _named(s) and _overlaps(s, begin, end)]
    windowed = [s for s in earlier if _named(s) and _overlaps(s, begin, end)]
    together: Dict[Tuple[str, str], float] = {}
    speaking: Dict[str, float] = {}
    for b in heard:
        speaking[b["speaker"]] = speaking.get(b["speaker"], 0.0) + _shared(b, b, begin, end)
        for a in windowed:
            seconds = _shared(a, b, begin, end)
            if seconds > 0:
                key = (b["speaker"], a["speaker"])
                together[key] = together.get(key, 0.0) + seconds
    named = sorted({s["speaker"] for s in later if _named(s)})
    if not together:
        return {speaker: speaker for speaker in named}

    mapping: Dict[str, str] = {}
    evidence: Dict[str, str] = {}
    for (mine, theirs), seconds in sorted(together.items(), key=lambda item: (-item[1], item[0])):
        if mine in mapping:
            continue
        sharing = [other for other, to in mapping.items() if to == theirs]
        if not sharing:
            mapping[mine] = theirs
            evidence[mine] = f"同時說話 {seconds:.1f} 秒"
        elif _same_person(mine, sharing, later, seconds=seconds, speaking=speaking[mine]):
            mapping[mine] = theirs
            evidence[mine] = (f"同時說話 {seconds:.1f} 秒，佔重疊區的 {seconds / speaking[mine]:.0%}，"
                              f"和 {'、'.join(sharing)} 是同一個人")
    next_number = 1 + max(_numbers(s.get("speaker") for s in earlier), default=-1)
    for speaker in named:
        if speaker not in mapping:
            mapping[speaker] = f"S{next_number}"
            evidence[speaker] = "新編號"
            next_number += 1
    logger.info("接續的說話者配對（接續段→前段）："
                + "；".join(f"{mine}→{mapping[mine]}（{evidence[mine]}）" for mine in named))
    return mapping


def _same_person(mine: str, sharing: Sequence[str], later: Sequence[Segment], *,
                 seconds: float, speaking: float) -> bool:
    """接續段的 ``mine`` 和已經配到同一個前段編號的 ``sharing`` 是不是同一個人：

    1. 和那個前段編號同時說話（``seconds``）至少 ``SAME_PERSON_MIN_SECONDS`` 秒：比時間戳對不準、短暫
       附和造成的重疊長，又不到一句話。不同的兩個人被誤配，在實驗裡都是 2 秒以下的證據。
    2. 至少佔他在重疊區說話時間（``speaking``）的 ``SAME_PERSON_MIN_SHARE``：他在重疊區說的話，大部分
       前段都認成那個人。實驗裡配對正確的人都在 0.88 以上。
    3. 在整個接續段裡，和 ``sharing`` 的任何一位同時說話加起來不超過
       ``SAME_PERSON_MAX_SIMULTANEOUS_SECONDS`` 秒（只容許時間戳的捨入）：同一個人不會和自己搶話，
       MOSS 輸出的同一位說話者的片段也從不重疊。兩個人在重疊區搶話、前段只認出其中一位時，前兩個條件
       擋不住，靠這一條。
    """
    if seconds < SAME_PERSON_MIN_SECONDS or seconds < SAME_PERSON_MIN_SHARE * speaking:
        return False
    theirs = [s for s in later if s.get("speaker") in sharing]
    simultaneous = sum(_shared(a, b, -math.inf, math.inf)
                       for a in later if a.get("speaker") == mine for b in theirs)
    return simultaneous <= SAME_PERSON_MAX_SIMULTANEOUS_SECONDS


def _junction(earlier: Sequence[Segment], later: Sequence[Segment],
              begin: float, stopped: float) -> float:
    """接續點：``begin`` 到 ``stopped`` 之間，兩邊都沒有片段跨過的最晚的時間（片段的起訖或
    ``stopped``）；找不到時（例如重疊區一直有人說話）是 ``stopped``，跨過它的片段看中點落在哪一邊。"""
    both = [s for s in (*earlier, *later) if _overlaps(s, begin, stopped)]
    candidates = {stopped} | {t for s in both for t in (s["start"], _end(s)) if begin <= t <= stopped}
    for t in sorted(candidates, reverse=True):
        if not any(s["start"] < t < _end(s) for s in both):
            return t
    logger.info(f"接續：{begin:.2f}–{stopped:.2f} 秒之間兩邊都有片段跨過，接在 {stopped:.2f} 秒")
    return stopped


def _overlaps(segment: Segment, begin: float, end: float) -> bool:
    return segment["start"] <= end and _end(segment) >= begin


def _named(segment: Segment) -> bool:
    return segment.get("speaker") is not None


def _shared(a: Segment, b: Segment, begin: float, end: float) -> float:
    """``a`` 和 ``b`` 在 ``begin`` 到 ``end`` 之間同時說話幾秒；``a`` 和 ``b`` 是同一個片段時就是它在這段
    時間裡說了幾秒。"""
    return max(0.0, min(_end(a), _end(b), end) - max(a["start"], b["start"], begin))


def _end(segment: Segment) -> float:
    """片段的結束；沒有結束時間時看開始。"""
    end = segment.get("end")
    return end if end is not None else segment["start"]


def _middle(segment: Segment) -> float:
    return (segment["start"] + _end(segment)) / 2


def _numbers(speakers: Iterable[Optional[str]]) -> List[int]:
    """說話者編號（``S0``、``S1``…）的數字；不是這種寫法的不算。"""
    return [int(m[1]) for speaker in speakers if speaker and (m := _SPEAKER_RE.fullmatch(speaker))]
