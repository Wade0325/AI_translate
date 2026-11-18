"""逐句校對（``python -m tools.eval proofread``）：一個模型的轉錄結果寫成標準答案的草稿與校對頁，
使用者每一句都聽過、改好，再確認成標準答案（ADR 0009）。

例句全是自造的，不取自任何真實錄音（tools/eval/README.md）。
"""
import json
import textwrap
import wave
from datetime import date
from pathlib import Path

import pytest

from tools.eval import cli, lrc, proofread, reference_set
from tools.eval.cli import UsageError

FIRST = """
    [00:01.20][S1] 今天天氣很好。
    [00:03.50][S0] 我們去爬山吧。
    [00:06.00][S1] 好啊，要帶雨傘嗎？
    [00:09.75][S2] 不用，下午就放晴了。
"""
SECOND = """
    [00:00.80][S1] 今天天氣很好
    [00:03.40][S0] 我們去爬山吧
    [00:06.10][S1] 好啊要帶雨傘嗎
    [00:08.00][S1] 嗯
    [00:09.70][S2] 不用下午就放情了
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


def _wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))
    return path


@pytest.fixture
def lab(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    (root / "data" / "eval").mkdir(parents=True)
    monkeypatch.setenv("AIT_LAB_DIR", str(root))
    return root


def _draft(tmp_path, first=FIRST, second=SECOND, start=0.0, end=12.0, private=False):
    a = _write(tmp_path / "moss-align" / "x.lrc", first)
    b = None if second is None else lrc.read(_write(tmp_path / "moss-qwen3-asr" / "x.lrc", second))
    return proofread.build_draft("demo_P", start, end, lrc.read(a), b, private=private)


# ------------------------------------------------------------------ 草稿
def test_speakers_become_letters_in_order_of_appearance(tmp_path):
    draft = _draft(tmp_path)

    assert [r.speaker for r in draft.rows] == ["A", "B", "A", "C"]
    assert draft.speakers == {"A": "S1", "B": "S0", "C": "S2"}


def test_lines_without_a_speaker_label_count_as_one_speaker(tmp_path):
    draft = _draft(tmp_path, first="""
        [00:01.00] 沒有標記的一行
        [00:02.00][S0] 有標記的一行
        [00:03.00] 又一行沒有標記
    """, second=None)

    assert [r.speaker for r in draft.rows] == ["A", "B", "A"]
    assert draft.speakers == {"A": "無標記", "B": "S0"}
    assert all(r.alt is None and not r.alt_differs for r in draft.rows)


def test_more_than_26_speakers_keep_valid_codes():
    codes = proofread.speaker_codes([f"S{i}" for i in range(28)])

    assert codes["S25"] == "Z"
    assert codes["S26"] == "S27"
    assert reference_set.UTT_RE.match(f"{codes['S27']}: 文字")


def test_second_hypothesis_lines_go_to_the_line_whose_time_they_fall_in(tmp_path):
    draft = _draft(tmp_path)

    # 歸時間重疊最多的一句：第二假設早 0.1 秒開始的「我們去爬山吧」照樣歸第二句，00:08.00 的「嗯」
    # 落在第三句的時間裡
    assert [r.alt for r in draft.rows] == ["今天天氣很好", "我們去爬山吧", "好啊要帶雨傘嗎 嗯",
                                          "不用下午就放情了"]


def test_second_hypothesis_lines_outside_every_line_go_to_the_nearest(tmp_path):
    draft = _draft(tmp_path, end=20.0, second="""
        [00:00.00][S1] 嗯
        [00:15.00][S2] 最後
    """)

    # 「嗯」在第一句之前結束，「最後」在最後一句之後很久才開始：都歸最近的一句
    assert [r.alt for r in draft.rows] == ["嗯", "", "", "最後"]


def test_only_differences_that_count_are_marked(tmp_path):
    draft = _draft(tmp_path)

    # 標點不同不算；多了「嗯」是語助詞，計分時也去掉；「放晴」與「放情」不同
    assert [r.alt_differs for r in draft.rows] == [False, False, False, True]


def test_a_line_with_nothing_from_the_second_hypothesis_is_marked_when_it_has_words(tmp_path):
    draft = _draft(tmp_path, second="""
        [00:00.50][S0] 今天天氣很好我們去爬山吧
    """)

    assert draft.rows[1].alt == ""
    assert draft.rows[1].alt_differs


def test_lines_outside_the_range_are_left_out(tmp_path):
    draft = _draft(tmp_path, start=3.0, end=9.75)

    assert [r.text for r in draft.rows] == ["我們去爬山吧。", "好啊，要帶雨傘嗎？"]
    # 代號照範圍內第一次出現的順序編
    assert [r.speaker for r in draft.rows] == ["A", "B"]


def test_an_empty_range_is_refused(tmp_path):
    with pytest.raises(UsageError, match="沒有任何一行"):
        _draft(tmp_path, start=20.0, end=30.0)


@pytest.mark.parametrize("name", ["demo P", "../demo", "名稱/斜線", ""])
def test_names_the_header_cannot_read_are_refused(tmp_path, name):
    a = _write(tmp_path / "x.lrc", FIRST)
    with pytest.raises(UsageError, match="--name"):
        proofread.build_draft(name, 0, 12, lrc.read(a))


def test_draft_text_is_a_reference_with_every_line_marked(tmp_path):
    draft = _draft(tmp_path, private=True)
    systems = [{"label": "moss-align", "sha256": "a" * 64}, {"label": "moss-qwen3-asr", "sha256": "b" * 64}]
    path = tmp_path / "demo_P.draft.txt"
    path.write_text(proofread.draft_text(draft, systems), encoding="utf-8")

    with pytest.raises(reference_set.ReferenceSetError, match="4 處草稿標記"):
        reference_set.read_reference(path)
    excerpt = reference_set.read_reference(path, allow_draft=True)
    assert (excerpt.name, excerpt.start, excerpt.end, excerpt.private) == ("demo_P", 0.0, 12.0, True)
    assert [(u.speaker, u.text) for u in excerpt.utterances] == [
        ("A", "今天天氣很好。"), ("B", "我們去爬山吧。"), ("A", "好啊，要帶雨傘嗎？"), ("C", "不用，下午就放晴了。")]
    text = path.read_text(encoding="utf-8")
    assert "[00:01.20] A?: 今天天氣很好。" in text
    assert "草稿 moss-align（SHA-256 aaaaaaaaaaaa）、對照 moss-qwen3-asr（SHA-256 bbbbbbbbbbbb）" in text


@pytest.mark.parametrize(("seconds", "text"), [
    (0, "00:00.00"), (61.5, "01:01.50"), (1836.47, "30:36.47"), (3749.829, "62:29.82"), (5.999, "00:05.99"),
])
def test_clock_truncates_to_hundredths(seconds, text):
    assert proofread.clock(seconds) == text


def test_range_from_wav_header_is_truncated(tmp_path):
    wav = _wav(tmp_path / "a.wav", 12.3456)

    assert proofread.wav_seconds(wav) == 12.34


@pytest.mark.parametrize("text", ["0:00-", "1:00-0:30", "abc"])
def test_bad_ranges_are_refused(text):
    with pytest.raises(UsageError, match="--range"):
        proofread.parse_range(text)


# ------------------------------------------------------------------ 指令
def _cli_draft(tmp_path, out, *extra):
    a = _write(tmp_path / "moss-align" / "x.lrc", FIRST)
    b = _write(tmp_path / "moss-qwen3-asr" / "x.lrc", SECOND)
    wav = _wav(tmp_path / "audio" / "x.wav", 12.0)
    return cli.main(["proofread", "draft", "--transcript", str(a), "--second-hypothesis", str(b),
                     "--audio", str(wav), "--name", "demo_P", "--out", str(out), *extra])


def test_draft_writes_page_data_and_draft_but_prints_only_numbers(tmp_path, lab, capsys):
    out = tmp_path / "proof"
    assert _cli_draft(tmp_path, out, "--private") == 0

    printed = capsys.readouterr().out
    assert "4 句、3 位說話者" in printed
    assert "和 moss-qwen3-asr 寫法不同的句子：1" in printed
    assert "爬山" not in printed and "雨傘" not in printed
    payload = json.loads((out / "demo_P.proofread.json").read_text(encoding="utf-8"))
    assert payload["header"] == "# demo_P  00:00.00-00:12.00"
    assert payload["private"] is True
    assert payload["audio"]["src"] == "../audio/x.wav"
    assert [s["label"] for s in payload["systems"]] == ["moss-align", "moss-qwen3-asr"]
    assert len(payload["rows"]) == 4
    page = (out / "demo_P.proofread.html").read_text(encoding="utf-8")
    assert payload["digest"] in page and "__DATA__" not in page
    draft = reference_set.read_reference(out / "demo_P.draft.txt", allow_draft=True)
    assert draft.private and len(draft.utterances) == 4


def test_draft_refuses_to_write_into_references_or_over_old_results(tmp_path, lab, capsys):
    assert _cli_draft(tmp_path, lab / "data" / "eval" / "drafts") == 2
    assert "不能寫進標準答案的資料夾" in capsys.readouterr().err
    out = tmp_path / "proof"
    assert _cli_draft(tmp_path, out) == 0
    assert _cli_draft(tmp_path, out) == 2
    assert "不覆寫" in capsys.readouterr().err


def test_draft_without_a_wav_needs_a_range(tmp_path, lab, capsys):
    a = _write(tmp_path / "moss-align" / "x.lrc", FIRST)
    argv = ["proofread", "draft", "--transcript", str(a), "--name", "demo_P", "--out", str(tmp_path / "o")]

    assert cli.main(argv) == 2
    assert "--range" in capsys.readouterr().err
    assert cli.main([*argv, "--range", "00:00.00-00:07.00"]) == 0
    payload = json.loads((tmp_path / "o" / "demo_P.proofread.json").read_text(encoding="utf-8"))
    assert payload["audio"] is None and len(payload["rows"]) == 3


def test_page_embeds_the_data_safely(tmp_path):
    draft = _draft(tmp_path, first="[00:01.00][S0] </script><b>不能提早結束</b>\n", second=None)
    payload = proofread.to_payload(draft, [{"label": "x", "path": "x", "sha256": "0" * 64}], None, tmp_path)

    page = proofread.render_page(payload)
    assert "</script><b>" not in page
    embedded = page.split('<script id="data" type="application/json">')[1].split("</script>")[0]
    assert json.loads(embedded)["rows"][0]["text"] == "</script><b>不能提早結束</b>"


# ------------------------------------------------------------------ 確認
DOWNLOADED = """
    # demo_P  00:00.00-00:12.00
    # 不公開
    # A=甲 B=乙
    # 逐句校對：草稿 moss-align（SHA-256 aaaaaaaaaaaa）；共 3 句，已確認 3 句

    [00:01.20] A: 今天天氣很好。
    [00:03.50] B: 我們去爬山吧。
    [00:08.00] ~A: 嗯
