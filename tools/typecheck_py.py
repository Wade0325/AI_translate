"""basedpyright 閘門：只擋錯誤清單（.basedpyright/baseline.json）以外的新錯誤，並確認真的分析到檔案。

由 tools/check.py 的 basedpyright 項目呼叫；用執行這支腳本的直譯器跑 basedpyright，
也拿它當分析時的 Python 環境（``--pythonpath``）。設定在 repo 根目錄的 pyrightconfig.json。

錯誤數是 0 還不夠：pyrightconfig.json 的 include 對不上時，pyright 回報 0 個錯誤，
其實一個檔案也沒分析，所以分析到 0 個檔案也算失敗。清單裡的錯誤修掉時，basedpyright
會自己把它們從清單拿掉；重產清單（--writebaseline）等於放寬閘門，tools/ratchet.py 會擋。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOWN = 30  # 一次最多印幾則錯誤


def verdict(report: dict) -> tuple[list[str], str | None]:
    """basedpyright --outputjson 的報告 → (要印的錯誤, 失敗原因)；通過時失敗原因是 None。"""
    errors = [d for d in report.get("generalDiagnostics", []) if d.get("severity") == "error"]
    lines = []
    for d in errors[:SHOWN]:
        line = d.get("range", {}).get("start", {}).get("line", 0) + 1
        lines.append(f"{d.get('file')}:{line} [{d.get('rule', '')}] {d.get('message', '')}")
    if len(errors) > SHOWN:
        lines.append(f"……還有 {len(errors) - SHOWN} 則")
    summary = report.get("summary", {})
    if not summary.get("filesAnalyzed"):
        return lines, "basedpyright 沒有分析到任何檔案：檢查 pyrightconfig.json 的 include"
    count = summary.get("errorCount", len(errors))
    if count:
        return lines, f"{count} 個錯誤清單以外的型別錯誤"
    return lines, None


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--outputjson", "--pythonpath", sys.executable],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print((proc.stderr or proc.stdout)[-2000:])
        print(f"basedpyright 沒有輸出報告（結束碼 {proc.returncode}）")
        return 1
    lines, failure = verdict(report)
    print("\n".join(lines))
    summary = report.get("summary", {})
    print(f"分析了 {summary.get('filesAnalyzed', 0)} 個檔案，"
          f"{summary.get('errorCount', 0)} 個錯誤清單以外的錯誤")
    if failure:
        print(failure)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.exit(main())
