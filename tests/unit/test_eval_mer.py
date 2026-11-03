"""評測工具（tools/eval）的單句計分：錯字率的分子與錯誤分類。

錯字率（MER）以漢字、平假名、片假名每字一個 token，英文詞一個 token；日文和中文的算法相同
（ADR 0009）。正規化兩邊同時做，聽打規範的差異（簡繁字形、全形、標點、語助詞、逐字母縮寫、個位
數字、[聽不清]、括號標註的非語言聲）不算錯；詞彙替換、口音同音字與漢字假名的寫法不同要算錯。
句子的案例和 ``python -m tools.eval selftest`` 共用，見 ``tools/eval/selftest.py``；斷成哪些
token、「着」併成「著」的方向與附和的計分只在這裡測。
"""
import itertools
import random

import pytest

from tools.eval import selftest
from tools.eval.custom_vocabulary import CustomVocabulary
from tools.eval.mer import (
    UNK,
    Result,
    best_mapping,
    evaluate,
    global_mapping,
    mapping_cost,
    score_text,
    speaker_distances,
    tokenize,
)
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


def test_cp_mer_skips_unclear_like_mer():
    # 《坊っちゃん》：錄音開頭的有聲書宣告底稿沒有，標成 [聽不清]。錯字率不計那一段，cpMER 以前
    # 卻把 [聽不清] 先丟掉，宣告整段算成插入（#273）
    excerpt = Excerpt(name="ja", start=0.0, end=60.0, utterances=[
        Utterance(speaker="A", text="[聽不清] 親譲りの無鉄砲で"),
        Utterance(speaker="B", text="小供の時から損ばかり"),
    ])
    transcript = [
        Utterance(speaker="S0", text="これは録音です。親譲りの無鉄砲で"),
        Utterance(speaker="S1", text="子供の時から損ばかり"),
    ]

    result = evaluate(excerpt, transcript, CustomVocabulary(), bootstrap=0)
    _, cp = global_mapping([result])

    # 兩邊都只剩「小供／子供」1 個錯，分母都不含 [聽不清]
    assert result.errors == 1
    assert result.cp_mer_local == pytest.approx(result.mer)
    assert cp == pytest.approx(result.mer)


def test_unclear_alone_costs_nothing_when_its_speaker_is_unmatched():
    dist = speaker_distances({"A": [UNK], "B": ["甲", UNK, "乙"]}, {})

    assert (dist[("A", "")], dist[("B", "")]) == (0, 2)


# ----------------------------------------------------------------- 說話者對應
def _random_speakers(rng, prefix, count, vocabulary="甲乙丙丁戊"):
    return {f"{prefix}{k}": [rng.choice(vocabulary) for _ in range(rng.randint(0, 6))]
            for k in range(count)}


def _brute_force_cost(ref_spk, hyp_spk):
    """cpWER 的定義：列舉所有一對一對應（配不到的算全刪或全插），取最小的總編輯距離。"""
    dist = speaker_distances(ref_spk, hyp_spk)
    refs = sorted(ref_spk)
    hyps = sorted(hyp_spk)
    n = max(len(refs), len(hyps))
    refs += [""] * (n - len(refs))
    hyps += [""] * (n - len(hyps))
    return min((sum(dist.get((r, h), 0) for r, h in zip(refs, perm, strict=True) if r or h)
                for perm in itertools.permutations(hyps)), default=0)


@pytest.mark.parametrize("seed", range(40))
def test_best_mapping_finds_the_cheapest_one_to_one_mapping(seed):
    rng = random.Random(seed)
    ref_spk = _random_speakers(rng, "R", rng.randint(0, 5))
    hyp_spk = _random_speakers(rng, "S", rng.randint(0, 5))

    cost, mapping = best_mapping(ref_spk, hyp_spk)

    assert cost == _brute_force_cost(ref_spk, hyp_spk)
    assert cost == mapping_cost(ref_spk, hyp_spk, mapping)
    matched = [r for r in mapping.values() if r]
    assert len(matched) == len(set(matched))  # 一對一


@pytest.mark.parametrize("seed", range(20))
def test_global_mapping_finds_the_cheapest_shared_mapping(seed):
    # 同一份轉錄結果的幾段：每段的代號與標記不一定都出現，共用一組對應
    rng = random.Random(seed)
    results = []
    for k in range(rng.randint(1, 3)):
        refs = _random_speakers(rng, "R", 4)
        hyps = _random_speakers(rng, "S", 4)
        result = Result(name=f"r{k}", window=(0.0, 1.0), n_utts=1, ref_len=1, transcript_len=1)
        result.ref_spk = {key: v for key, v in refs.items() if rng.random() < 0.7}
        result.transcript_spk = {key: v for key, v in hyps.items() if rng.random() < 0.7}
        results.append(result)
    labels_ref = sorted({k for r in results for k in r.ref_spk})
    labels_hyp = sorted({k for r in results for k in r.transcript_spk})
    n = max(len(labels_ref), len(labels_hyp))
    candidates = [{h: r for h, r in zip(labels_hyp + [""] * (n - len(labels_hyp)), perm, strict=True) if h}
                  for perm in itertools.permutations(labels_ref + [""] * (n - len(labels_ref)))]
    brute = min(sum(mapping_cost(r.ref_spk, r.transcript_spk, m) for r in results) for m in candidates)
    denom = sum(sum(len(v) for v in r.ref_spk.values()) for r in results) or 1

    mapping, cp = global_mapping(results)

    assert cp == pytest.approx(brute / denom)
    assert sum(mapping_cost(r.ref_spk, r.transcript_spk, mapping) for r in results) == brute


def test_many_speakers_do_not_enumerate_every_permutation():
    # JVS 耳語：20 位說話者依序唸，模型只分出 2 個標記。列舉全排列是 20!，永遠算不完
    utterances = [Utterance(f"P{k:02d}", "甲乙丙丁" * (k % 3 + 1)) for k in range(20)]
    transcript = [Utterance("S0" if k < 10 else "S1", u.text) for k, u in enumerate(utterances)]
    excerpt = Excerpt(name="jvs", start=0.0, end=60.0, utterances=utterances)

    result = evaluate(excerpt, transcript, CustomVocabulary(), bootstrap=10)
    mapping, cp = global_mapping([result])

    assert result.mer == 0
    # 20 位裡只配得到 2 位：其餘 18 位的字算刪除，又在那 2 個標記裡算插入
    assert result.cp_mer_local == pytest.approx(cp) and 1.5 < cp < 2
    assert len([r for r in mapping.values() if r]) == 2
