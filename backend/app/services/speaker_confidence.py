"""說話者機率（GLOSSARY）：本機的模型寫一個片段的說話者編號時，給這個編號的機率。

轉接器在片段上附 ``speaker_probs``：{說話者編號: 機率}，是模型寫這個片段的說話者時給各說話者編號的機率，編號和
片段的 ``speaker`` 同一套（現在只有本機的 MOSS 有，見 ``app.provider.local.moss`` 與 ``app.provider.local.asr``）。
分段轉錄與接續換說話者編號時，機率跟著換（:func:`renamed`）；合併完成時每個片段只留下它最後的說話者的機率
（:func:`settled`，``speaker_confidence``），存進片段，校正頁照它標出說話者不確定的片段。

- 兩個編號換成同一位時機率相加（例如照所選人數收斂把 S3 併進 S1）：模型在這兩個編號之間猶豫，換完之後兩個都是
  同一位，就不算不確定。
- 換編號的對照裡沒有的其他編號（模型考慮過、這一段卻沒有人用的編號）不知道換完之後是誰，丟掉。只會讓機率偏低、
  多標出幾個片段，不會漏標。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

PROBS = "speaker_probs"
"""轉接器附在片段上的各說話者編號的機率。"""
CONFIDENCE = "speaker_confidence"
"""合併完成的片段上，它的說話者的機率。"""


def renamed(segment: Mapping[str, Any], mapping: Mapping[str, str]) -> Optional[Dict[str, float]]:
    """片段的說話者編號照 ``mapping``（{原本的編號: 換成的編號}）換時，它的說話者機率換成的樣子；片段沒有說話者
    機率時是 None。

    ``mapping`` 是空的（不換編號）時照舊。片段自己的說話者不在 ``mapping`` 裡時照舊，和換說話者編號的規則相同；
    其他編號不在 ``mapping`` 裡時丟掉（見模組說明）。換成同一位的機率相加。
    """
    probs = segment.get(PROBS)
    if probs is None:
        return None
    if not mapping:
        return dict(probs)
    speaker = segment.get("speaker")
    out: Dict[str, float] = {}
    for label, probability in probs.items():
        if label in mapping:
            new = mapping[label]
        elif label == speaker:
            new = label
        else:
            continue
        out[new] = out.get(new, 0.0) + probability
    return out


def settled(segment: Mapping[str, Any]) -> Dict[str, Any]:
    """合併完成的片段：說話者機率換成片段的說話者的那一個（``speaker_confidence``），回傳新的片段。

    沒有附說話者機率的片段（Gemini、VibeVoice）原樣傳回，不加這一欄。附了、卻沒有片段的說話者的機率時是 None。
    """
    out = dict(segment)
    if PROBS not in out:
        return out
    probs = out.pop(PROBS)
    speaker = out.get("speaker")
    out[CONFIDENCE] = None if probs is None or speaker is None else probs.get(speaker)
    return out
