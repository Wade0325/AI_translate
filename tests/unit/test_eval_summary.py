"""``python -m tools.eval summary``：把 eval 的 JSON 與兩邊的 manifest 整理成 PR 的評測摘要（#38）。

摘要要貼進 PR，所以只能有數字、雜湊與檔名：標準答案與轉錄結果的文字一個字都不能出現（#15 的 Q4）。
"""
import json
import textwrap

import pytest

from tools.eval import cli

REFERENCE_TEXT = "我們下週二去爬山"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


def _manifest(lrc, commit, *, sha256="ab" * 32, duration=30.0, rtf=0.1234, vram=10.5,
              dirty=False):
    """transcribe 在轉錄結果旁邊寫的 manifest（只留摘要用到的欄位）。"""
    manifest = {
        "command": "transcribe",
        "request": {"provider": "local", "model": "moss-align", "language": "zh-TW"},
        "audio": {"file": "demo.wav", "sha256": sha256, "duration_seconds": duration},
        "code": {"commit": commit, "dirty": dirty},
        "run": {"success": True, "rtf": rtf, "peak_vram_gb": vram},
    }
    lrc.with_name(f"{lrc.stem}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def lab(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    _write(root / "data" / "eval" / "demo_A.txt", f"# demo_A  00:00.00-00:30.00\nA: {REFERENCE_TEXT}\n")
    (root / "glossaries").mkdir()
    monkeypatch.setenv("AIT_LAB_DIR", str(root))
    return root


@pytest.fixture
def runs(tmp_path):
    """main 與 PR 各轉一次：main 漏了「山」（錯字率 1/8），PR 全對；最後一行都在 1 秒。"""
    base = _write(tmp_path / "runs" / "main" / "demo.lrc", "[00:01.00][S0] 我們下週二去爬\n")
    head = _write(tmp_path / "runs" / "pr" / "demo.lrc", f"[00:01.00][S0] {REFERENCE_TEXT}\n")
    return base, head


def _eval(capsys, out, *transcripts, extra=()):
    argv = ["eval", "--reference", "demo_A", "--transcript", str(transcripts[0])]
    if len(transcripts) == 2:
        argv += ["--vs", str(transcripts[1])]
    assert cli.main([*argv, *extra, "--json", str(out)]) == 0
    capsys.readouterr()
    return out


def _summary(capsys, path):
    code = cli.main(["summary", str(path)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_eval_json_has_what_the_summary_needs(lab, runs, tmp_path, capsys):
    path = _eval(capsys, tmp_path / "eval.json", *runs)

    result = json.loads(path.read_text(encoding="utf-8"))
    assert [s["cp_mer_global"] for s in result["systems"]] == [0.125, 0.0]
    assert result["paired"]["delta_mer"] == -0.125
    assert result["paired"]["significant"] in (True, False)
    assert len(result["paired"]["ci"]) == 2


def test_compares_main_and_the_pull_request(lab, runs, tmp_path, capsys):
    _manifest(runs[0], "1" * 40, rtf=0.1234, vram=10.5)
    _manifest(runs[1], "2" * 40, rtf=0.2, vram=None, dirty=True)
    path = _eval(capsys, tmp_path / "eval.json", *runs)

    code, out, _ = _summary(capsys, path)

    assert code == 0
    assert "### 評測摘要：demo.wav" in out
    assert "| | 基準（--transcript） | 這個 PR（--vs） |" in out
    assert f"| commit | `{'1' * 12}` | `{'2' * 12}`（有沒 commit 的改動） |" in out
    assert "| 模型與語言 | local／moss-align／zh-TW | local／moss-align／zh-TW |" in out
    assert "| 錯字率（MER） | 12.50% | 0.00% |" in out
    assert "| cpMER（全域對應） | 12.50% | 0.00% |" in out
    assert "| RTF | 0.123 | 0.200 |" in out
    assert "| 峰值顯存 | 10.5 GB | 沒有用到顯卡 |" in out
    assert "最後一行 0:01，音檔 0:30，之後 29 秒沒有字" in out
    assert "- ΔMER（這個 PR − 基準）：-12.50 pp，95% CI [" in out
    assert "- 音檔：`demo.wav`（SHA-256 `abababababababab…`，長度 0:30）" in out
    assert "- 標準答案：demo_A\n" in out
    assert ("`python -m tools.eval transcribe --audio demo.wav --provider local --model moss-align "
            "--language zh-TW`") in out
    assert "--transcript <基準的 LRC> --vs <這個 PR 的 LRC> --bootstrap 1000" in out
    assert out.rstrip().endswith("- 判定：待回歸判定")


def test_never_prints_any_transcript_or_reference_text(lab, runs, tmp_path, capsys):
    for lrc in runs:
        _manifest(lrc, "1" * 40)
    path = _eval(capsys, tmp_path / "eval.json", *runs)

    _, out, _ = _summary(capsys, path)

    for word in ("我們", "下週", "爬山", "去爬"):
        assert word not in out


def test_single_transcript(lab, runs, tmp_path, capsys):
    _manifest(runs[0], "1" * 40)
    path = _eval(capsys, tmp_path / "eval.json", runs[0])

    _, out, _ = _summary(capsys, path)

    assert "| | 轉錄結果 |" in out
    assert "| 錯字率（MER） | 12.50% |" in out
    assert "ΔMER" not in out
    assert "--vs" not in out


def test_missing_manifest_leaves_blanks_and_says_so(lab, runs, tmp_path, capsys):
    _manifest(runs[1], "2" * 40)
    path = _eval(capsys, tmp_path / "eval.json", *runs)

    _, out, _ = _summary(capsys, path)

    assert f"| commit | — | `{'2' * 12}` |" in out
    assert "| 結尾核對 | 最後一行 0:01 | 最後一行 0:01，音檔 0:30" in out
    assert "找不到 manifest" in out
    assert "demo.lrc" in out


def test_warns_when_the_two_runs_used_different_audio(lab, runs, tmp_path, capsys):
    _manifest(runs[0], "1" * 40, sha256="ab" * 32)
    _manifest(runs[1], "2" * 40, sha256="cd" * 32)
    path = _eval(capsys, tmp_path / "eval.json", *runs)

    _, out, _ = _summary(capsys, path)

    assert "兩邊轉錄的音檔不同" in out


def test_draft_reference_is_flagged(lab, runs, tmp_path, capsys):
    _write(lab / "data" / "eval" / "demo_B.draft.txt",
           f"# demo_B  00:00.00-00:30.00\nA?: {REFERENCE_TEXT}\n")
    path = tmp_path / "eval.json"
    assert cli.main(["eval", "--reference", "demo_B.draft", "--allow-draft",
                     "--transcript", str(runs[0]), "--json", str(path)]) == 0
    capsys.readouterr()

    _, out, _ = _summary(capsys, path)

    assert "- 標準答案：demo_B.draft，草稿標記 1 處：數字只能當工具驗證，不能當結論" in out


def test_relative_transcript_paths_are_found_next_to_the_json(lab, runs, tmp_path, capsys,
                                                              monkeypatch):
    # eval 在 runs 資料夾執行、給相對路徑；summary 在別的地方執行也找得到
    _manifest(runs[0], "1" * 40)
    monkeypatch.chdir(tmp_path / "runs")
    path = _eval(capsys, tmp_path / "runs" / "eval.json", runs[0].relative_to(tmp_path / "runs"))
    monkeypatch.chdir(tmp_path)

    _, out, _ = _summary(capsys, path)

    assert f"| commit | `{'1' * 12}` |" in out


@pytest.mark.parametrize("content", ['{"command": "transcribe"}', "不是 JSON"])
def test_refuses_files_that_are_not_eval_results(tmp_path, capsys, content):
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")

    code, _, err = _summary(capsys, path)

    assert code == 2
    assert str(path) in err


def test_missing_file(tmp_path, capsys):
    code, _, err = _summary(capsys, tmp_path / "nope.json")

    assert code == 2
    assert "找不到 eval 的 JSON" in err
