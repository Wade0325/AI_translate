"""讀轉錄結果的 LRC：每行「[mm:ss.xx][S0] 文字」，說話者標記可有可無。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# 說話者標記是 [S0]，或存下來的 Gemini LRC 裡的「Speaker A:」（和 backend 的
# app.services.output_format 認得的相同）；沒有標記的行也讀
LINE_RE = re.compile(
    r"^\[(\d+):(\d+(?:\.\d+)?)\]\s*"
    r"(?:\[(?P<label>S\d+)\]|(?P<gemini>Speaker\s*(?:[0-9]+|[A-Z])\s*[:：]))?"
    r"\s*(?P<text>.*)$")
# 標題、作者這類標籤（[ti:…]、[ar:…]），不是轉錄的內容
META_RE = re.compile(r"^\[[A-Za-z]+:.*\]$")


@dataclass
class Line:
    seconds: float
    speaker: str | None   # 沒有說話者標記時是 None
    text: str


@dataclass
class LrcText:
    lines: list[Line] = field(default_factory=list)
    # 不是空行、不是標籤，卻沒有時間戳的行（例如換行後的文字）；不計分
    skipped: list[str] = field(default_factory=list)


def read(path: str | Path) -> LrcText:
    out = LrcText()
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or META_RE.match(s):
            continue
        m = LINE_RE.match(s)
        if not m:
            out.skipped.append(s)
            continue
        if m.group("label"):
            speaker = m.group("label")
        elif m.group("gemini"):
            speaker = re.sub(r"[\s:：]", "", m.group("gemini"))
        else:
            speaker = None
        out.lines.append(Line(seconds=int(m.group(1)) * 60 + float(m.group(2)),
                              speaker=speaker, text=m.group("text")))
    return out
