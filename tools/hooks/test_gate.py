"""Stop hook：有程式碼改動時跑 lint 與測試，紅燈就不讓這個回合結束。

官方把這種做法列為驗證的「deterministic gate」（best-practices：Give Claude a way
to verify its work）。CLAUDE.md 的規則是勸告性的，hook 才是強制的。

幾個刻意的取捨：
  * 依改動範圍挑檢查：.py（或 ruff.toml）→ ruff + pytest；frontend 的 .js/.jsx
    → ESLint。純問答的回合不該浪費 8 秒
  * 所有檢查跑完才一起回報，免得修好 lint 才看到測試也紅
  * ``stop_hook_active`` 為真時直接放行 —— 官方的 Stop hook 在連續阻擋 8 次後
    會被覆寫，這個旗標避免和那個上限互相打架
  * 失敗時 exit 2，並把各檢查的尾段輸出寫到 stderr，Claude 才看得到原因
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

Check = tuple[str, list[str], Path]


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


def _python_checks(cwd: Path) -> list[Check]:
    # worktree 裡的 .venv 通常是接回主 checkout 的 junction，路徑照樣成立
    python = cwd / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    return [
        ("ruff", [str(python), "-m", "ruff", "check", "."], cwd),
        ("pytest", [str(python), "-m", "pytest", "tests/", "-q"], cwd),
    ]


def _frontend_checks(cwd: Path) -> list[Check]:
    frontend = cwd / "frontend"
    # 直接用 node 跑 eslint 入口，避開 Windows 上 npx.cmd 得經過 shell 的問題
    eslint = frontend / "node_modules" / "eslint" / "bin" / "eslint.js"
    # --quiet 只印 error：react-hooks 的 warning 一則十幾行，會把真正的 error
    # 擠出 TAIL_LINES
    return [("eslint", ["node", str(eslint), ".", "--quiet"], frontend)]


def _run(name: str, cmd: list[str], cwd: Path) -> str | None:
    """跑一項檢查；通過回傳 None，失敗回傳給 Claude 看的尾段輸出。"""
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        return f"[{name}] 無法執行：{e}"
    if result.returncode == 0:
        return None
    tail = (result.stdout or result.stderr or "").splitlines()[-TAIL_LINES:]
    return f"[{name}] 失敗：\n" + "\n".join(tail)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    if payload.get("stop_hook_active"):
        return 0

    cwd = Path(payload.get("cwd") or os.getcwd())
    changed = _changed_paths(cwd)
    if changed is None:
        return 0

    checks: list[Check] = []
    if any(p.endswith(".py") or p == "ruff.toml" for p in changed):
        checks += _python_checks(cwd)
    if any(p.startswith("frontend/") and p.endswith((".js", ".jsx")) for p in changed):
        checks += _frontend_checks(cwd)

    failures = [msg for name, cmd, where in checks if (msg := _run(name, cmd, where))]
    if not failures:
        return 0

    print("驗證失敗，修好再結束回合：\n\n" + "\n\n".join(failures), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
