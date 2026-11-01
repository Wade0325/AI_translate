"""評測工具（tools/eval）的單句計分：錯字率的分子與錯誤分類。

錯字率（MER）以漢字、平假名、片假名每字一個 token，英文詞一個 token；日文和中文的算法相同
（ADR 0009）。正規化兩邊同時做，聽打規範的差異（簡繁字形、全形、標點、語助詞、逐字母縮寫、個位
數字、[聽不清]、括號標註的非語言聲）不算錯；詞彙替換、口音同音字與漢字假名的寫法不同要算錯。
句子的案例和 ``python -m tools.eval selftest`` 共用，見 ``tools/eval/selftest.py``；斷成哪些
token、「着」併成「著」的方向與附和的計分只在這裡測。
"""
import pytest

from tools.eval import selftest
from tools.eval.custom_vocabulary import CustomVocabulary
from tools.eval.mer import UNK, evaluate, score_text, tokenize
from tools.eval.reference_set import Excerpt, Utterance


@pytest.mark.parametrize("case", selftest.MER_CASES, ids=lambda case: case.description)
def test_sentence_errors_and_bucket(case):
    score = score_text(case.reference, case.transcript, case.zh_terms)

    assert score.errors == case.errors
    if case.bucket is not None:
        assert case.bucket in score.buckets


@pytest.mark.parametrize(("text", "tokens"), [
    ("看着", ["看", "著"]),
    ("著作", ["著", "作"]),   # 本來就是「著」的詞不受影響
])
def test_simplified_zhe_tokenizes_as_zhu(text, tokens):
    # 「着」（zhe）併成「著」（zhù），不是反過來。錯誤範例印的是正規化後的 token，所以方向看得到
    assert tokenize(text) == tokens


@pytest.mark.parametrize(("text", "tokens"), [
    ("ありがとう", ["あ", "り", "が", "と", "う"]),
    ("コーヒー", ["コ", "ー", "ヒ", "ー"]),           # 長音「ー」是 1 個 token
    ("いすゞ", ["い", "す", "ゞ"]),                   # 疊字符號也是
    ("人々", ["人", "々"]),
    ("今日はDockerを使う", ["今", "日", "は", "docker", "を", "使", "う"]),
    ("すご〜い", ["す", "ご", "い"]),                 # 波浪號和標點一樣不計分
])
def test_japanese_counts_every_kanji_and_kana(text, tokens):
    assert tokenize(text) == tokens


@pytest.mark.parametrize(("text", "tokens"), [
    # 中黑「・」在片假名的區塊裡，但它是標點；中文的人名也用它，收進來中文的分數就會變
    ("卡爾・馬克思", ["卡", "尔", "马", "克", "思"]),
    ("ジョン・スミス", ["ジ", "ョ", "ン", "ス", "ミ", "ス"]),
])
def test_middle_dot_is_punctuation(text, tokens):
    assert tokenize(text) == tokens


@pytest.mark.parametrize(("text", "tokens"), [
    ("（笑）はい", ["は", "い"]),
    ("はい(笑い)", ["は", "い"]),
    ("[拍手]はい［ため息］", ["は", "い"]),
    ("【笑】はい", ["は", "い"]),
    ("[laughter] OK", ["ok"]),
])
def test_bracketed_non_speech_is_dropped(text, tokens):
    assert tokenize(text) == tokens


def test_unclear_mark_is_not_dropped_as_a_bracket():
    # [聽不清] 也是方括號，但它是標準答案裡的 wildcard，要先換掉才刪括號
    assert tokenize("先把 [聽不清] 關掉") == ["先", "把", UNK, "关", "掉"]


def test_japanese_backchannel_is_scored_and_listed_separately():
    # 附和照算，另外列出排除附和後的數字（#15 Q2c）。以前假名整個被丟掉，「はい」是 0 個 token
    excerpt = Excerpt(name="ja", start=0.0, end=60.0, utterances=[
        Utterance(speaker="A", text="今日はいい天気ですね"),
        Utterance(speaker="B", text="はい", overlap=True),
    ])
    transcript = [Utterance(speaker="S0", text="今日はいい天気ですね")]

    result = evaluate(excerpt, transcript, CustomVocabulary(), bootstrap=0)

    assert (result.ref_len, result.dels) == (12, 2)
    assert result.mer == pytest.approx(2 / 12)
    assert result.mer_no_overlap == 0.0
