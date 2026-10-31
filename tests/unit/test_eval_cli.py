"""評測工具（tools/eval）的指令：``python -m tools.eval eval|selftest``。

標準答案與術語表留在研究區（repo 外，和主 checkout 同一層的 ``<主 checkout>-lab/``），不進
版控；這裡用 tmp 裡自造的假研究區。工具只讀取標準答案，不寫入。
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tools.eval import cli

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """假研究區：data/eval 放標準答案，glossaries 放術語表。"""
    root = tmp_path / "lab"
    (root / "data" / "eval").mkdir(parents=True)
    (root / "glossaries").mkdir()
    monkeypatch.setenv("AIT_LAB_DIR", str(root))
    return root


def _write(path, text):
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


def _reference(lab, name, body):
    return _write(lab / "data" / "eval" / f"{name}.txt", body)


@pytest.fixture
def transcript(tmp_path):
    # 標準答案 8 個 token（我們下週二去爬山），轉錄結果漏了「山」：錯字率 1/8
    return _write(tmp_path / "transcript.lrc", """
        [00:01.00][S0] 我們下週二去爬
        [00:40.00][S0] 範圍外的行不計分
    """)


def test_selftest_passes(capsys):
    assert cli.main(["selftest"]) == 0
    assert "整體：PASS" in capsys.readouterr().out


def test_runs_as_module_from_repo_root():
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, "-m", "tools.eval", "selftest"], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", env=env)
    assert done.returncode == 0, done.stdout + done.stderr


def test_eval_finds_draft_reference_by_name_in_lab(lab, transcript, capsys):
    _reference(lab, "demo_A.draft", """
        # demo_A  00:00.00-00:30.00
        A: 我們下週二去爬山
    """)

    code = cli.main(["eval", "--reference", "demo_A.draft", "--transcript", str(transcript)])

    out = capsys.readouterr().out
    assert code == 0
    assert "MER             12.50%" in out
    assert "(替換 0 / 漏 1 / 插 0)" in out
    assert "對應 S0→A" in out


def test_missing_reference_lists_what_is_there(lab, transcript, capsys):
    _reference(lab, "demo_A.draft", "# demo_A  00:00.00-00:30.00\nA: 有\n")

    code = cli.main(["eval", "--reference", "demo_A", "--transcript", str(transcript)])

    err = capsys.readouterr().err
    assert code == 2
    assert "demo_A.txt" in err
    assert "demo_A.draft" in err


def test_reference_dir_option_overrides_lab(tmp_path, lab, transcript, capsys):
    other = tmp_path / "elsewhere"
    other.mkdir()
    _write(other / "demo_B.txt", "# demo_B  00:00.00-00:30.00\nA: 我們下週二去爬\n")

    code = cli.main(["eval", "--reference-dir", str(other), "--reference", "demo_B",
                     "--transcript", str(transcript)])

    assert code == 0
    assert "MER              0.00%" in capsys.readouterr().out


def test_draft_reference_is_refused_unless_allowed(lab, transcript, capsys):
    _reference(lab, "demo_A.draft", """
        # demo_A  00:00.00-00:30.00
        A?: 我們下週二去爬山
    """)
    argv = ["eval", "--reference", "demo_A.draft", "--transcript", str(transcript)]

    assert cli.main(argv) == 2
    assert "草稿標記" in capsys.readouterr().err
    assert cli.main([*argv, "--allow-draft"]) == 0
    assert "草稿" in capsys.readouterr().out


def test_vocabulary_by_name_reports_term_recall(tmp_path, lab, capsys):
    _reference(lab, "demo_A", """
        # demo_A  00:00.00-00:30.00
        A: 先安裝 Docker 再重開
    """)
    _write(lab / "glossaries" / "tools.json", '{"terms": ["Docker"], "zh_terms": ["安裝"]}')
    lrc = _write(tmp_path / "transcript.lrc", "[00:01.00][S0] 先安裝 doctor 再重開\n")
    out_json = tmp_path / "out" / "result.json"

    code = cli.main(["eval", "--reference", "demo_A", "--transcript", str(lrc),
                     "--vocabulary", "tools", "--json", str(out_json)])

    assert code == 0
    assert "術語召回          50.0%   (1/2)" in capsys.readouterr().out
    result = json.loads(out_json.read_text(encoding="utf-8"))
    [excerpt] = result["systems"][0]["per_excerpt"]
    assert (excerpt["term_hit"], excerpt["term_total"]) == (1, 2)
    assert excerpt["budget"]["術語拼寫"] == 1
    assert result["vocabulary"] == ["tools.json"]


def test_vs_compares_two_transcripts(tmp_path, lab, transcript, capsys):
    _reference(lab, "demo_A", "# demo_A  00:00.00-00:30.00\nA: 我們下週二去爬山\n")
    better = _write(tmp_path / "better.lrc", "[00:01.00][S1] 我們下週二去爬山\n")

    code = cli.main(["eval", "--reference", "demo_A", "--transcript", str(transcript), "--vs", str(better)])

    out = capsys.readouterr().out
    assert code == 0
    assert "成對比較（better.lrc − transcript.lrc）" in out
    assert "ΔMER -12.50 pp" in out


def test_global_mapping_is_shared_by_the_excerpts_of_one_transcript(tmp_path, lab, capsys):
    # 同一個音檔切成兩段標準答案，代號一致（A 都是同一個人）；轉錄結果前一段把 A 標成 S0、
    # 後一段標成 S1。每段各自配對都全對，共用一組對應時有一段配錯：這就是全域對應要量的（#93）
    _reference(lab, "demo_A", "# demo_A  00:00.00-00:10.00\nA: 我們下週二\nB: 去爬山\n")
    _reference(lab, "demo_B", "# demo_B  00:10.00-00:20.00\nA: 要帶水嗎\nB: 當然記得\n")
    lrc = _write(tmp_path / "demo.lrc", """
        [00:01.00][S0] 我們下週二
        [00:05.00][S1] 去爬山
        [00:11.00][S1] 要帶水嗎
        [00:15.00][S0] 當然記得
    """)
    out_json = tmp_path / "eval.json"

    assert cli.main(["eval", "--reference", "demo_A", "demo_B", "--transcript", str(lrc),
                     "--json", str(out_json)]) == 0

    out = capsys.readouterr().out
    [system] = json.loads(out_json.read_text(encoding="utf-8"))["systems"]
    assert [e["cp_mer_local"] for e in system["per_excerpt"]] == [0.0, 0.0]
    assert system["global_mapping"] == {"S0": "A", "S1": "B"}
    # 後一段照全域對應：A 對到 S0、B 對到 S1，兩組的 4 個字各錯 4 個，8 個錯 ÷ 8 個 token
    assert [e["cp_mer_global"] for e in system["per_excerpt"]] == [0.0, 1.0]
    assert "← 說話者標記在這幾段之間不一致" in out


def test_never_writes_into_the_reference_dir(lab, transcript, capsys):
    reference = _reference(lab, "demo_A", "# demo_A  00:00.00-00:30.00\nA: 我們下週二去爬山\n")
    before = reference.read_bytes()

    for target in (reference, lab / "data" / "eval" / "result.json"):
        code = cli.main(["eval", "--reference", "demo_A", "--transcript", str(transcript),
                         "--json", str(target)])
        assert code == 2
        assert "標準答案" in capsys.readouterr().err

    assert reference.read_bytes() == before
    assert sorted(p.name for p in (lab / "data" / "eval").iterdir()) == ["demo_A.txt"]



def test_never_writes_into_the_lab_references_even_when_reading_elsewhere(
        tmp_path, lab, transcript, capsys):
    reference = _reference(lab, "demo_A", "# demo_A  00:00.00-00:30.00\nA: 我們下週二去爬山\n")
    before = reference.read_bytes()
    other = tmp_path / "elsewhere"
    other.mkdir()
    _write(other / "demo_B.txt", "# demo_B  00:00.00-00:30.00\nA: 我們下週二去爬\n")

    code = cli.main(["eval", "--reference-dir", str(other), "--reference", "demo_B",
                     "--transcript", str(transcript), "--json", str(reference)])

    assert code == 2
    assert "標準答案" in capsys.readouterr().err
    assert reference.read_bytes() == before


def test_warns_when_transcript_has_no_speaker_labels(tmp_path, lab, capsys):
    _reference(lab, "demo_A", "# demo_A  00:00.00-00:30.00\nA: 我們下週二去爬山\n")
    lrc = _write(tmp_path / "gemini.lrc", "[00:01.00] 我們下週二去爬山\n")

    assert cli.main(["eval", "--reference", "demo_A", "--transcript", str(lrc)]) == 0
    out = capsys.readouterr().out
    assert "1 行沒有說話者標記" in out
    assert "MER              0.00%" in out


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_default_lab_sits_beside_the_main_checkout_even_from_a_worktree(tmp_path, monkeypatch):
    monkeypatch.delenv("AIT_LAB_DIR", raising=False)
    main = tmp_path / "AI_translate"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git("-c", "user.name=t", "-c", "user.email=t@example.com",
         "commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    worktree = tmp_path / "wt" / "feature"
    _git("worktree", "add", "-q", str(worktree), cwd=main)

    assert cli.default_lab_dir(worktree).resolve() == (tmp_path / "AI_translate-lab").resolve()
    assert cli.default_lab_dir(main).resolve() == (tmp_path / "AI_translate-lab").resolve()


def test_lab_dir_env_overrides_default(tmp_path, monkeypatch):
    monkeypatch.setenv("AIT_LAB_DIR", str(tmp_path / "my-lab"))

    assert cli.default_lab_dir(ROOT) == tmp_path / "my-lab"
