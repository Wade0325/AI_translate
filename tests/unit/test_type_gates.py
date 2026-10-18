"""型別閘門（#34）：tools/typecheck_py.py 的判定，與 tools/ratchet.py 的棘輪。

要緊的性質：分析到 0 個檔案不算通過；@ts-nocheck 的檔案數與 baseline 的條目數
比 origin/main 多就失敗（逐檔、逐規則，不只比總數），origin/main 還沒有那道閘門時不比。
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(f"ait_tools_{name}", ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


# ── basedpyright 的判定 ─────────────────────────────────────────────────────────


@pytest.fixture
def typecheck(monkeypatch):
    return _load(monkeypatch, "typecheck_py")


def _error(line=0):
    return {"file": "backend/app/x.py", "severity": "error", "rule": "reportArgumentType",
            "message": "壞了", "range": {"start": {"line": line}}}


def test_no_new_errors_passes(typecheck):
    lines, failure = typecheck.verdict({"summary": {"filesAnalyzed": 76, "errorCount": 0},
                                        "generalDiagnostics": []})
    assert failure is None
    assert lines == []


def test_new_error_fails_and_is_printed_one_based(typecheck):
    lines, failure = typecheck.verdict({"summary": {"filesAnalyzed": 76, "errorCount": 1},
                                        "generalDiagnostics": [_error(line=8)]})
    assert failure is not None
    assert lines == ["backend/app/x.py:9 [reportArgumentType] 壞了"]


def test_zero_files_analyzed_fails_even_with_zero_errors(typecheck):
    _, failure = typecheck.verdict({"summary": {"filesAnalyzed": 0, "errorCount": 0},
                                    "generalDiagnostics": []})
    assert failure is not None
    assert "pyrightconfig.json" in failure


def test_warnings_do_not_fail(typecheck):
    warning = {**_error(), "severity": "warning"}
    lines, failure = typecheck.verdict({"summary": {"filesAnalyzed": 1, "errorCount": 0},
                                        "generalDiagnostics": [warning]})
    assert failure is None
    assert lines == []


# ── 棘輪 ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def ratchet(monkeypatch):
    return _load(monkeypatch, "ratchet")


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write(repo, path, text):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")


def _baseline(entries, path="./backend/x.py"):
    return json.dumps({"files": {path: [{"code": "r"}] * entries}})


@pytest.fixture
def repo(tmp_path):
    """有 origin/main 的 repo：main 上 tsconfig、一個 @ts-nocheck 的檔與兩條 baseline。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, "frontend/tsconfig.json", "{}")
    _write(repo, "frontend/src/a.jsx", "// @ts-nocheck\nexport {}\n")
    _write(repo, "frontend/src/b.jsx", "export {}\n")
    _write(repo, ".basedpyright/baseline.json", _baseline(2))
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "main")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def test_unchanged_passes(ratchet, repo):
    assert ratchet.compare(repo) == []


def test_fewer_is_fine(ratchet, repo):
    _write(repo, "frontend/src/a.jsx", "export {}\n")
    _write(repo, ".basedpyright/baseline.json", _baseline(1))
    assert ratchet.compare(repo) == []


def test_one_more_ts_nocheck_fails(ratchet, repo):
    _write(repo, "frontend/src/b.jsx", "// @ts-nocheck\nexport {}\n")
    failures = ratchet.compare(repo)
    assert len(failures) == 1
    assert "@ts-nocheck" in failures[0]


def test_new_ts_nocheck_file_fails(ratchet, repo):
    _write(repo, "frontend/src/c.js", "// @ts-nocheck\n")
    assert len(ratchet.compare(repo)) == 1


def test_moving_ts_nocheck_to_another_file_fails(ratchet, repo):
    _write(repo, "frontend/src/a.jsx", "export {}\n")
    _write(repo, "frontend/src/b.jsx", "// @ts-nocheck\nexport {}\n")
    assert ratchet.compare(repo) == ["新標了 @ts-nocheck：frontend/src/b.jsx"]


def test_swapping_a_fixed_error_for_a_new_one_fails(ratchet, repo):
    # 總數一樣是 2，但 y.py 的錯誤是 main 沒有的：重產錯誤清單吸收了新錯誤
    swapped = {"files": {"./backend/x.py": [{"code": "r"}],
                         "./backend/y.py": [{"code": "r"}]}}
    _write(repo, ".basedpyright/baseline.json", json.dumps(swapped))
    failures = ratchet.compare(repo)
    assert len(failures) == 1
    assert "./backend/y.py" in failures[0]


def test_broken_baseline_is_an_error_not_a_crash(ratchet, repo):
    _write(repo, ".basedpyright/baseline.json", "{not json")
    with pytest.raises(ratchet.RatchetError):
        ratchet.compare(repo)


def test_bigger_baseline_fails(ratchet, repo):
    _write(repo, ".basedpyright/baseline.json", _baseline(3))
    failures = ratchet.compare(repo)
    assert len(failures) == 1
    assert "錯誤清單多了 ./backend/x.py" in failures[0]


def test_gates_missing_on_main_are_not_compared(ratchet, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, "README.md", "x")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "main")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _write(repo, "frontend/src/a.jsx", "// @ts-nocheck\n")
    _write(repo, ".basedpyright/baseline.json", _baseline(5))
    assert ratchet.compare(repo) == []


def test_missing_origin_main_is_an_error(ratchet, repo):
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    with pytest.raises(ratchet.RatchetError, match="git fetch"):
        ratchet.compare(repo)