"""


def test_finalize_records_who_confirmed_before_the_first_line():
    text = proofread.finalize(textwrap.dedent(DOWNLOADED).lstrip(), "x", "Wade", on=date(2026, 11, 19))

    lines = text.splitlines()
    assert lines[4] == "# 確認：Wade，2026-11-19"
    assert lines[5] == ""
    assert lines[6].startswith("[00:01.20] A:")


def test_finalize_writes_a_reference_the_evaluation_reads(tmp_path, lab, capsys):
    src = _write(tmp_path / "dl" / "demo_P.proofread.txt", DOWNLOADED)
    out = tmp_path / "final"

    assert cli.main(["proofread", "finalize", "--draft", str(src), "--confirmed-by", "Wade",
                     "--out", str(out)]) == 0
    excerpt = reference_set.read_reference(out / "demo_P.txt")
    assert excerpt.private and len(excerpt.utterances) == 3 and excerpt.utterances[2].overlap
    assert "# 確認：Wade，" in (out / "demo_P.txt").read_text(encoding="utf-8")
    assert "今天" not in capsys.readouterr().out
    assert cli.main(["proofread", "finalize", "--draft", str(src), "--confirmed-by", "Wade",
                     "--out", str(out)]) == 2
    assert "不覆寫" in capsys.readouterr().err


def test_finalize_refuses_lines_still_marked_as_draft(tmp_path, lab, capsys):
    src = _write(tmp_path / "demo_P.proofread.txt", DOWNLOADED.replace("B: 我們", "B?: 我們"))

    assert cli.main(["proofread", "finalize", "--draft", str(src), "--confirmed-by", "Wade",
                     "--out", str(tmp_path / "final")]) == 2
    assert "1 處草稿標記" in capsys.readouterr().err
    assert not (tmp_path / "final").exists()


def test_finalize_refuses_to_confirm_twice():
    once = proofread.finalize(textwrap.dedent(DOWNLOADED).lstrip(), "x", "Wade")

    with pytest.raises(UsageError, match="不重複確認"):
        proofread.finalize(once, "x", "Wade")


def test_finalize_does_not_write_into_references(tmp_path, lab, capsys):
    src = _write(tmp_path / "demo_P.proofread.txt", DOWNLOADED)

    assert cli.main(["proofread", "finalize", "--draft", str(src), "--confirmed-by", "Wade",
                     "--out", str(lab / "data" / "eval")]) == 2
    assert "不能寫進標準答案的資料夾" in capsys.readouterr().err
