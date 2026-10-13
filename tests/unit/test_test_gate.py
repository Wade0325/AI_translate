"""Stop hook（tools/hooks/test_gate.py）的測試。

每個測試都在 tmp_path 裡建暫存 repo，不碰這個 repo 本身；git 不讀使用者的設定，
也不會往上找到外層的 repo。實際執行 ruff、pytest、ESLint 的 ``_run`` 預設換成
紀錄器（在 pytest 裡再跑一次 pytest 會遞迴）：這裡測的是「檢查哪些路徑、挑哪些
檢查、在哪裡跑、什麼時候擋」。``_run`` 本身的行為由 ``REAL_RUN`` 的測試涵蓋。
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "tools" / "hooks" / "test_gate.py"
_spec = importlib.util.spec_from_file_location("test_gate_hook", HOOK)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)
REAL_RUN = gate._run

# A49：issue #28 指定的原句
UNRELATED_RED = (
    "檢查因為與這次改動無關的原因一直紅燈時（例如 main 上原本就失敗的測試），"
    "先合併 main 或等修正的 PR，不要繞過；main 本身也紅燈時，停下來問使用者。"
)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", check=True,
    )
    return result.stdout.strip()


def write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(root: Path, rel: str, text: str = "x = 1\n") -> None:
    write(root, rel, text)
    git(root, "add", rel)
    git(root, "commit", "-q", "-m", f"add {rel}")


def fake_venv(root: Path) -> Path:
    """只要直譯器的檔案存在就好：_run 換成紀錄器之後，它不會真的被執行。"""
    python = root / "backend" / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    return python


def same(a: Path | str, b: Path | str) -> bool:
    return Path(a).resolve() == Path(b).resolve()


def run_hook(monkeypatch, capsys, payload: dict) -> tuple[int, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = gate.main()
    return code, capsys.readouterr().err


class FakeRun:
    """取代 _run：記下每項檢查的名稱、指令與工作目錄；failing 為真時一律回報紅燈。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], Path]] = []
        self.failing = False

    def __call__(self, name: str, cmd: list[str], cwd: Path) -> str | None:
        self.calls.append((name, cmd, Path(cwd)))
        return f"[{name}] 失敗：\n模擬的紅燈" if self.failing else None

    @property
    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    config = tmp_path / "gitconfig"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def checks_run(monkeypatch) -> FakeRun:
    fake = FakeRun()
    monkeypatch.setattr(gate, "_run", fake)
    return fake


@pytest.fixture
def repo(tmp_path) -> Path:
    """master 上有一個 base commit 的暫存 repo；.venv 與 node_modules 被忽略。"""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    write(root, ".gitignore", ".venv/\nnode_modules/\n")
    write(root, "a.py")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    return root


def add_worktree(repo: Path, tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "wt", str(wt))
    return wt


# ── 漏洞 1：同一回合內 commit，回合結束時工作區已經乾淨 ─────────────────────


def test_commit_inside_the_turn_is_still_checked(repo):
    git(repo, "switch", "-q", "-c", "feat/x")
    commit(repo, "b.py")

    assert "b.py" in gate._changed_paths(repo)


def test_first_run_starts_from_the_merge_base_not_the_whole_history(repo):
    git(repo, "switch", "-q", "-c", "feat/x")
    commit(repo, "b.py")
    git(repo, "switch", "-q", "master")
    commit(repo, "m.py")  # 分支開出去之後，master 才有的改動
    git(repo, "switch", "-q", "feat/x")

    paths = gate._changed_paths(repo)

    assert "b.py" in paths
    assert "a.py" not in paths
    assert "m.py" not in paths


def test_first_run_prefers_origin_master_over_a_stale_local_master(repo):
    git(repo, "switch", "-q", "-c", "upstream")
    commit(repo, "o.py")  # 已經進了 origin/master、本機 master 還沒 pull 的改動
    git(repo, "update-ref", "refs/remotes/origin/master", "HEAD")
    git(repo, "switch", "-q", "--no-track", "-c", "feat/x", "origin/master")
    git(repo, "branch", "-q", "-D", "upstream")
    commit(repo, "b.py")

    paths = gate._changed_paths(repo)

    assert "b.py" in paths
    assert "o.py" not in paths


