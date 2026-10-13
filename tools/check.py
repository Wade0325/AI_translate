"""唯一的檢查清單：ruff → pytest → ESLint。

用法（在哪個目錄執行都可以，一律以 repo 根目錄為基準）：

    python tools/check.py               # 依序跑全部
    python tools/check.py pytest        # 只跑指定的項目，可以列好幾項
    python tools/check.py --list        # 列出所有項目

CI（.github/workflows/ci.yml）的 python 與 frontend job、README 與 .vscode/tasks.json
都呼叫這支腳本，不另寫檢查指令。Stop hook（tools/hooks/test_gate.py）也從這裡取清單與
「改到哪些路徑時要跑哪一項」（各項的 runs_for），自己不定義任何檢查。要加檢查（例如
#34 的型別檢查）就加在 checks()，各處會一起跑。它決定閘門跑哪些檢查，屬於單向門
（docs/agents/merging.md）。

幾個刻意的取捨：
  * 只用標準函式庫：CI 的 frontend job 用 runner 內建的 Python 執行，不裝任何套件；
    Stop hook 也是直接載入這個檔
  * ruff 與 pytest 用執行這支腳本的直譯器跑（``python -m``），所以要用裝了
    backend/requirements-dev.txt 的直譯器呼叫，例如 backend/.venv 裡的 python
  * 不替子程序開 UTF-8 模式（PYTHONUTF8、-X utf8）：CI 的 Windows 腿要和使用者的
    環境一樣，才抓得到 open() 沒指定 encoding 的 bug
  * 一項失敗也把其餘的跑完再一起回報；任何一項失敗或跑不起來，結束碼就是 1
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESLINT_JS = Path("node_modules") / "eslint" / "bin" / "eslint.js"

# 改到這些路徑要跑 Python 的檢查：任何 .py，或這些目錄底下的任何檔案（含
# backend/requirements*.txt 與測試資料），或這些設定檔。改設定或依賴檔一樣可能讓
# 測試或 lint 壞掉，所以不只看副檔名
PYTHON_DIRS = ("backend/", "tests/", "tools/")
PYTHON_FILES = ("pytest.ini", "ruff.toml")


@dataclass(frozen=True)
class Check:
    name: str
    cmd: tuple[str, ...]
    cwd: Path
    # 工具不在時回傳給人看的補救方法；工具都在時回傳 None
    missing: Callable[[], str | None] = lambda: None
    # 改到這個路徑（以 repo 根目錄為基準、用 /）時要跑這項：Stop hook 依此挑檢查，CI 一律全跑
    runs_for: Callable[[str], bool] = lambda path: True
    # 以 Python 直譯器執行（python -m …）：Stop hook 會換成它找到的 venv 裡的 python
    uses_python: bool = False


def _python_related(path: str) -> bool:
    return path.endswith(".py") or path.startswith(PYTHON_DIRS) or path in PYTHON_FILES


def _frontend_related(path: str) -> bool:
    # dist/ 是建置產物，不是原始碼
    return path.startswith("frontend/") and not path.startswith("frontend/dist/")


def _python_module_missing(python: str, module: str) -> Callable[[], str | None]:
    def missing() -> str | None:
        # 只認得執行這支腳本的直譯器；換成別的直譯器時（Stop hook 找到的 venv），
        # 由呼叫的一方從執行結果判斷
        if python != sys.executable or importlib.util.find_spec(module) is not None:
            return None
        return (f"{sys.executable} 沒有安裝 {module}：先執行 "
                f"`{sys.executable} -m pip install -r backend/requirements-dev.txt`，"
                "或改用 backend/.venv 裡的 python 執行 tools/check.py")
    return missing


def _eslint_missing(frontend: Path) -> Callable[[], str | None]:
    def missing() -> str | None:
        problems = []
        if shutil.which("node") is None:
            problems.append("找不到 node：先安裝 frontend/.nvmrc 指定的 Node 版本"
                            "（Windows：winget install OpenJS.NodeJS.LTS），再重開終端機或"
                            " Claude Code，讓 PATH 生效")
        if not (frontend / ESLINT_JS).is_file():
            problems.append(f"{frontend / ESLINT_JS} 不存在（這個 checkout 還沒裝前端依賴）："
                            f'照 package-lock.json 安裝：npm ci --prefix "{frontend}"')
        return "\n".join(problems) or None
    return missing


def checks(root: Path = ROOT, python: str = sys.executable) -> tuple[Check, ...]:
    """檢查清單。Stop hook 傳入 root 與 python，對 worktree、用 venv 的直譯器跑同一份清單。"""
    frontend = root / "frontend"
    return (
        Check("ruff", (python, "-m", "ruff", "check", "."), root,
              _python_module_missing(python, "ruff"), _python_related, uses_python=True),
        Check("pytest", (python, "-m", "pytest", "tests/", "-q"), root,
              _python_module_missing(python, "pytest"), _python_related, uses_python=True),
        # 直接用 node 跑 eslint 的入口，避開 Windows 上 npx.cmd／npm.cmd 得經過 shell 的問題。
        # --quiet 只印 error：warning 不擋合併，react-hooks 的 warning 一則十幾行，會把 error 淹掉
        Check("eslint", ("node", str(ESLINT_JS), ".", "--quiet"), frontend,
              _eslint_missing(frontend), _frontend_related),
    )


CHECKS: tuple[Check, ...] = checks()


def select(paths: Iterable[str]) -> list[str]:
    """改到這些路徑（以 repo 根目錄為基準、用 /）時要跑的檢查，照清單的順序。"""
    paths = list(paths)
    return [c.name for c in checks() if any(c.runs_for(p) for p in paths)]


def _run(check: Check) -> str | None:
    """跑一項檢查；通過回傳 None，失敗回傳一行原因。"""
    print(f"\n==> {check.name}: {' '.join(check.cmd)}", flush=True)
    remedy = check.missing()
    if remedy:
        print(remedy, flush=True)
        return f"無法執行：{remedy}"
    try:
        returncode = subprocess.run(check.cmd, cwd=check.cwd).returncode
    except OSError as e:
        print(f"無法執行：{e}", flush=True)
        return f"無法執行：{e}"
    return None if returncode == 0 else f"失敗（結束碼 {returncode}）"


def main(argv: Sequence[str] | None = None) -> int:
    names = [c.name for c in CHECKS]
    parser = argparse.ArgumentParser(
        prog="tools/check.py",
        description="依序執行 repo 的檢查（" + " → ".join(names) + "）。")
    parser.add_argument("checks", nargs="*", metavar="CHECK",
                        help="只跑這些項目（" + "、".join(names) + "）；不給就全部跑")
    parser.add_argument("--list", action="store_true", help="列出所有項目後結束")
    args = parser.parse_args(argv)

    if args.list:
        print("\n".join(names))
        return 0
    unknown = [n for n in args.checks if n not in names]
    if unknown:
        parser.error(f"沒有這個檢查：{'、'.join(unknown)}（可用：{'、'.join(names)}）")

    selected = [c for c in CHECKS if not args.checks or c.name in args.checks]
    results = [(c.name, _run(c)) for c in selected]

    print("\n結果：")
    width = max(len(name) for name, _ in results)
    for name, failure in results:
        print(f"  {name:<{width}}  {failure or '通過'}")
    return 1 if any(failure for _, failure in results) else 0


if __name__ == "__main__":
    # 輸出到管線時用的是系統碼頁；印不出的字元改用跳脫，不讓腳本自己因為編碼而失敗
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.exit(main())
