"""Stop hook：有 Python 改動時跑測試，紅燈就不讓這個回合結束。

官方把這種做法列為驗證的「deterministic gate」（best-practices：Give Claude a way
to verify its work）。CLAUDE.md 的規則是勸告性的，hook 才是強制的。

三個刻意的取捨：
  * 只有工作區出現 .py 變動時才跑；純問答的回合不該浪費 8 秒
  * ``stop_hook_active`` 為真時直接放行 —— 官方的 Stop hook 在連續阻擋 8 次後
    會被覆寫，這個旗標避免和那個上限互相打架
  * 失敗時 exit 2，並把 pytest 的尾段輸出寫到 stderr，Claude 才看得到原因
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Windows 的 stderr 預設 cp950，pytest 的中文輸出會變亂碼
try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

TAIL_LINES = 40


def _changed_paths(cwd: Path) -> list[str] | None:
    """工作區有變動的路徑；不是 git 工作區時回傳 None。"""
    # -uall 才會逐檔列出未追蹤檔案；預設只印目錄（"?? tools/hooks/"），
    # 新增整個目錄的 .py 會因此逃過測試閘門
    result = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    # porcelain 前兩碼是狀態、第三碼是空白；改名會是 "old -> new"
    return [line[3:].strip().strip('"') for line in result.stdout.splitlines()]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    if payload.get("stop_hook_active"):
        return 0

    cwd = Path(payload.get("cwd") or os.getcwd())
    changed = _changed_paths(cwd)
    if changed is None or not any(p.endswith(".py") for p in changed):
        return 0

    # worktree 裡的 .venv 通常是接回主 checkout 的 junction，路徑照樣成立
    python = cwd / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)

    result = subprocess.run(
        [str(python), "-m", "pytest", "tests/", "-q"],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        return 0

    tail = (result.stdout or result.stderr or "").splitlines()[-TAIL_LINES:]
    print("pytest 失敗，修好再結束回合：\n" + "\n".join(tail), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