def test_without_any_default_branch_everything_is_checked(tmp_path):
    """找不到 master/main 時，無從判斷分支從哪裡開始：寧可全部檢查，也不漏掉。"""
    root = tmp_path / "solo"
    root.mkdir()
    git(root, "init", "-q", "-b", "trunk")
    commit(root, "a.py")
    commit(root, "b.py")

    assert {"a.py", "b.py"} <= set(gate._changed_paths(root))


def test_a_clean_master_needs_no_checks(repo, monkeypatch, capsys, checks_run):
    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(repo)})

    assert code == 0
    assert checks_run.calls == []


def test_red_keeps_the_baseline_and_green_moves_it(repo, monkeypatch, capsys, checks_run):
    fake_venv(repo)
    git(repo, "switch", "-q", "-c", "feat/x")
    commit(repo, "b.py")

    checks_run.failing = True
    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(repo)})
    assert code == 2

    # 紅燈沒有更新狀態檔：b.py 仍然要檢查
    checks_run.failing = False
    checks_run.calls.clear()
    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(repo)})
    assert code == 0
    assert checks_run.names == ["ruff", "pytest"]

    # 綠燈記下了 HEAD：沒有新的改動，就不必再跑
    checks_run.calls.clear()
    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(repo)})
    assert code == 0
    assert checks_run.calls == []


def test_green_is_recorded_in_the_worktrees_own_git_dir(repo, tmp_path, monkeypatch, capsys):
    fake_venv(repo)
    wt = add_worktree(repo, tmp_path)
    commit(wt, "w.py")

    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(wt)})

    assert code == 0
    state = Path(git(wt, "rev-parse", "--absolute-git-dir")) / gate.STATE_FILE
    assert state.read_text(encoding="utf-8").strip() == git(wt, "rev-parse", "HEAD")
    main_state = Path(git(repo, "rev-parse", "--absolute-git-dir")) / gate.STATE_FILE
    assert not main_state.exists()


# ── 漏洞 2：紅燈只擋一次 ───────────────────────────────────────────────────


def test_stop_hook_active_does_not_let_a_red_turn_end(repo, monkeypatch, capsys, checks_run):
    fake_venv(repo)
    write(repo, "b.py")
    checks_run.failing = True

    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(repo), "stop_hook_active": True})

    assert code == 2


# ── 阻擋訊息 ───────────────────────────────────────────────────────────────


def red_turn(repo, monkeypatch, capsys, checks_run) -> tuple[int, str]:
    fake_venv(repo)
    write(repo, "b.py")
    checks_run.failing = True
    return run_hook(monkeypatch, capsys, {"cwd": str(repo)})


def test_block_message_opens_with_the_hook_scripts_own_path(repo, monkeypatch, capsys, checks_run):
    code, err = red_turn(repo, monkeypatch, capsys, checks_run)

    assert code == 2
    assert str(HOOK) in err.splitlines()[0]


def test_block_message_says_what_to_do_when_red_is_unrelated(repo, monkeypatch, capsys, checks_run):
    code, err = red_turn(repo, monkeypatch, capsys, checks_run)

    assert code == 2
    assert UNRELATED_RED in err


# ── H5：以 repo 根目錄為基準 ───────────────────────────────────────────────


def test_checks_run_from_the_repo_root_when_cwd_is_a_subdirectory(repo, monkeypatch, capsys, checks_run):
    fake_venv(repo)
    write(repo, "b.py")

    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(repo / "backend")})

    assert code == 0
    assert checks_run.names == ["ruff", "pytest"]
    assert all(same(cwd, repo) for _, _, cwd in checks_run.calls)


