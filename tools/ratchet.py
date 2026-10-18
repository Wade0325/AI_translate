"""型別閘門的棘輪：只進不退。

兩個數字都不得比 origin/main 多，多了就失敗：

  * frontend/src 裡標了 ``@ts-nocheck`` 的檔案數
  * .basedpyright/baseline.json 的條目數

兩者都是在放寬型別閘門：多標一個 ``@ts-nocheck``，那個檔就不再檢查；重產 baseline，
新的錯誤就被吸收進去。合併由代理在 `check` 綠燈後執行，沒有人工把關，所以把「只進不退」
寫成確定性的檢查（#34）。比的是工作目錄，不是暫存區的快照，和 tools/check.py 的其他項目一樣。

origin/main 還沒有某個閘門（沒有 frontend/tsconfig.json 或 baseline）時，那個數字還沒有
起點，不比。由 tools/check.py 的 ratchet 項目呼叫；只用標準函式庫與 git。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = "origin/main"
NOCHECK = "@ts-nocheck"
FRONTEND_SRC = "frontend/src"
TSCONFIG = "frontend/tsconfig.json"
BASELINE = ".basedpyright/baseline.json"


def baseline_entries(text: str) -> int:
    return sum(len(entries) for entries in json.loads(text).get("files", {}).values())


def nocheck_files(root: Path) -> int:
    src = root / FRONTEND_SRC
    if not src.is_dir():
        return 0
    return sum(1 for p in src.rglob("*")
               if p.is_file() and NOCHECK in p.read_text(encoding="utf-8", errors="replace"))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _main_has(root: Path, path: str) -> bool:
    return _git(root, "cat-file", "-e", f"{MAIN}:{path}").returncode == 0


def _main_nocheck_files(root: Path) -> int:
    proc = _git(root, "grep", "-l", "-F", NOCHECK, MAIN, "--", FRONTEND_SRC)
    if proc.returncode not in (0, 1):  # 1：沒有符合的檔案
        raise RuntimeError(proc.stderr.strip())
    return len(proc.stdout.splitlines())


def compare(root: Path = ROOT) -> list[str]:
    """回傳超過 origin/main 的項目，一項一行；空的就是通過。"""
    if _git(root, "rev-parse", "--verify", "--quiet", f"{MAIN}^{{commit}}").returncode:
        raise RuntimeError(f"找不到 {MAIN}：先執行 git fetch origin main")
    failures = []
    if _main_has(root, TSCONFIG):
        before, now = _main_nocheck_files(root), nocheck_files(root)
        print(f"{FRONTEND_SRC} 標 {NOCHECK} 的檔案：{MAIN} {before}，現在 {now}")
        if now > before:
            failures.append(f"{NOCHECK} 的檔案從 {before} 個增加到 {now} 個")
    else:
        print(f"{MAIN} 還沒有 {TSCONFIG}：{NOCHECK} 不比")
    if _main_has(root, BASELINE):
        before = baseline_entries(_git(root, "show", f"{MAIN}:{BASELINE}").stdout)
        baseline = root / BASELINE
        now = baseline_entries(baseline.read_text(encoding="utf-8")) if baseline.is_file() else 0
        print(f"{BASELINE} 的條目：{MAIN} {before}，現在 {now}")
        if now > before:
            failures.append(f"{BASELINE} 的條目從 {before} 增加到 {now}（重產了 baseline？）")
    else:
        print(f"{MAIN} 還沒有 {BASELINE}：baseline 不比")
    return failures


def main() -> int:
    try:
        failures = compare()
    except RuntimeError as e:
        print(e)
        return 1
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.exit(main())
