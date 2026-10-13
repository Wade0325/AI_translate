"""單元測試：受保護路徑的 PreToolUse hook（tools/hooks/protect_paths.py）

用假的 payload 執行 hook 的 main()，確認：
  * 寫入、刪除或搬移標準答案（lab/data/eval/）與 .env 的變體時擋下（exit 2）
  * 讀取一律放行；寫到 lab/ 底下其他位置也放行
  * 讀不到 payload 時擋下，不靜默放行
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "tools" / "hooks" / "protect_paths.py"
ROOT = "D:\\dev\\AI_translate"                         # 假的主 checkout
WORKTREE = ROOT + "\\.claude\\worktrees\\feature"


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("protect_paths", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_hook(hook, monkeypatch, capsys):
    """把 payload 當成 stdin 執行 main()，回傳 (結束碼, stderr)。"""
    def run(payload) -> tuple[int, str]:
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
        code = hook.main()
        return code, capsys.readouterr().err

    return run


def _payload(tool: str, tool_input: dict, cwd: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "cwd": cwd,
    }


def bash(command: str, cwd: str = ROOT) -> dict:
    return _payload("Bash", {"command": command}, cwd)


def powershell(command: str, cwd: str = ROOT) -> dict:
    return _payload("PowerShell", {"command": command}, cwd)


def write(path: str) -> dict:
    return _payload("Write", {"file_path": path, "content": "x"}, ROOT)


def edit(path: str) -> dict:
    return _payload("Edit", {"file_path": path, "old_string": "a", "new_string": "b"}, ROOT)


def notebook(path: str) -> dict:
    return _payload("NotebookEdit", {"notebook_path": path, "new_source": "x"}, ROOT)


def _id(payload: dict) -> str:
    """參數化的測試名稱：工具加上命令或路徑。"""
    tool_input = payload["tool_input"]
    detail = tool_input.get("command") or tool_input.get("file_path") or tool_input.get("notebook_path")
    return f"{payload['tool_name']}: {detail}"


def assert_blocked(result: tuple[int, str]) -> None:
    code, err = result
    assert code == 2, f"應該擋下，卻放行了（exit {code}）"
    assert err.strip(), "擋下時要在 stderr 說明原因"


def assert_allowed(result: tuple[int, str]) -> None:
    code, err = result
    assert code == 0, f"應該放行，卻擋下了：{err}"


class TestReportedBypasses:
    """稽核時用假 payload 實測會放行（exit 0）的四種寫入。"""

    def test_bash_redirect_into_eval(self, run_hook):
        assert_blocked(run_hook(bash("echo x > lab/data/eval/rec17_A.draft.txt")))

    def test_powershell_set_content_into_eval(self, run_hook):
        assert_blocked(run_hook(powershell(
            r"Set-Content -Path lab\data\eval\rec17_A.draft.txt -Value x")))

    def test_notebook_edit_under_eval(self, run_hook):
        assert_blocked(run_hook(notebook(ROOT + r"\lab\data\eval\scratch.ipynb")))

    def test_write_env_production(self, run_hook):
        assert_blocked(run_hook(write(ROOT + r"\.env.production")))


class TestShellWriteActions:
    """寫入型動作指向標準答案時擋下：重新導向、寫檔 cmdlet、tee、複製與搬移的目的地、刪除。"""

    @pytest.mark.parametrize("command", [
        "echo x >> lab/data/eval/rec17.tsv",
        "echo x >lab/data/eval/a.txt",
        "python make.py 2> lab/data/eval/err.txt",
        "make &> lab/data/eval/log.txt",
        "echo x | tee lab/data/eval/a.txt",
        "echo x | tee -a /tmp/log.txt lab/data/eval/a.txt",
        "cp /tmp/a.txt lab/data/eval/rec17_A.draft.txt",
        "cp -t lab/data/eval /tmp/a.txt",
        "mv /tmp/a.txt lab/data/eval/a.txt",
        "mv lab/data/eval/rec17.tsv /tmp/",                 # 搬走也等於刪掉原處的標準答案
        "rm lab/data/eval/rec17.tsv",
        "rm -f lab/data/eval/*.txt",
        "echo x > LAB/Data/EVAL/rec17.tsv",                 # 不分大小寫
        "echo x > /d/dev/AI_translate/lab/data/eval/a.txt",  # Git Bash 的絕對路徑
        "cat a.txt > 'D:\\dev\\AI_translate\\lab\\data\\eval\\a.txt'",  # 反斜線
        "cd lab/data/eval && echo x > a.txt",               # 先 cd 再寫相對路徑
        "true; rm lab/data/eval/a.txt",
        "sudo rm -rf lab/data/eval",
        "FOO=1 rm lab/data/eval/a.txt",
        "ls lab/data/eval/*.txt | xargs rm",
        "find lab/data/eval -name '*.txt' -exec rm {} +",
        'powershell -NoProfile -Command "Remove-Item lab\\data\\eval\\a.txt"',
        'cmd //c "del lab\\data\\eval\\a.txt"',
    ])
    def test_bash_blocks(self, run_hook, command):
        assert_blocked(run_hook(bash(command)))

    @pytest.mark.parametrize("command", [
        r"Add-Content lab\data\eval\rec17.tsv 'x'",
        r"'x' | Out-File -FilePath lab\data\eval\a.txt -Encoding utf8",
        r"'x' | Out-File lab\data\eval\a.txt",
        r"'x' > lab\data\eval\a.txt",
        r"Get-Date *>> lab\data\eval\a.txt",
        r"'x' | Tee-Object -FilePath lab\data\eval\a.txt",
        r"Copy-Item C:\tmp\a.txt -Destination lab\data\eval\a.txt",
        r"Copy-Item C:\tmp\a.txt lab\data\eval\a.txt",
        r"Copy-Item -Path C:\tmp\a.txt lab\data\eval",
        r"Move-Item -Path C:\tmp\a.txt -Destination lab\data\eval\a.txt",
        r"Remove-Item lab\data\eval\rec17.tsv",
        r"Remove-Item -LiteralPath 'lab\data\eval\rec17 A.txt' -Force",
        r"del lab\data\eval\rec17.tsv",
        r"SET-CONTENT LAB\DATA\EVAL\REC17.TSV 'x'",
        r"Set-Content D:\dev\AI_translate\lab\data\eval\a.txt 'x'",
        r"Set-Location lab\data; Remove-Item eval -Recurse",
        r"Get-ChildItem lab\data\eval | Remove-Item",
        r"Get-ChildItem lab\data\eval -Filter *.txt | ForEach-Object { Remove-Item $_.FullName }",
        r"Remove-Item -Recurse -Force (Join-Path $PWD 'lab\data\eval')",
        "bash -c 'rm -rf lab/data/eval'",
    ])
    def test_powershell_blocks(self, run_hook, command):
        assert_blocked(run_hook(powershell(command)))

    def test_relative_path_from_worktree_into_main_checkout(self, run_hook):
        assert_blocked(run_hook(bash("echo x > ../../../lab/data/eval/a.txt", cwd=WORKTREE)))

    def test_edit_tool(self, run_hook):
        assert_blocked(run_hook(edit(ROOT + r"\lab\data\eval\rec17_A.draft.txt")))


class TestEvalParentsAndGitClean:
    """lab、lab/data 本身或底下的萬用字元也擋；lab/ 底下其他位置放行；git clean 不看路徑。"""

    @pytest.mark.parametrize("payload", [
        bash("rm -r lab"),
        powershell(r"Remove-Item lab\data -Recurse"),
        bash("rm -rf lab/*"),
        powershell(r"Remove-Item -Recurse -Force lab\*"),
        bash("rm -rf ./lab/data/"),
        bash("rm -rf lab/data/e*"),
        bash("rm -rf lab/{data,runs}"),
        bash("rm -rf lab/data/eval"),
        bash("mv lab /tmp/lab-old"),
        powershell(r"Move-Item lab\data C:\tmp\data"),
        bash("cp -r /tmp/new lab/"),
        powershell(r"Remove-Item -Recurse -Force D:\dev\AI_translate\lab"),
    ], ids=_id)
    def test_parent_of_eval_is_blocked(self, run_hook, payload):
        assert_blocked(run_hook(payload))

    @pytest.mark.parametrize("payload", [
        bash("echo x > lab/runs/out.txt"),
        bash("mkdir -p lab/runs/exp1 && cp /tmp/a.txt lab/runs/exp1/"),
        bash("rm -rf lab/runs/old"),
        bash("rm -rf lab/r*"),
        bash("mv lab/runs/a lab/reports/a"),
        bash("echo x > lab/data/notes.txt"),
        powershell(r"Remove-Item -Recurse -Force lab\runs\old"),
        powershell(r"Set-Content lab\reports\note.md 'x'"),
        write(ROOT + r"\lab\runs\out.txt"),
    ], ids=_id)
    def test_other_places_under_lab_are_allowed(self, run_hook, payload):
        assert_allowed(run_hook(payload))

    @pytest.mark.parametrize("payload", [
        bash("git clean -fdX"),
        bash("git clean -fdx"),
        bash("git clean -f"),
        bash("git -C D:/dev/AI_translate clean -ffdx"),
        bash("git status && git clean -fd"),
        powershell("git clean -fdX"),
    ], ids=_id)
    def test_git_clean_without_dry_run_is_blocked(self, run_hook, payload):
        assert_blocked(run_hook(payload))

    @pytest.mark.parametrize("command", [
        "git clean -n",
        "git clean -ndX",
        "git clean -fdxn",
        "git clean --dry-run -fdX",
        "git status --short",
    ])
    def test_git_clean_dry_run_is_allowed(self, run_hook, command):
        assert_allowed(run_hook(bash(command)))


class TestReadOnlyCommands:
    """只擋寫入：讀標準答案（#36 的評測工具會用 python 讀）一律放行。"""

    @pytest.mark.parametrize("payload", [
        bash("python tools/eval/score.py --ref lab/data/eval/rec17_A.draft.txt --hyp lab/runs/out.txt"),
        bash("python -c \"print(open('lab/data/eval/rec17.tsv', encoding='utf-8').read()[:200])\""),
        powershell(r"& D:\dev\AI_translate\backend\.venv\Scripts\python.exe tools\eval\score.py lab\data\eval\rec17.tsv"),
        powershell(r"Get-Content lab\data\eval\rec17.tsv -TotalCount 5"),
        powershell(r"Get-Content -Raw -Encoding utf8 lab\data\eval\rec17_A.draft.txt | Measure-Object -Line"),
        powershell(r"Get-Content lab\data\eval\rec17.tsv | Out-File $env:TEMP\rec17.txt"),
        powershell(r"Get-ChildItem lab\data\eval"),
        powershell(r"Copy-Item lab\data\eval\rec17.tsv lab\runs\rec17.tsv"),
        bash("cat lab/data/eval/rec17.tsv"),
        bash("cat lab/data/eval/rec17.tsv | head -5"),
        bash("cat lab/data/eval/rec17_A.draft.txt > /tmp/copy.txt"),
        bash("wc -l < lab/data/eval/rec17.tsv"),
        bash("grep -n 'x' lab/data/eval/*.txt"),
        bash("cp lab/data/eval/rec17.tsv lab/runs/"),
        bash("cat .env"),
    ], ids=_id)
    def test_reads_are_allowed(self, run_hook, payload):
        assert_allowed(run_hook(payload))

    @pytest.mark.parametrize("payload", [
        bash('echo "echo x > lab/data/eval/a.txt"'),
        bash('git commit -m "擋下 rm -rf lab 與 git clean -fdX"'),
        bash("git commit -F - <<'EOF'\n擋下寫入標準答案\nrm -rf lab\necho x > lab/data/eval/a.txt\nEOF"),
        powershell("$body = @'\nrm -rf lab\nSet-Content lab\\data\\eval\\a.txt x\n'@\n$body | Out-File C:\\tmp\\body.md"),
    ], ids=_id)
    def test_text_mentioning_protected_paths_is_allowed(self, run_hook, payload):
        assert_allowed(run_hook(payload))


