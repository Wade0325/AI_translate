"""PreToolUse hook：阻擋 AI 寫入不該由 AI 改動的檔案。

保護的是「重做成本很高」或「不該自動化」的東西：

  * ``lab/data/eval/*.txt`` —— 人工聽打的 gold 評測檔。那是幾小時的人工成果，
    而且它是所有實驗的標準答案，被覆寫等於所有數字失去意義
  * ``.env`` —— 金鑰與連線設定（``.env.example`` 不在保護範圍，那是範本）

只擋寫入，不擋讀取：計分工具仍然要讀 gold。
"""

from __future__ import annotations

import fnmatch
import json
import sys

# Windows 的 stderr 用系統碼頁，中文理由會變亂碼，Claude 就看不懂為什麼被擋
try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# (glob 比對正規化後的絕對路徑, 理由)
PROTECTED = [
    ("*/lab/data/eval/*.txt", "人工聽打的 gold 評測檔"),
    ("*/.env", "環境變數與金鑰設定"),
    ("*/.env.local", "環境變數與金鑰設定"),
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    path = (payload.get("tool_input") or {}).get("file_path")
    if not path:
        return 0

    normalized = str(path).replace("\\", "/")
    for pattern, reason in PROTECTED:
        if fnmatch.fnmatch(normalized, pattern):
            print(
                f"拒絕寫入 {normalized}：{reason}。"
                "這個檔案只由使用者本人修改；需要變更請說明原因並請使用者自己改，"
                "或改用其他檔名。",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
