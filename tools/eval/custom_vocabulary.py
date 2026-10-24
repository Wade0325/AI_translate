"""術語表的讀取：錯誤分類與術語召回用到其中的英文術語（terms）與中文術語（zh_terms）。

術語表是研究區 ``glossaries/`` 底下的 JSON，例如：

    {"terms": ["Docker", "SQL"], "zh_terms": ["資料表", "資料庫"]}

其他欄位（說明、別名）評測不用，讀的時候略過。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CustomVocabulary:
    terms: list[str] = field(default_factory=list)
    zh_terms: list[str] = field(default_factory=list)

    @property
    def all_terms(self) -> list[str]:
        return [*self.terms, *self.zh_terms]


def load_custom_vocabulary(*paths: str | Path) -> CustomVocabulary:
    """合併多份術語表；同一個術語只留第一次出現的。沒給檔案時是空的術語表。"""
    vocabulary = CustomVocabulary()
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        for merged, key in ((vocabulary.terms, "terms"), (vocabulary.zh_terms, "zh_terms")):
            for t in data.get(key, []):
                if t not in merged:
                    merged.append(t)
    return vocabulary
