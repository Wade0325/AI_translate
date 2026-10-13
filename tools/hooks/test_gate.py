"""Stop hook：這個回合有改動時跑 lint 與測試，紅燈就不讓回合結束。

CLAUDE.md 的規則是勸告，這支 hook 才是強制的；能不能合併，仍以 CI 為準。

要檢查的路徑
  * 工作區的變動（含未追蹤檔），加上「上次綠燈」之後的 commit 動到的檔案：
    同一回合內改完就 commit，一樣會檢查。
  * 上次綠燈時的 HEAD 記在各 worktree 自己的 git-dir（``STATE_FILE``），
    worktree 之間互不干擾。綠燈才更新，紅燈不更新。
  * 還沒有紀錄時，從 HEAD 與預設分支的 merge-base 算起（依序找 origin/HEAD、
    origin/master、origin/main、master、main），只看這個分支自己的改動。
    這些分支都不存在時無從判斷分支從哪裡開始，就檢查 repo 裡的所有檔案。

依路徑挑檢查（不只看副檔名）
  * 任何 .py，或 backend/、tests/、tools/ 底下任何檔案（含 backend/requirements*.txt），
    或 pytest.ini、ruff.toml → ruff + pytest
  * frontend/ 底下除了 dist/ 以外的任何檔案 → ESLint
  * 全部跑完才一起回報，免得修好 lint 才看到測試也紅。

在哪裡跑、用什麼跑
  * 一律以 repo 根目錄為基準。payload 的 cwd 會跟著 Claude 的 cd 走，所以先用
    ``git -C <cwd> rev-parse --show-toplevel`` 解析根目錄；cwd 不在任何 repo 時，
    改用 CLAUDE_PROJECT_DIR（session 啟動處）；兩者都失敗就擋下。
  * Python 檢查依序用 <repo 根目錄>/backend/.venv、主 checkout 的 backend/.venv
    （git common dir 的上一層），不用執行這支 hook 的直譯器。
  * Python 子程序以 UTF-8 輸出（PYTHONIOENCODING），失敗原因裡的中文才不會變亂碼。
  * 找不到檢查工具（兩處都沒有 backend/.venv、venv 裡沒有 ruff 或 pytest、
    frontend/node_modules 裡沒有 ESLint、PATH 上沒有 node）也擋下，並印出原因與
    可以直接執行的補救指令。改成「略過並警告」等於放寬閘門，要由使用者決定。

什麼時候擋
  * 紅燈就擋（exit 2），不看 payload 的 stop_hook_active。Claude Code 自己有上限：
    Stop hook 連續讓回合繼續 8 次後，下一次阻擋會被覆寫、回合結束；但 Claude 每呼叫
    一次工具，計數就歸零（環境變數 CLAUDE_CODE_STOP_HOOK_BLOCK_CAP 可以調高上限）。
    所以代理持續呼叫工具修復時，會一直擋到綠燈；檢查因為與這次改動無關的原因一直
    紅燈時，要由使用者中斷。
  * 故障也擋：任何例外或 git 指令失敗，都印出原因並 exit 2。exit 1 會被當成
    non-blocking error 而放行，Stop hook 的 onFailure 設定又沒有作用，只能在腳本裡
    處理。settings.json 設的逾時一到仍會放行，這點腳本補不了。
  * 擋下的訊息第一行是這支腳本自己的路徑：從主 checkout 啟動的 session 進了
    worktree，跑的仍是主 checkout 那一份（${CLAUDE_PROJECT_DIR} 不隨 worktree 改變）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

TAIL_LINES = 40
STATE_FILE = "ait-test-gate-last-green"
DEFAULT_BRANCHES = (
    "refs/remotes/origin/HEAD",
    "refs/remotes/origin/master",
    "refs/remotes/origin/main",
    "refs/heads/master",
    "refs/heads/main",
)
PYTHON_DIRS = ("backend/", "tests/", "tools/")
PYTHON_FILES = ("pytest.ini", "ruff.toml")
WINDOWS = os.name == "nt"

RED = (
    "驗證失敗，修好再結束回合。\n"
    "檢查因為與這次改動無關的原因一直紅燈時（例如 master 上原本就失敗的測試），"
    "先合併 master 或等修正的 PR，不要繞過；master 本身也紅燈時，停下來問使用者。"
)
FAULT = (
    "Stop hook 沒能完成檢查，所以擋下這個回合。修好下面的問題再結束；"
    "修不了（例如 hook 本身的錯）時，停下來問使用者，不要繞過。"
)

Check = tuple[str, list[str], Path]


class GateError(Exception):
    """沒辦法完成檢查（找不到 repo、git 失敗、讀不到輸入）：印出原因並擋下。"""


class MissingTool(Exception):
    """找不到檢查工具；訊息附上補救指令。"""


def _git(root: Path, *args: str, probe: bool = False) -> str:
    """在 root 跑 git，回傳 stdout；失敗就丟 GateError。

    probe=True 用在只問「有沒有」的指令（rev-parse --verify --quiet、merge-base）：
    它們以 exit 1 表示「沒有」，這時回傳空字串，不算失敗。
    """
    # --no-optional-locks：git status 不順手寫回 index，不和同時在跑的 git 搶鎖
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode == 0:
        return result.stdout
    if probe and result.returncode == 1:
        return ""
    raise GateError(
        f"git {' '.join(args)} 失敗（exit {result.returncode}）：{result.stderr.strip()}"
    )


def _repo_root(cwd: str) -> Path:
    """要檢查的 repo 根目錄：先看 payload 的 cwd，不在任何 repo 時改看 CLAUDE_PROJECT_DIR。"""
    tried = []
    for label, start in (("cwd", cwd), ("CLAUDE_PROJECT_DIR", os.environ.get("CLAUDE_PROJECT_DIR", ""))):
        if not start:
            tried.append(f"{label}：沒有值")
            continue
        try:
            return Path(_git(Path(start), "rev-parse", "--show-toplevel").strip())
        except GateError as e:
            tried.append(f"{label}（{start}）：{e}")
    raise GateError("找不到要檢查的 git repo：\n  " + "\n  ".join(tried))


def _head(root: Path) -> str:
    """HEAD 的 commit；還沒有任何 commit 時回傳空字串。"""
    return _git(root, "rev-parse", "--verify", "--quiet", "HEAD", probe=True).strip()


def _state_path(root: Path) -> Path:
    # 各 worktree 的 git-dir 不同（.git/worktrees/<name>），狀態檔因此互不干擾
    return Path(_git(root, "rev-parse", "--absolute-git-dir").strip()) / STATE_FILE


def _read_state(state: Path) -> str:
    try:
        text = state.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    return text if re.fullmatch(r"[0-9a-f]{40}([0-9a-f]{24})?", text) else ""


def _baseline(root: Path, head: str) -> str:
    """上次綠燈時的 HEAD；沒有紀錄就用 HEAD 與預設分支的 merge-base；都沒有回傳空字串。"""
    recorded = _read_state(_state_path(root))
    if recorded == head:
        return head
    if recorded and _git(root, "rev-parse", "--verify", "--quiet", f"{recorded}^{{commit}}", probe=True):
        return recorded
    existing = set(_git(root, "for-each-ref", "--format=%(refname)", *DEFAULT_BRANCHES).split())
    for ref in DEFAULT_BRANCHES:
        if ref in existing:
            base = _git(root, "merge-base", head, ref, probe=True).strip()
            if base:
                return base
    return ""


def _changed_paths(root: Path) -> list[str]:
    """要檢查的路徑：工作區的變動，加上上次綠燈之後的 commit 動到的檔案。"""
    # -uall 逐檔列出未追蹤檔（預設只印目錄，新增整個目錄的 .py 會逃過閘門）；
    # --no-renames 把改名拆成刪除＋新增，舊路徑也算改動
    status = _git(root, "status", "--porcelain", "-z", "-uall", "--no-renames")
    paths = {entry[3:] for entry in status.split("\0") if entry}
    head = _head(root)
    if head:
        base = _baseline(root, head)
        if not base:
            paths.update(_git(root, "ls-files", "-z").split("\0"))
        elif base != head:
            # 比兩邊的檔案樹：base 不是 HEAD 的祖先（例如換過分支）也照樣成立
            paths.update(
                _git(root, "diff", "--name-only", "-z", "--no-renames", base, head).split("\0")
            )
    paths.discard("")
    return sorted(paths)


def _record_green(root: Path) -> None:
    head = _head(root)
    if not head:
        return
    state = _state_path(root)
    if _read_state(state) != head:
        state.write_text(head + "\n", encoding="utf-8")


def _select_checks(paths: list[str]) -> list[str]:
    """依改動的路徑挑檢查：改設定或依賴檔，一樣可能讓測試或 lint 壞掉。"""
    names: list[str] = []
    if any(p.endswith(".py") or p.startswith(PYTHON_DIRS) or p in PYTHON_FILES for p in paths):
        names += ["ruff", "pytest"]
    if any(p.startswith("frontend/") and not p.startswith("frontend/dist/") for p in paths):
        names.append("eslint")
    return names


def _python_in(venv: Path) -> Path | None:
    for python in (venv / "Scripts" / "python.exe", venv / "bin" / "python"):
        if python.is_file():
            return python
    return None


def _venv_python(root: Path) -> Path:
    """Python 檢查用的直譯器：先找 repo 根目錄的 backend/.venv，再找主 checkout 的。"""
    own = _python_in(root / "backend" / ".venv")
    if own:
        return own
    main = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent
    tried = [root / "backend" / ".venv"]
    if main.resolve() != root.resolve():
        theirs = _python_in(main / "backend" / ".venv")
        if theirs:
            return theirs
        tried.append(main / "backend" / ".venv")

    venv = main / "backend" / ".venv"
    requirements = (
        f'-r "{main / "backend" / "requirements-standalone.txt"}" '
        f'-r "{main / "backend" / "requirements-dev.txt"}"'
    )
    if WINDOWS:
        fix = (
            "（PowerShell）",
            f'py -3.11 -m venv "{venv}"',
            f'& "{venv / "Scripts" / "python.exe"}" -m pip install {requirements}',
        )
    else:
        fix = (
            "",
            f'python3.11 -m venv "{venv}"',
            f'"{venv / "bin" / "python"}" -m pip install {requirements}',
        )
    raise MissingTool(
        "[ruff、pytest] 找不到 Python 檢查用的 venv，找過：\n"
        + "".join(f"  {path}\n" for path in tried)
        + f"補救：在主 checkout 建 venv 並安裝依賴{fix[0]}：\n  {fix[1]}\n  {fix[2]}"
    )


def _python_checks(root: Path) -> list[Check]:
    python = str(_venv_python(root))
    return [
        ("ruff", [python, "-m", "ruff", "check", "."], root),
        ("pytest", [python, "-m", "pytest", "tests/", "-q"], root),
    ]


def _frontend_checks(root: Path) -> list[Check]:
    frontend = root / "frontend"
    # 直接用 node 跑 eslint 入口，避開 Windows 上 npx.cmd 得經過 shell 的問題
    eslint = frontend / "node_modules" / "eslint" / "bin" / "eslint.js"
    missing = []
    if not eslint.is_file():
        missing.append(
            f"[eslint] 找不到 ESLint：{eslint} 不存在（這個 checkout 還沒裝前端依賴）。\n"
            f'補救：照 package-lock.json 安裝：\n  npm ci --prefix "{frontend}"'
        )
    if shutil.which("node") is None:
        missing.append(
            "[eslint] PATH 上找不到 node。\n"
            "補救：安裝 Node.js（Windows：winget install OpenJS.NodeJS.LTS），再重開 Claude Code 讓 PATH 生效。"
        )
    if missing:
        raise MissingTool("\n\n".join(missing))
    # --quiet 只印 error：react-hooks 的 warning 一則十幾行，會把真正的 error 擠出 TAIL_LINES
    return [("eslint", ["node", str(eslint), ".", "--quiet"], frontend)]


def _run(name: str, cmd: list[str], cwd: Path) -> str | None:
    """跑一項檢查；通過回傳 None，失敗回傳給 Claude 看的尾段輸出。"""
    # Python 子程序寫進管線時用系統碼頁（例如 cp936），這裡卻以 UTF-8 解碼，失敗原因裡的
    # 中文會變成 U+FFFD。只設 PYTHONIOENCODING、不開 UTF-8 模式（PYTHONUTF8）：open() 的
    # 預設編碼仍和使用者的環境一樣，測試照樣抓得到沒指定 encoding 的 bug
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        return f"[{name}] 無法執行：{e}"
    if result.returncode == 0:
        return None
    tail = (result.stdout or result.stderr or "").splitlines()[-TAIL_LINES:]
    message = f"[{name}] 失敗：\n" + "\n".join(tail)
    module = cmd[2] if len(cmd) > 2 and cmd[1] == "-m" else ""
    if module and f"No module named {module}" in result.stdout + result.stderr:
        install = f'"{cmd[0]}" -m pip install -r "{cwd / "backend" / "requirements-dev.txt"}"'
        shell = "（PowerShell）" if WINDOWS else ""
        prefix = "& " if WINDOWS else ""
        message += f"\n補救：這個 venv 沒有 {module}，安裝開發工具{shell}：\n  {prefix}{install}"
    return message


def _verify(root: Path, names: list[str]) -> list[str]:
    """跑挑到的檢查，回傳所有失敗（包括找不到工具）。"""
    failures: list[str] = []
    checks: list[Check] = []
    if "ruff" in names or "pytest" in names:
        try:
            checks += [check for check in _python_checks(root) if check[0] in names]
        except MissingTool as e:
            failures.append(str(e))
    if "eslint" in names:
        try:
            checks += _frontend_checks(root)
        except MissingTool as e:
            failures.append(str(e))
    failures += [msg for name, cmd, where in checks if (msg := _run(name, cmd, where))]
    return failures


def _report(root: Path | None, header: str, sections: list[str]) -> None:
    lines = [f"Stop hook 腳本：{Path(__file__).resolve()}"]
    if root is not None:
        lines.append(f"檢查的 repo：{root}")
    lines.append(header)
    print("\n".join(lines) + "\n\n" + "\n\n".join(sections), file=sys.stderr)


def main() -> int:
    root: Path | None = None
    try:
        try:
            payload = json.load(sys.stdin)
        except ValueError as e:
            raise GateError(f"讀不到 Claude Code 傳來的 JSON：{e}") from e
        root = _repo_root(payload.get("cwd") or os.getcwd())
        failures = _verify(root, _select_checks(_changed_paths(root)))
        if failures:
            _report(root, RED, failures)
            return 2
        _record_green(root)
        return 0
    except GateError as e:
        _report(root, FAULT, [str(e)])
        return 2
    except Exception:
        _report(root, FAULT, ["\n".join(traceback.format_exc().splitlines()[-TAIL_LINES:])])
        return 2


if __name__ == "__main__":
    # Claude Code 以 UTF-8 送出 JSON，Windows 的 stdin 卻用系統碼頁解碼：輸入有中文時
    # JSON 會解析失敗，而讀不到輸入會擋下回合。
    # Windows 的 stderr 用系統碼頁，Claude 讀到的中文會變亂碼。
    for stream in (sys.stdin, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        code = main()
    except Exception:  # 連 main() 自己的回報都失敗時，一樣擋下，不讓 exit 1 放行
        code = 2
    sys.exit(code)