def test_cwd_outside_any_repo_falls_back_to_claude_project_dir(
    repo, tmp_path, monkeypatch, capsys, checks_run,
):
    fake_venv(repo)
    write(repo, "b.py")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))

    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(outside)})

    assert code == 0
    assert checks_run.names == ["ruff", "pytest"]
    assert all(same(cwd, repo) for _, _, cwd in checks_run.calls)


def test_blocks_when_neither_cwd_nor_project_dir_is_in_a_repo(tmp_path, monkeypatch, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "gone"))

    code, err = run_hook(monkeypatch, capsys, {"cwd": str(outside)})

    assert code == 2
    assert "CLAUDE_PROJECT_DIR" in err


# ── H4：故障時擋下，不放行 ─────────────────────────────────────────────────


def test_an_unexpected_exception_blocks(repo, monkeypatch, capsys):
    def broken(root):
        raise RuntimeError("模擬 hook 內部的錯誤")

    monkeypatch.setattr(gate, "_changed_paths", broken)

    code, err = run_hook(monkeypatch, capsys, {"cwd": str(repo)})

    assert code == 2
    assert "模擬 hook 內部的錯誤" in err


def test_an_unreadable_payload_blocks(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("不是 JSON"))

    assert gate.main() == 2
    assert capsys.readouterr().err


def test_a_failing_git_command_blocks(repo, monkeypatch, capsys):
    (repo / ".git" / "index").write_bytes(b"not an index")

    code, err = run_hook(monkeypatch, capsys, {"cwd": str(repo)})

    assert code == 2
    assert "git status" in err


def test_the_payload_is_read_as_utf8(repo, monkeypatch):
    """Claude Code 以 UTF-8 送出 JSON，裡面有 last_assistant_message 這類中文。照系統碼頁
    （例如 cp936）解讀時，中文後面的反斜線會被當成雙位元組字的一半吃掉，JSON 就壞了；
    讀不到輸入會擋下，所以這裡讀錯就是每個回合都被擋。"""
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    payload = json.dumps(
        {
            "cwd": str(repo),
            "transcript_path": "C:\\Users\\王小明\\.claude\\projects\\session.jsonl",
            "last_assistant_message": '完成。"好"',
        },
        ensure_ascii=False,
    )

    result = subprocess.run(
        [sys.executable, str(HOOK)], input=payload.encode("utf-8"), capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


# ── H4：Python 檢查用的直譯器 ──────────────────────────────────────────────


def test_a_worktree_without_a_venv_uses_the_main_checkouts(repo, tmp_path):
    main_python = fake_venv(repo)
    wt = add_worktree(repo, tmp_path)

    python_checks = gate._python_checks(wt)

    assert [name for name, _, _ in python_checks] == ["ruff", "pytest"]
    assert all(same(cmd[0], main_python) for _, cmd, _ in python_checks)
    assert all(same(cwd, wt) for _, _, cwd in python_checks)


def test_the_repos_own_venv_comes_before_the_main_checkouts(repo, tmp_path):
    fake_venv(repo)
    wt = add_worktree(repo, tmp_path)
    own_python = fake_venv(wt)

    assert all(same(cmd[0], own_python) for _, cmd, _ in gate._python_checks(wt))


# ── 找不到檢查工具：擋下並給補救指令 ───────────────────────────────────────


def test_no_venv_anywhere_blocks_with_a_fix(repo, monkeypatch, capsys):
    write(repo, "b.py")

    code, err = run_hook(monkeypatch, capsys, {"cwd": str(repo)})

    assert code == 2
    assert "-m venv" in err
    assert "requirements-dev.txt" in err


def test_no_eslint_in_node_modules_blocks_with_a_fix(repo, monkeypatch, capsys):
    write(repo, "frontend/src/App.jsx", "export default 1\n")

    code, err = run_hook(monkeypatch, capsys, {"cwd": str(repo)})

    assert code == 2
    assert "npm ci" in err


def test_a_venv_missing_the_tool_says_how_to_install_it(tmp_path):
    message = REAL_RUN("ruff", [sys.executable, "-m", "no_such_module_for_test_gate"], tmp_path)

    assert message is not None
    assert "pip install -r" in message
    assert "requirements-dev.txt" in message


# ── H12：依路徑挑檢查 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("pytest.ini", ["ruff", "pytest"]),
        ("ruff.toml", ["ruff", "pytest"]),
        ("backend/requirements.txt", ["ruff", "pytest"]),
        ("backend/requirements-dev.txt", ["ruff", "pytest"]),
        ("tests/fixtures/sample.srt", ["ruff", "pytest"]),
        ("tools/launcher.cs", ["ruff", "pytest"]),
        ("scripts/anything.py", ["ruff", "pytest"]),
        ("frontend/package.json", ["eslint"]),
        ("frontend/package-lock.json", ["eslint"]),
        ("frontend/src/App.jsx", ["eslint"]),
        ("frontend/dist/index.html", []),
        ("docs/adr/0001-example.md", []),
        ("README.md", []),
    ],
)
def test_checks_are_selected_by_path(path, expected):
    assert gate._select_checks([path]) == expected


