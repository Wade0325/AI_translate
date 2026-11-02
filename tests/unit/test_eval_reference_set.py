"""評測工具（tools/eval）讀標準答案與轉錄結果。

標準答案是人工聽打的一段連續音訊：表頭寫名稱與時間範圍，每行一句「代號: 文字」。轉錄結果
讀的是 LRC，依標準答案的時間範圍裁切。沒有說話者標記的行（例如 Gemini 的轉錄結果）以前會被
默默丟掉，讓錯字率看起來像整段漏字；現在讀進來，算同一位說話者。
"""
import textwrap

import pytest

from tools.eval.reference_set import (
    UNLABELED_SPEAKER,
    ReferenceSetError,
    Utterance,
    clip_transcript,
    read_reference,
    transcript_warnings,
)


def _write(path, text):
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


def test_reads_header_and_utterances(tmp_path):
    path = _write(tmp_path / "demo_A.txt", """
        # demo_A  01:00.00-02:30.50
        # A=主持人 B=來賓
        [01:02.10] A: 我們下週二去爬山。
        ~B: 嗯
        B: 要帶 [聽不清] 嗎？
    """)

    excerpt = read_reference(path)

    assert (excerpt.name, excerpt.start, excerpt.end) == ("demo_A", 60.0, 150.5)
    assert excerpt.utterances == [
        Utterance("A", "我們下週二去爬山。"),
        Utterance("B", "嗯", overlap=True),
        Utterance("B", "要帶 [聽不清] 嗎？"),
    ]
    assert excerpt.draft_marks == 0


def test_refuses_draft_marks_unless_allowed(tmp_path):
    path = _write(tmp_path / "demo_A.draft.txt", """
        # demo_A  00:00.00-00:30.00
        A?: 先確認版本。
        B: 版本是 (?) 三。
    """)

    with pytest.raises(ReferenceSetError, match="2 處草稿標記"):
        read_reference(path)
    assert read_reference(path, allow_draft=True).draft_marks == 2


def test_reads_cpmer_skip_with_its_reason(tmp_path):
    # 說話者的安排量不到說話者分離的片段（例如幾位唸同一份台本、依序接成區塊）只算錯字率（ADR 0009）
    path = _write(tmp_path / "demo_J.txt", """
        # demo_J  00:00.00-00:30.00
        # cpMER 不計：兩位說話者唸同一份台本、依序接成區塊
        A: 我們下週二
        B: 我們下週二
    """)

    assert read_reference(path).cp_mer_skip == "兩位說話者唸同一份台本、依序接成區塊"
    assert read_reference(_write(tmp_path / "demo_A.txt", "# demo_A  00:00.00-00:30.00\nA: 好\n")
                          ).cp_mer_skip is None


@pytest.mark.parametrize("line", ["# cpMER 不計", "# cpMER 不計：", "# cpMER 不計：  "])
def test_refuses_cpmer_skip_without_a_reason(tmp_path, line):
    path = _write(tmp_path / "demo_J.txt", f"# demo_J  00:00.00-00:30.00\n{line}\nA: 好\n")

    with pytest.raises(ReferenceSetError, match="沒有理由"):
        read_reference(path)


def test_refuses_file_without_time_range(tmp_path):
    path = _write(tmp_path / "demo_A.txt", "A: 沒有表頭。\n")

    with pytest.raises(ReferenceSetError, match="表頭"):
        read_reference(path)


def test_refuses_line_without_speaker(tmp_path):
    path = _write(tmp_path / "demo_A.txt", """
        # demo_A  00:00.00-00:30.00
        這行沒有代號
    """)

    with pytest.raises(ReferenceSetError, match="這行沒有代號"):
        read_reference(path)


def test_clips_lrc_to_the_excerpt_window(tmp_path):
    lrc = _write(tmp_path / "transcript.lrc", """
        [00:59.99][S0] 前一段
        [01:00.00][S0] 開始了
        [01:10.50][S1] 換人講
        [02:30.50][S0] 已經在範圍外
    """)

    assert clip_transcript(lrc, 60.0, 150.5) == [
        Utterance("S0", "開始了"),
        Utterance("S1", "換人講"),
    ]


def test_reads_lines_without_speaker_label_as_one_speaker(tmp_path):
    lrc = _write(tmp_path / "transcript.lrc", """
        [ti:範例]
        [00:01.00] 沒有標記的第一行
        [00:02.00][S1] 有標記
        [00:03.00] 沒有標記的第二行
    """)

    assert clip_transcript(lrc, 0.0, 10.0) == [
        Utterance(UNLABELED_SPEAKER, "沒有標記的第一行"),
        Utterance("S1", "有標記"),
        Utterance(UNLABELED_SPEAKER, "沒有標記的第二行"),
    ]


def test_reads_gemini_speaker_prefix_as_label(tmp_path):
    lrc = _write(tmp_path / "transcript.lrc", """
        [00:01.00]Speaker A: 第一位
        [00:02.00]Speaker B：第二位
    """)

    assert clip_transcript(lrc, 0.0, 10.0) == [
        Utterance("SpeakerA", "第一位"),
        Utterance("SpeakerB", "第二位"),
    ]


def test_warns_about_unlabeled_lines_and_lines_without_timestamp(tmp_path):
    lrc = _write(tmp_path / "transcript.lrc", """
        [00:01.00] 沒有標記
        [00:02.00][S0] 有標記
        換行後沒有時間戳的文字
    """)

    assert transcript_warnings(lrc) == [
        "1 行沒有說話者標記，全部算同一位說話者（S?）",
        "1 行沒有時間戳，不計分（第一行：換行後沒有時間戳的文字）",
    ]


def test_no_warnings_for_fully_labeled_lrc(tmp_path):
    lrc = _write(tmp_path / "transcript.lrc", "[ar:範例]\n[00:01.00][S0] 有標記\n")

    assert transcript_warnings(lrc) == []