class TestProtectedScope:
    """保護範圍：*/lab/data/eval/*（含 rec17.tsv），*/.env 與 */.env.*，但 .env.example 放行。"""

    @pytest.mark.parametrize("payload", [
        write(ROOT + r"\lab\data\eval\rec17.tsv"),
        bash("echo x >> lab/data/eval/rec17.tsv"),
        write(ROOT + r"\.env"),
        write(ROOT + r"\backend\.env"),
        write(ROOT + r"\.env.local"),
        write(ROOT + r"\frontend\.env.development.local"),
        write(ROOT + r"\data\.env.production"),
        edit(ROOT + r"\backend\.env.local"),
        bash("echo GEMINI_KEY=x >> .env"),
        bash("cp .env.example .env"),
        bash("rm .env*"),
        powershell(r"Set-Content backend\.env.production 'x'"),
    ], ids=_id)
    def test_eval_and_env_variants_are_blocked(self, run_hook, payload):
        assert_blocked(run_hook(payload))

    @pytest.mark.parametrize("payload", [
        write(ROOT + r"\.env.example"),
        edit(ROOT + r"\.env.example"),
        bash("echo '# 範例' >> .env.example"),
        bash("cp .env.example /tmp/env.example"),
        write(ROOT + r"\.envrc"),
        write(ROOT + r"\backend\app\main.py"),
    ], ids=_id)
    def test_env_example_and_other_files_are_allowed(self, run_hook, payload):
        assert_allowed(run_hook(payload))


