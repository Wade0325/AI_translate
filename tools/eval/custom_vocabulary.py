"""術語表的讀取：錯誤分類與術語召回用到其中的英文術語（terms）與中文術語（zh_terms）。

術語表是研究區 ``glossaries/`` 底下的 JSON，例如：

    {"terms": ["Docker", "SQL"], "zh_terms": ["設定檔", "資料庫"]}

其他欄位（說明、別名）評測不用，讀的時候略過。
"""

from __future__ import annotations

import json
from pathlib import Path


def load_custom_vocabulary(*paths: str | Path) -> dict:
    """合併多份術語表；同一個術語只留第一次出現的。"""
    merged: dict = {"terms": [], "zh_terms": [], "sources": []}
    for p in paths:
        p = Path(p)
        data = json.loads(p.read_text(encoding="utf-8"))
        for key in ("terms", "zh_terms"):
            for t in data.get(key, []):
                if t not in merged[key]:
                    merged[key].append(t)
        merged["sources"].append(p.name)
    return merged
