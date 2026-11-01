"""``python -m tools.eval summary``：把 eval 的 JSON 與兩邊的 manifest 整理成 PR 的評測摘要（#38），
最後照 ADR 0009 判定回歸（#264）。

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
              dirty=False, audio="demo.wav", language="zh-TW"):
    """transcribe 在轉錄結果旁邊寫的 manifest（只留摘要用到的欄位）。"""
    manifest = {
        "command": "transcribe",
        "request": {"provider": "local", "model": "moss-align", "language": language},
        "audio": {"file": audio, "sha256": sha256, "duration_seconds": duration},
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


def _eval(capsys, out, *transcripts, reference="demo_A", extra=()):
    argv = ["eval", "--reference", reference, "--transcript", str(transcripts[0])]
    if len(transcripts) == 2:
        argv += ["--vs", str(transcripts[1])]
    assert cli.main([*argv, *extra, "--json", str(out)]) == 0
    capsys.readouterr()
    return out


def _summary(capsys, *paths):
    code = cli.main(["summary", *map(str, paths)])
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
    assert "| 中文 | demo_A | 8 | 12.50%（1 個錯） → 0.00%（0 個錯） | 12.50%（1 個錯） → 0.00%（0 個錯） | 通過 |" in out
    assert out.rstrip().endswith("- 判定：通過（中文）")


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
    assert "- 沒算進判定：demo.wav（只有一份轉錄結果，沒有基準可比）" in out
    assert out.rstrip().endswith("- 判定：無法判定：沒有已確認的標準答案可以和基準比（有草稿標記的不算）")


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
    assert "- 沒算進判定：demo.wav（兩邊轉錄的音檔不同）" in out
    assert "- 判定：無法判定" in out


def test_draft_reference_is_flagged(lab, runs, tmp_path, capsys):
    _write(lab / "data" / "eval" / "demo_B.draft.txt",
           f"# demo_B  00:00.00-00:30.00\nA?: {REFERENCE_TEXT}\n")
    path = tmp_path / "eval.json"
    assert cli.main(["eval", "--reference", "demo_B.draft", "--allow-draft",
                     "--transcript", str(runs[0]), "--json", str(path)]) == 0
    capsys.readouterr()

    _, out, _ = _summary(capsys, path)

    assert "- 標準答案：demo_B.draft，草稿標記 1 處：數字只能當工具驗證，不能當結論" in out


def test_no_confirmed_reference_means_no_verdict(lab, runs, tmp_path, capsys):
    # 草稿的標準答案就算兩邊都比了，也不拿來判定（#15 的 Q3）
    for lrc in runs:
        _manifest(lrc, "1" * 40)
    _write(lab / "data" / "eval" / "demo_B.draft.txt",
           f"# demo_B  00:00.00-00:30.00\nA?: {REFERENCE_TEXT}\n")
    path = _eval(capsys, tmp_path / "eval.json", *runs, reference="demo_B.draft",
                 extra=["--allow-draft"])

    _, out, _ = _summary(capsys, path)

    assert "| 語言 |" not in out
    assert "- 沒算進判定：demo.wav（標準答案還有 1 處草稿標記）" in out
    assert out.rstrip().endswith("- 判定：無法判定：沒有已確認的標準答案可以和基準比（有草稿標記的不算）")


def test_relative_transcript_paths_are_found_next_to_the_json(lab, runs, tmp_path, capsys,
                                                              monkeypatch):
    # eval 在 runs 資料夾執行、給相對路徑；summary 在別的地方執行也找得到
    _manifest(runs[0], "1" * 40)
    monkeypatch.chdir(tmp_path / "runs")
    path = _eval(capsys, tmp_path / "runs" / "eval.json", runs[0].relative_to(tmp_path / "runs"))
    monkeypatch.chdir(tmp_path)

    _, out, _ = _summary(capsys, path)

    assert f"| commit | `{'1' * 12}` |" in out


def test_same_output_as_the_baseline_passes(lab, runs, tmp_path, capsys):
    # 容忍值是 0：一樣就通過，多一個錯就是回歸（下一個測試）
    for lrc in runs:
        _manifest(lrc, "1" * 40)
    path = _eval(capsys, tmp_path / "eval.json", runs[0], runs[0])

    _, out, _ = _summary(capsys, path)

    assert "| 中文 | demo_A | 8 | 12.50%（1 個錯） → 12.50%（1 個錯） |" in out
    assert out.rstrip().endswith("- 判定：通過（中文）")


def test_higher_mer_than_the_baseline_is_a_regression(lab, runs, tmp_path, capsys):
    for lrc in runs:
        _manifest(lrc, "1" * 40)
    # 這次全對的當基準、漏字的當 PR
    path = _eval(capsys, tmp_path / "eval.json", runs[1], runs[0])

    _, out, _ = _summary(capsys, path)

    assert "| 中文 | demo_A | 8 | 0.00%（0 個錯） → 12.50%（1 個錯） |" in out
    assert "| 回歸 |" in out
    assert out.rstrip().endswith(
        "- 判定：回歸（中文）：代理不合併，等使用者明確接受並在 PR 上記下理由")


def test_higher_cpmer_alone_is_a_regression(lab, tmp_path, capsys):
    # 字全對、只有說話者標錯：錯字率一樣，cpMER 變高，一樣是回歸（#15 的 Q2b）
    _write(lab / "data" / "eval" / "demo_C.txt", "# demo_C  00:00.00-00:30.00\nA: 我們下週二\nB: 去爬山\n")
    base = _write(tmp_path / "runs" / "main" / "demo.lrc",
                  "[00:01.00][S0] 我們下週二\n[00:02.00][S1] 去爬山\n")
    head = _write(tmp_path / "runs" / "pr" / "demo.lrc",
                  "[00:01.00][S0] 我們下週二\n[00:02.00][S0] 去爬山\n")
    for lrc in (base, head):
        _manifest(lrc, "1" * 40)
    path = _eval(capsys, tmp_path / "eval.json", base, head, reference="demo_C")

    _, out, _ = _summary(capsys, path)

    # cpMER 的錯誤數是從 JSON 的比率乘回 token 數還原的，要和 mer 算的一樣：S0 對到 A 最好，
    # A 多了「去爬山」3 個字，B 沒有對到任何標記、3 個字全漏，共 6 個錯
    assert ("| 中文 | demo_C | 8 | 0.00%（0 個錯） → 0.00%（0 個錯） "
            "| 0.00%（0 個錯） → 75.00%（6 個錯） | 回歸 |") in out
    assert out.rstrip().endswith(
        "- 判定：回歸（中文）：代理不合併，等使用者明確接受並在 PR 上記下理由")


def _other_audio(lab, tmp_path, capsys, *, base_text, head_text, language):
    """評測集的另一個音檔：自己的標準答案、兩份轉錄結果與 eval 的 JSON。"""
    _write(lab / "data" / "eval" / "other_A.txt", "# other_A  00:00.00-00:30.00\nA: 東京大学図書館\n")
    lrcs = [_write(tmp_path / "runs" / side / "other.lrc", f"[00:01.00][S0] {text}\n")
            for side, text in (("main", base_text), ("pr", head_text))]
    for lrc in lrcs:
        _manifest(lrc, "1" * 40, sha256="cd" * 32, audio="other.wav", language=language)
    return _eval(capsys, tmp_path / "other.json", *lrcs, reference="other_A")


def test_same_language_is_judged_across_audio_files(lab, runs, tmp_path, capsys):
    # demo：PR 多錯 1 個；other：PR 少錯 2 個。同一種語言合起來，PR 比基準少錯 1 個，通過。
    # 兩個音檔的語言代碼不同（zh-TW、zh-CN），一樣算中文
    for lrc in runs:
        _manifest(lrc, "1" * 40)
    demo = _eval(capsys, tmp_path / "demo.json", runs[1], runs[0])
    other = _other_audio(lab, tmp_path, capsys, base_text="東京大学図", head_text="東京大学図書館",
                         language="zh-CN")

    _, alone, _ = _summary(capsys, demo)
    _, out, _ = _summary(capsys, demo, other)

    assert "- 判定：回歸（中文）" in alone
    assert "### 評測摘要：demo.wav" in out
    assert "### 評測摘要：other.wav" in out
    assert "| 中文 | demo_A、other_A | 15 | 13.33%（2 個錯） → 6.67%（1 個錯） |" in out
    assert out.rstrip().endswith("- 判定：通過（中文）")


def test_speakers_are_paired_within_each_audio_file(lab, tmp_path, capsys):
    # 兩段無關的錄音，字全對，同名的標記指不同的人：demo 的 A 是 S0，other 的 A 是 S1。
    # 每個音檔各自配對都全對；若把兩段一起配對，有一段的說話者會全部配錯（#298）
    _write(lab / "data" / "eval" / "demo_C.txt", "# demo_C  00:00.00-00:30.00\nA: 我們下週二\nB: 去爬山\n")
    _write(lab / "data" / "eval" / "other_C.txt", "# other_C  00:00.00-00:30.00\nA: 要帶水嗎\nB: 當然記得\n")
    transcripts = {
        "demo": "[00:01.00][S0] 我們下週二\n[00:02.00][S1] 去爬山\n",
        "other": "[00:01.00][S1] 要帶水嗎\n[00:02.00][S0] 當然記得\n",
    }
    paths = []
    for (name, text), sha256 in zip(transcripts.items(), ("ab" * 32, "cd" * 32), strict=True):
        lrcs = [_write(tmp_path / "runs" / side / f"{name}.lrc", text) for side in ("main", "pr")]
        for lrc in lrcs:
            _manifest(lrc, "1" * 40, sha256=sha256, audio=f"{name}.wav")
        paths.append(_eval(capsys, tmp_path / f"{name}.json", *lrcs, reference=f"{name}_C"))

    _, out, _ = _summary(capsys, *paths)

    assert ("| 中文 | demo_C、other_C | 16 | 0.00%（0 個錯） → 0.00%（0 個錯） "
            "| 0.00%（0 個錯） → 0.00%（0 個錯） | 通過 |") in out


def test_each_language_is_judged_on_its_own(lab, runs, tmp_path, capsys):
    for lrc in runs:
        _manifest(lrc, "1" * 40)
    chinese = _eval(capsys, tmp_path / "demo.json", *runs)
    japanese = _other_audio(lab, tmp_path, capsys, base_text="東京大学図書館", head_text="東京大学図書",
                            language="ja")

    _, out, _ = _summary(capsys, chinese, japanese)

    assert "| 中文 | demo_A | 8 |" in out
    assert "| 日文 | other_A | 7 | 0.00%（0 個錯） → 14.29%（1 個錯） |" in out
    assert out.rstrip().endswith(
        "- 判定：回歸（日文）：代理不合併，等使用者明確接受並在 PR 上記下理由")


def test_a_run_without_manifests_is_left_out(lab, runs, tmp_path, capsys):
    # 沒有 manifest 就不知道是哪種語言，不能和別的音檔合起來
    path = _eval(capsys, tmp_path / "eval.json", *runs)

    _, out, _ = _summary(capsys, path)

    assert "- 沒算進判定：demo.lrc（找不到 manifest，不知道是哪種語言）" in out
    assert "- 判定：無法判定" in out


def test_cpmer_too_coarse_to_tell_is_undecided(tmp_path, capsys):
    # eval 的 JSON 只存 cpMER 的比率（小數第四位）：一段有 30000 個 token 時，0.1000 可能是
    # 2999～3001 個錯，兩邊都寫 0.1000 就分不出 PR 有沒有比基準多錯
    systems = []
    for side in ("main", "pr"):
        lrc = _write(tmp_path / side / "long.lrc", "[00:01.00][S0] 略\n")
        _manifest(lrc, "1" * 40, audio="long.wav")
        excerpt = {"name": "long_A", "subs": 100, "dels": 0, "ins": 0, "ref_len": 30000,
                   "cp_mer_global": 0.1}
        systems.append({"transcript": str(lrc), "per_excerpt": [excerpt],
                        "total_mer": 0.0033, "cp_mer_global": 0.1})
    path = tmp_path / "eval.json"
    path.write_text(json.dumps({"command": "eval", "reference": ["long_A.txt"],
                                "reference_draft_marks": 0, "bootstrap": 1000,
                                "systems": systems, "paired": None}), encoding="utf-8")

    _, out, _ = _summary(capsys, path)

    assert "| 10.00%（2999～3001 個錯） → 10.00%（2999～3001 個錯） | 無法判定 |" in out
    assert out.rstrip().endswith(
        "- 判定：無法判定（中文）：JSON 裡的 cpMER 只到小數第四位，分不出有沒有比基準高；代理不合併，交給使用者")


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
