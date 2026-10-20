"""tools/check.py：唯一的檢查清單（ruff → pytest → ESLint）。

CI 的 job 與本機都經由它跑檢查，所以最要緊的性質是：任何一項失敗或跑不起來，
結束碼就不是 0，而且其餘項目照樣跑完，一次看到全部的紅燈。
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def check(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "ait_tools_check", ROOT / "tools" / "check.py")
    module = importlib.util.module_from_spec(spec)
    # dataclass 解析字串型別註記時，要在 sys.modules 找得到模組
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _fake(check, tmp_path, name, code=0):
    """執行時把自己的名字附加到 ran.txt，再以 code 結束的假檢查。"""
    log = tmp_path / "ran.txt"
    script = (f"open({str(log)!r}, 'a', encoding='utf-8').write({name!r}); "
              f"raise SystemExit({code})")
    return check.Check(name, (sys.executable, "-c", script), tmp_path)


def _ran(tmp_path):
    log = tmp_path / "ran.txt"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def test_checks_are_ruff_pytest_eslint_node_test_in_order(check):
    assert [c.name for c in check.CHECKS] == ["ruff", "pytest", "eslint", "node-test"]


def test_python_checks_use_running_interpreter_from_repo_root(check):
    by_name = {c.name: c for c in check.CHECKS}
    for name in ("ruff", "pytest"):
        assert by_name[name].cmd[0] == sys.executable
        assert by_name[name].cwd == ROOT
    assert by_name["eslint"].cwd == ROOT / "frontend"


def test_frontend_tests_run_with_node_from_frontend(check):
    # 前端的純邏輯測試用 Node 內建的 node:test，不另裝套件
    node_test = {c.name: c for c in check.CHECKS}["node-test"]
    assert node_test.cmd[:2] == ("node", "--test")
    assert node_test.cwd == ROOT / "frontend"


def test_no_arguments_runs_every_check(check, monkeypatch, tmp_path):
    monkeypatch.setattr(check, "CHECKS", tuple(
        _fake(check, tmp_path, name) for name in "abc"))
    assert check.main([]) == 0
    assert _ran(tmp_path) == "abc"


def test_named_checks_run_alone_in_list_order(check, monkeypatch, tmp_path):
    monkeypatch.setattr(check, "CHECKS", tuple(
        _fake(check, tmp_path, name) for name in "abc"))
    assert check.main(["c", "a", "c"]) == 0
    assert _ran(tmp_path) == "ac"


def test_failure_exits_nonzero_and_remaining_checks_still_run(check, monkeypatch, tmp_path):
    monkeypatch.setattr(check, "CHECKS", (
        _fake(check, tmp_path, "a", code=1), _fake(check, tmp_path, "b")))
    assert check.main([]) == 1
    assert _ran(tmp_path) == "ab"


def test_missing_tool_fails_with_remedy(check, monkeypatch, tmp_path, capsys):
    tool_missing = check.Check(
        "x", (sys.executable, "-c", "pass"), tmp_path, missing=lambda: "先安裝 x 再重跑")
    monkeypatch.setattr(check, "CHECKS", (tool_missing, _fake(check, tmp_path, "b")))
    assert check.main([]) == 1
    assert "先安裝 x 再重跑" in capsys.readouterr().out
    assert _ran(tmp_path) == "b"


def test_command_that_cannot_start_is_a_failure(check, monkeypatch, tmp_path):
    monkeypatch.setattr(check, "CHECKS", (
        check.Check("x", ("ait-no-such-command-29",), tmp_path),))
    assert check.main([]) == 1


def test_unknown_check_name_is_rejected(check):
    with pytest.raises(SystemExit) as exc:
        check.main(["no-such-check"])
    assert exc.value.code == 2



def test_missing_eslint_names_the_fix_for_that_checkout(check, tmp_path):
    eslint = {c.name: c for c in check.checks(tmp_path)}["eslint"]
    remedy = eslint.missing()
    assert remedy is not None
    assert "npm ci" in remedy
    assert str(tmp_path / "frontend") in remedy


# ── pre-commit：只跑快的檢查，而且只跑和暫存區有關的（#49） ──────────────────────


def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)


@pytest.fixture
def stage(check, monkeypatch, tmp_path):
    """tmp_path/repo 是一個空的 repo，ROOT 指向它；回傳「把這些檔案加進暫存區」的函式。"""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.setattr(check, "ROOT", repo)

    def add(*paths):
        for path in paths:
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", *paths], cwd=repo, check=True)
    return add


def _covering(check, tmp_path, name, suffix, *, pre_commit, code=0):
    fake = _fake(check, tmp_path, name, code)
    return check.Check(name, fake.cmd, fake.cwd, runs_for=lambda p: p.endswith(suffix),
                       pre_commit=pre_commit)


def test_staged_runs_fast_checks_covering_staged_paths(check, monkeypatch, tmp_path, stage):
    monkeypatch.setattr(check, "CHECKS", (
        _covering(check, tmp_path, "a", ".py", pre_commit=True),
        _covering(check, tmp_path, "b", ".py", pre_commit=False),
        _covering(check, tmp_path, "c", ".js", pre_commit=True),
    ))
    stage("backend/x.py", "README.md")
    assert check.main(["--staged"]) == 0
    # b 是慢的檢查（像 pytest），交給 CI；c 和暫存的檔案無關
    assert _ran(tmp_path) == "a"


def test_staged_with_nothing_relevant_passes_without_running(check, monkeypatch, tmp_path, stage):
    monkeypatch.setattr(check, "CHECKS", (
        _covering(check, tmp_path, "a", ".py", pre_commit=True),))
    stage("docs/x.md")
    assert check.main(["--staged"]) == 0
    assert _ran(tmp_path) == ""


def test_staged_failure_blocks_the_commit(check, monkeypatch, tmp_path, stage):
    monkeypatch.setattr(check, "CHECKS", (
        _covering(check, tmp_path, "a", ".py", pre_commit=True, code=1),))
    stage("x.py")
    assert check.main(["--staged"]) == 1


def test_only_ruff_and_eslint_run_before_commit(check):
    assert [c.name for c in check.CHECKS if c.pre_commit] == ["ruff", "eslint"]


def test_python_change_triggers_ruff_and_frontend_change_triggers_eslint(check):
    by_name = {c.name: c for c in check.CHECKS}
    assert by_name["ruff"].runs_for("backend/requirements.txt")
    assert by_name["ruff"].runs_for("ruff.toml")
    assert not by_name["ruff"].runs_for("README.md")
    assert by_name["eslint"].runs_for("frontend/src/App.jsx")
    assert not by_name["eslint"].runs_for("frontend/dist/index.js")
    assert by_name["node-test"].runs_for("frontend/src/utils/id.js")
