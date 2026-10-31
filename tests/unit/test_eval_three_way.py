"""三方對照（``python -m tools.eval three-way``）：底稿和兩個本機模型的轉錄結果逐句比對，列出不一致的
地方給使用者聽，再把決定套回成標準答案（ADR 0009、#15 Q5、#273）。

例句全是自造的，不取自任何真實錄音（tools/eval/README.md）。
"""
import json
import textwrap
from datetime import date
from pathlib import Path

import pytest

from tools.eval import cli, mer, reference_set, three_way
from tools.eval.cli import UsageError


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


@pytest.fixture
def lab(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    (root / "data" / "eval").mkdir(parents=True)
    monkeypatch.setenv("AIT_LAB_DIR", str(root))
    return root


def _compare(tmp_path, source, first, second):
    src = _write(tmp_path / "src" / "底稿.txt", source)
    a = _write(tmp_path / "moss-align" / "x.lrc", first)
    b = _write(tmp_path / "moss-qwen3-asr" / "x.lrc", second)
    s = three_way.read_source(src)
    return three_way.compare(s, three_way.read_transcript(a, s.start, s.end),
                             three_way.read_transcript(b, s.start, s.end))


# ------------------------------------------------------------------ 正規化
@pytest.mark.parametrize("text", [
    "我們下週二去爬山。",
    "要帶雨傘嗎？嗯",
    "天気が良ければ散歩に行きます（笑）",
    "用 Docker 跑 S Q L 查詢 9 次",
    "ＡＢＣ　全形英數字１２３",
    "他說[聽不清]然後(?)走了",
    "看著、看着",
    "東京タワーー々ゝ・ラジオ",
    "【拍手】それでは[掌聲]開始",
])
def test_offsets_give_the_same_tokens_as_scoring(text):
    tokens = three_way.tokenize_with_offsets(text, 0)

    assert [t.text for t in tokens] == mer.tokenize(text)
    for t in tokens:
        assert mer.tokenize(text[t.start:t.end], drop_fillers=False) == [t.text]


def test_offsets_cover_spelled_letters_and_full_width_text():
    text = "先裝 S Q L 再用ＡＰＩ"
    by_text = {t.text: text[t.start:t.end] for t in three_way.tokenize_with_offsets(text, 0)}

    assert by_text["sql"] == "S Q L"
    assert by_text["api"] == "ＡＰＩ"


# ------------------------------------------------------------------ 比對
SOURCE = """
    # demo_A  00:00.00-01:00.00
    # A=主持人 B=來賓

    [00:01.00] A: 我們下週二去爬山。
    [00:05.00] B: 要帶雨傘嗎？
    A: 天気が良ければ散歩に行きます。
"""


def test_differences_that_do_not_count_are_not_listed(tmp_path):
    # 標點、繁簡、語助詞、括號標註的非語言聲都不影響錯字率
    same = """
        [00:01.00][S0] 我们下周二去爬山
        [00:05.00][S1] 嗯，要带雨伞吗
        [00:09.00][S0] 天気が良ければ（笑）散歩に行きます！
    """
    result = _compare(tmp_path, SOURCE, same, same)

    assert result.spots == []
    assert result.counts()["tokens"] == len(mer.tokenize("我們下週二去爬山要帶雨傘嗎天気が良ければ散歩に行きます"))


def test_each_kind_of_disagreement_is_categorized(tmp_path):
    first = """
        [00:01.00][S0] 我們下週二去爬山。
        [00:05.00][S1] 要帶雨傘吧？
        [00:09.00][S0] 天気がよければ散歩に行きます。
    """
    second = """
        [00:01.00][S0] 我們夏洲二去爬山。
        [00:05.00][S1] 要帶雨傘嘛？
        [00:09.00][S0] 天気がよければ散歩に行きます。
    """
    result = _compare(tmp_path, SOURCE, first, second)

    found = [(s.category, s.source.text, s.first.text, s.second.text) for s in result.spots]
    assert found == [
        ("source_with_one", "下週", "下週", "夏洲"),
        ("all_differ", "嗎", "吧", "嘛"),
        ("models_agree", "良", "よ", "よ"),
    ]
    assert result.counts() | {"tokens": 0} == {
        "lines": 3, "tokens": 0, "spots": 3, "models_agree": 1, "all_differ": 1, "source_with_one": 1}


def test_words_the_source_lacks_are_listed_with_an_empty_source(tmp_path):
    both = """
        [00:01.00][S0] 我們下週二去爬山。
        [00:05.00][S1] 要帶雨傘嗎？好啊
        [00:09.00][S0] 天気が良ければ散歩に行きます。
    """
    result = _compare(tmp_path, SOURCE, both, both)

    [spot] = result.spots
    assert (spot.category, spot.line, spot.source.text, spot.first.text) == ("models_agree", 1, "", "好")
    # 插入點在底稿這一句「嗎」的後面
    assert spot.source.start == spot.source.end == "要帶雨傘嗎".__len__()


@pytest.mark.parametrize("first_line, second_line, line, at", [
    # 多出來的「你」和下一句的「要」在轉錄結果的同一行：算第二句的開頭
    ("我們下週二去爬山", "你要帶雨傘嗎？", 1, 0),
    # 多出來的「吧」在上一行的結尾：算第一句的結尾
    ("我們下週二去爬山吧", "要帶雨傘嗎？", 0, len("我們下週二去爬山")),
])
def test_words_between_two_source_lines_go_with_their_lrc_line(tmp_path, first_line, second_line, line, at):
    lrc = f"""
        [00:01.00][S0] {first_line}
        [00:05.00][S1] {second_line}
        [00:09.00][S0] 天気が良ければ散歩に行きます。
    """
    result = _compare(tmp_path, SOURCE, lrc, lrc)

    [spot] = result.spots
    assert (spot.line, spot.source.start, spot.source.end) == (line, at, at)


def test_unclear_in_the_source_matches_anything(tmp_path):
    source = """
        # demo_B  00:00.00-00:30.00
        A: 他說[聽不清]然後走了
    """
    result = _compare(tmp_path, source, "[00:01.00][S0] 他說好的然後走了\n",
                      "[00:01.00][S0] 他說喔然後走了\n")

    assert result.spots == []


@pytest.mark.parametrize("next_line, per_char", [
    ("00:12.00", 0.25),  # 8 個字在 10～12 秒之間：每字 0.25 秒
    ("00:14.00", 0.4),   # 每字 0.5 秒，但最多算 0.4 秒（中間多半是靜音）
])
def test_spot_time_is_interpolated_inside_the_lrc_line(tmp_path, next_line, per_char):
    source = """
        # demo_C  00:00.00-00:30.00
        A: 一二三四五六七八
        A: 下一行
    """
    lrc = f"[00:10.00][S0] 一二三四五六七錯\n[{next_line}][S0] 下一行\n"
    result = _compare(tmp_path, source, lrc, lrc)

    [spot] = result.spots
    assert spot.seconds == pytest.approx(10 + 7 * per_char)
    assert spot.end_seconds == pytest.approx(10 + 8 * per_char)


def test_words_both_models_dropped_use_the_source_line_time(tmp_path):
    # 兩個模型在 10 秒之後都沒有轉出字：只能靠底稿每一句的時間戳定位，
    # 不能全部掛在模型最後一個字（10 秒多）上
    source = """
        # demo_E  00:00.00-01:00.00
        [00:10.00] A: 我們下週二去爬山
        [00:20.00] B: 大家早安
        [00:30.00] A: 一二三四五六七八
        [00:40.00] B: 好
    """
    lrc = "[00:10.00][S0] 我們下週二去爬山\n[00:30.00][S0] 一二三四五六七\n"
    result = _compare(tmp_path, source, lrc, lrc)

    assert [(s.line, s.category) for s in result.spots] == [
        (1, "models_agree"), (2, "models_agree"), (3, "models_agree")]
    assert [(s.seconds, s.end_seconds) for s in result.spots] == [
        pytest.approx((20, 21.6)),        # 整句：4 個字，每字最多算 0.4 秒
        pytest.approx((30 + 7 * 0.4, 30 + 8 * 0.4)),  # 句尾一個字：照字數內插
        pytest.approx((40, 40.4)),        # 最後一句：一個字
    ]


def test_words_both_models_dropped_fall_back_to_the_model_time_without_timestamps(tmp_path):
    source = """
        # demo_F  00:00.00-01:00.00
        A: 一二三四五六七八
    """
    lrc = "[00:10.00][S0] 一二三四五六七\n"
    result = _compare(tmp_path, source, lrc, lrc)

    [spot] = result.spots
    assert (spot.seconds, spot.end_seconds) == pytest.approx((10 + 7 * 0.4, 10 + 7 * 0.4))


def test_lines_outside_the_source_window_are_ignored(tmp_path):
    source = """
        # demo_D  00:10.00-00:20.00
        A: 我們下週二去爬山
    """
    lrc = "[00:05.00][S0] 範圍外\n[00:11.00][S0] 我們下週二去爬山\n[00:25.00][S0] 範圍外\n"
    assert _compare(tmp_path, source, lrc, lrc).spots == []


# ------------------------------------------------------------------ 指令
def _cli_files(tmp_path, lab):
    src = _write(lab / "data" / "eval" / "sources" / "demo_A" / "底稿.txt", SOURCE)
    first = _write(tmp_path / "runs" / "moss-align" / "x.lrc", "[00:01.00][S0] 我們夏洲二去爬山\n")
    second = _write(tmp_path / "runs" / "moss-qwen3-asr" / "x.lrc", "[00:01.00][S0] 我們夏洲二去爬山\n")
    audio = lab / "data" / "audio" / "demo A.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"RIFF")
    return src, first, second, audio


def test_compare_writes_list_and_page_but_prints_only_numbers(tmp_path, lab, capsys):
    src, first, second, audio = _cli_files(tmp_path, lab)
    out = lab / "runs" / "273" / "three-way"

    code = cli.main(["three-way", "compare", "--source", str(src), "--transcript", str(first),
                     "--second-hypothesis", str(second), "--audio", str(audio), "--out", str(out)])

    printed = capsys.readouterr().out
    assert code == 0
    assert "不一致 3 處" in printed  # 夏洲；第二、三句兩個模型都沒有
    assert "兩個模型一致、底稿不同：3" in printed
    for sentence in ("我們", "夏洲", "雨傘", "天気"):
        assert sentence not in printed
    payload = json.loads((out / "demo_A.three-way.json").read_text(encoding="utf-8"))
    assert [s["category"] for s in payload["spots"]] == ["models_agree"] * 3
    assert [s["label"] for s in payload["systems"]] == ["moss-align", "moss-qwen3-asr"]
    assert payload["audio"]["src"] == "../../../data/audio/demo%20A.wav"
    assert (out / "demo_A.three-way.html").is_file()


def test_model_label_comes_from_the_transcribe_manifest(tmp_path):
    lrc = _write(tmp_path / "run1" / "x.lrc", "[00:01.00][S0] 好\n")
    _write(tmp_path / "run1" / "x.manifest.json", '{"request": {"model": "moss-qwen3-asr"}}')

    assert three_way.read_transcript(lrc, 0, 10).label == "moss-qwen3-asr"


def test_compare_refuses_to_write_into_references_or_over_old_results(tmp_path, lab, capsys):
    src, first, second, _ = _cli_files(tmp_path, lab)
    argv = ["three-way", "compare", "--source", str(src), "--transcript", str(first),
            "--second-hypothesis", str(second), "--out"]

    assert cli.main([*argv, str(lab / "data" / "eval" / "drafts")]) == 2
    assert "不能寫進標準答案的資料夾" in capsys.readouterr().err
    out = tmp_path / "out"
    assert cli.main([*argv, str(out)]) == 0
    assert cli.main([*argv, str(out)]) == 2
    assert "不覆寫" in capsys.readouterr().err


def test_page_embeds_the_data_safely():
    payload = {"name": "demo<1>", "digest": "d", "source": {"sha256": "s"},
               "spots": [], "lines": [{"speaker": "A", "text": "</script><b>", "seconds": None}]}

    page = three_way.render_page(payload)

    template = three_way.PAGE_TEMPLATE.read_text(encoding="utf-8")
    assert page.count("</script>") == template.count("</script>")
    assert "<title>三方對照 demo&lt;1&gt;</title>" in page
    start = page.index('<script id="data" type="application/json">') + len('<script id="data" type="application/json">')
    embedded = page[start:page.index("</script>", start)]
    assert json.loads(embedded) == payload


# ------------------------------------------------------------------ 套用決定
@pytest.fixture
def compared(tmp_path, lab):
    first = """
        [00:01.00][S0] 我們下週二去爬山。
        [00:05.00][S1] 要帶雨傘吧？
        [00:09.00][S0] 天気がよければ散歩に行きます。
    """
    second = """
        [00:01.00][S0] 我們夏洲二去爬山。
        [00:05.00][S1] 要帶雨傘嘛？
        [00:09.00][S0] 天気がよければ散歩に行きます。
    """
    src, a, b, _ = _cli_files(tmp_path, lab)
    _write(a, first)
    _write(b, second)
    out = tmp_path / "three-way"
    assert cli.main(["three-way", "compare", "--source", str(src), "--transcript", str(a),
                     "--second-hypothesis", str(b), "--out", str(out)]) == 0
    spots = out / "demo_A.three-way.json"
    return spots, json.loads(spots.read_text(encoding="utf-8"))


def _decide(tmp_path, payload, decisions):
    return _write(tmp_path / "decisions.json",
                  json.dumps({"name": payload["name"], "digest": payload["digest"],
                              "decisions": decisions}, ensure_ascii=False))


def test_apply_uses_each_choice_and_marks_undecided_spots(tmp_path, compared, capsys):
    spots, payload = compared
    decisions = _decide(tmp_path, payload, {"1": {"choice": "second"}, "2": {"choice": "custom", "text": "呢\n"}})

    code = cli.main(["three-way", "apply", "--spots", str(spots), "--decisions", str(decisions),
                     "--out", str(tmp_path / "final")])

    assert code == 0
    assert "沒決定 1（加了草稿標記）" in capsys.readouterr().out
    written = (tmp_path / "final" / "demo_A.txt").read_bytes()
    assert b"\r\n" not in written  # Windows 上也只用 LF
    text = written.decode("utf-8")
    assert "[00:01.00] A: 我們夏洲二去爬山。\n" in text
    assert "[00:05.00] B: 要帶雨傘呢？\n" in text
    assert "A: 天気が良(?)ければ散歩に行きます。\n" in text
    with pytest.raises(reference_set.ReferenceSetError, match="1 處草稿標記"):
        reference_set.read_reference(tmp_path / "final" / "demo_A.txt")


def test_apply_with_every_spot_decided_writes_a_confirmed_reference(tmp_path, compared):
    spots, payload = compared
    source = three_way.read_source(Path(payload["source"]["path"]))
    decisions = {"decisions": {"1": {"choice": "source"}, "2": {"choice": "unclear"},
                               "3": {"choice": "first"}}}

    applied = three_way.apply_decisions(source, payload, decisions, confirmed_by="Wade",
                                        on=date(2026, 11, 1))

    lines = applied.text.splitlines()
    assert lines[:4] == [
        "# demo_A  00:00.00-01:00.00",
        "# A=主持人 B=來賓",
        f"# 三方對照：底稿 底稿.txt（SHA-256 {payload['source']['sha256'][:12]}）、"
        f"moss-align（SHA-256 {payload['systems'][0]['sha256'][:12]}）、"
        f"moss-qwen3-asr（SHA-256 {payload['systems'][1]['sha256'][:12]}）；"
        "不一致 3 處，已決定 3 處（採用底稿 1、採用模型 1、自己輸入 0、聽不清 1）",
        "# 確認：Wade，2026-11-01",
    ]
    assert "[00:05.00] B: 要帶雨傘[聽不清]？" in lines
    reference_path = _write(tmp_path / "ref.txt", applied.text)
    excerpt = reference_set.read_reference(reference_path)
    assert excerpt.draft_marks == 0
    assert [u.text for u in excerpt.utterances][2] == "天気がよければ散歩に行きます。"


def test_confirmation_needs_every_spot_decided(compared):
    _, payload = compared
    source = three_way.read_source(Path(payload["source"]["path"]))

    with pytest.raises(UsageError, match="還有 3 處沒有決定"):
        three_way.apply_decisions(source, payload, {"decisions": {}}, confirmed_by="Wade")


def test_apply_refuses_decisions_made_on_another_list(tmp_path, compared, capsys):
    spots, payload = compared
    stale = _write(tmp_path / "stale.json", json.dumps({"digest": "0" * 64, "decisions": {}}))

    assert cli.main(["three-way", "apply", "--spots", str(spots), "--decisions", str(stale),
                     "--out", str(tmp_path / "final")]) == 2
    assert "digest 不同" in capsys.readouterr().err


def test_apply_refuses_a_source_edited_after_compare(tmp_path, compared, capsys):
    spots, payload = compared
    Path(payload["source"]["path"]).write_text(SOURCE.replace("爬山", "游泳"), encoding="utf-8")

    assert cli.main(["three-way", "apply", "--spots", str(spots),
                     "--decisions", str(_decide(tmp_path, payload, {})),
                     "--out", str(tmp_path / "final")]) == 2
    assert "改過了" in capsys.readouterr().err


def test_apply_does_not_write_into_references(tmp_path, lab, compared, capsys):
    spots, payload = compared

    assert cli.main(["three-way", "apply", "--spots", str(spots),
                     "--decisions", str(_decide(tmp_path, payload, {})),
                     "--out", str(lab / "data" / "eval")]) == 2
    assert "不能寫進標準答案的資料夾" in capsys.readouterr().err
