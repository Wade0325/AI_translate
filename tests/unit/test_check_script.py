"""tools/check.py：唯一的檢查清單（ruff → pytest → ESLint）。

CI 的 job 與本機都經由它跑檢查，所以最要緊的性質是：任何一項失敗或跑不起來，
結束碼就不是 0，而且其餘項目照樣跑完，一次看到全部的紅燈。
"""
import importlib.util
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


def test_checks_are_ruff_pytest_eslint_in_order(check):
    assert [c.name for c in check.CHECKS] == ["ruff", "pytest", "eslint"]


def test_python_checks_use_running_interpreter_from_repo_root(check):
    by_name = {c.name: c for c in check.CHECKS}
    for name in ("ruff", "pytest"):
        assert by_name[name].cmd[0] == sys.executable
        assert by_name[name].cwd == ROOT
    assert by_name["eslint"].cwd == ROOT / "frontend"


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
