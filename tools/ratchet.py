"""型別閘門的棘輪：只進不退。

和 origin/main 比，下面任何一項變多就失敗：

  * frontend/src 裡標了 ``@ts-nocheck`` 的檔案：出現 origin/main 沒標的檔案就算
  * .basedpyright/baseline.json 的型別錯誤清單：任何一個（檔案、規則）的條目數變多就算

兩者都是在放寬型別閘門：多標一個 ``@ts-nocheck``，那個檔就不再檢查；重產錯誤清單
（--writebaseline），新的錯誤就被吸收進去。合併由代理在 `check` 綠燈後執行，沒有人工把關，
所以把「只進不退」寫成確定性的檢查（#34）。逐檔、逐規則比，而不是只比總數：修掉一個舊錯誤、
再吸收一個別處的新錯誤，總數不變也擋得下。代價是改名的檔案算新檔，改名時要先把錯誤修掉。
比的是工作目錄，不是暫存區的快照，和 tools/check.py 的其他項目一樣。

origin/main 還沒有某道閘門（沒有 frontend/tsconfig.json 或錯誤清單）時，那一項還沒有
起點，不比。由 tools/check.py 的 ratchet 項目呼叫；只用標準函式庫與 git。
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = "origin/main"
NOCHECK = "@ts-nocheck"
FRONTEND_SRC = "frontend/src"
TSCONFIG = "frontend/tsconfig.json"
BASELINE = ".basedpyright/baseline.json"


class RatchetError(Exception):
    """比不了：找不到 origin/main、git 失敗，或錯誤清單不是合法的 JSON。"""


def baseline_entries(text: str) -> Counter[tuple[str, str]]:
    """錯誤清單 → 每個（檔案、規則）有幾條。"""
    try:
        files = json.loads(text).get("files", {})
    except (ValueError, AttributeError) as e:
        raise RatchetError(f"{BASELINE} 不是合法的錯誤清單：{e}") from e
    return Counter((path, entry.get("code", "")) for path, entries in files.items()
                   for entry in entries)


def nocheck_files(root: Path) -> set[str]:
    src = root / FRONTEND_SRC
    if not src.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in src.rglob("*")
            if p.is_file() and NOCHECK in p.read_text(encoding="utf-8", errors="replace")}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _main_has(root: Path, path: str) -> bool:
    return _git(root, "cat-file", "-e", f"{MAIN}:{path}").returncode == 0


def _main_nocheck_files(root: Path) -> set[str]:
    proc = _git(root, "grep", "-l", "-F", NOCHECK, MAIN, "--", FRONTEND_SRC)
    if proc.returncode not in (0, 1):  # 1：沒有符合的檔案
        raise RatchetError(proc.stderr.strip())
    # 輸出是「origin/main:路徑」
    return {line.removeprefix(f"{MAIN}:") for line in proc.stdout.splitlines()}


def _over(before: Counter[tuple[str, str]], now: Counter[tuple[str, str]]) -> list[str]:
    return [f"{path} 的 {code}：{before[path, code]} → {count}"
            for (path, code), count in sorted(now.items()) if count > before[path, code]]


def compare(root: Path = ROOT) -> list[str]:
    """回傳比 origin/main 多出來的項目，一項一行；空的就是通過。"""
    if _git(root, "rev-parse", "--verify", "--quiet", f"{MAIN}^{{commit}}").returncode:
        raise RatchetError(f"找不到 {MAIN}：先執行 git fetch origin main")
    failures = []
    if _main_has(root, TSCONFIG):
        before, now = _main_nocheck_files(root), nocheck_files(root)
        print(f"{FRONTEND_SRC} 標 {NOCHECK} 的檔案：{MAIN} {len(before)} 個，現在 {len(now)} 個")
        failures += [f"新標了 {NOCHECK}：{path}" for path in sorted(now - before)]
    else:
        print(f"{MAIN} 還沒有 {TSCONFIG}：{NOCHECK} 不比")
    if _main_has(root, BASELINE):
        before = baseline_entries(_git(root, "show", f"{MAIN}:{BASELINE}").stdout)
        baseline = root / BASELINE
        now = baseline_entries(baseline.read_text(encoding="utf-8")) if baseline.is_file() else Counter()
        print(f"{BASELINE} 的條目：{MAIN} {before.total()} 條，現在 {now.total()} 條")
        failures += [f"錯誤清單多了 {line}（重產了錯誤清單？）" for line in _over(before, now)]
    else:
        print(f"{MAIN} 還沒有 {BASELINE}：錯誤清單不比")
    return failures


def main() -> int:
    try:
        failures = compare()
    except RatchetError as e:
        print(e)
        return 1
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.exit(main())