def test_python_and_frontend_changes_select_all_three():
    assert gate._select_checks(["pytest.ini", "frontend/package.json"]) == ["ruff", "pytest", "eslint"]


# ── H14：Python 子程序的中文輸出 ───────────────────────────────────────────


def test_python_output_reaches_claude_as_utf8(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    script = "import sys; print('斷言失敗：中文說明'); sys.exit(1)"

    message = REAL_RUN("pytest", [sys.executable, "-c", script], tmp_path)

    assert message is not None
    assert "�" not in message
    assert "斷言失敗：中文說明" in message


# ── #29：檢查清單與「哪些路徑觸發哪些檢查」只寫在 tools/check.py ──────────────


def with_extra_check(monkeypatch, cmd: tuple[str, ...], runs_for) -> None:
    """在 tools/check.py 的清單最後加一項檢查，模擬之後有人在那裡新增檢查。"""
    tools_check = gate._tools_check()
    original = tools_check.checks

    def checks(root=tools_check.ROOT, python=sys.executable):
        extra = tools_check.Check("extra", cmd, Path(root), runs_for=runs_for)
        return (*original(root, python), extra)

    monkeypatch.setattr(tools_check, "checks", checks)


def test_path_rules_come_from_tools_check(monkeypatch):
    with_extra_check(monkeypatch, ("extra-tool",), lambda path: path.endswith(".txt"))

    assert gate._select_checks(["notes.txt"]) == ["extra"]
    assert gate._select_checks(["notes.txt", "a.py"]) == ["ruff", "pytest", "extra"]


def test_a_check_added_to_tools_check_runs_in_the_hook(repo, monkeypatch, capsys, checks_run):
    fake_venv(repo)
    with_extra_check(monkeypatch, ("extra-tool", "--strict"), lambda path: path.endswith(".py"))
    write(repo, "b.py")

    code, _ = run_hook(monkeypatch, capsys, {"cwd": str(repo)})

    assert code == 0
    assert checks_run.names == ["ruff", "pytest", "extra"]
    assert checks_run.calls[-1][1] == ["extra-tool", "--strict"]
    assert same(checks_run.calls[-1][2], repo)


def test_blocks_when_tools_check_cannot_be_loaded(repo, tmp_path, monkeypatch, capsys):
    """載入失敗若在 import 時丟例外，結束碼會是 1，Claude Code 會當成不阻擋而放行。"""
    fake_venv(repo)
    write(repo, "b.py")
    monkeypatch.setattr(gate, "CHECK_SCRIPT", tmp_path / "no-such-check.py")
    gate._tools_check.cache_clear()

    code, err = run_hook(monkeypatch, capsys, {"cwd": str(repo)})
    gate._tools_check.cache_clear()

    assert code == 2
    assert "no-such-check.py" in err