class TestUnreadablePayload:
    """讀不到 payload 時擋下並說明原因，不再放行。"""

    @pytest.mark.parametrize("raw", ["not json", "", '{"tool_input": ', "[1, 2]"])
    def test_blocks_with_reason(self, run_hook, raw):
        code, err = run_hook(raw)
        assert code == 2
        assert "讀不到" in err

    def test_payload_without_tool_input_is_allowed(self, run_hook):
        assert_allowed(run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash"}))


class TestScriptContract:
    def test_uses_standard_library_only(self):
        tree = ast.parse(HOOK.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add(node.module.split(".")[0])
        assert imported <= set(sys.stdlib_module_names)

    def test_block_message_says_reads_are_allowed(self, run_hook):
        _, err = run_hook(bash("echo x > lab/data/eval/a.txt"))
        assert "不擋讀取" in err

    def test_entry_point_blocks_with_utf8_reason(self):
        payload = json.dumps(bash("echo x > lab/data/eval/a.txt")).encode("utf-8")
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=payload, capture_output=True, timeout=60,
        )
        assert result.returncode == 2
        assert "標準答案" in result.stderr.decode("utf-8")

    def test_entry_point_blocks_unreadable_payload(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=b"not json", capture_output=True, timeout=60,
        )
        assert result.returncode == 2
