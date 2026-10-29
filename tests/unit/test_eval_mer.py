"""評測工具（tools/eval）的單句計分：錯字率的分子與錯誤分類。

錯字率（MER）以中文字與英文詞各算一個 token。正規化兩邊同時做，聽打規範的差異（簡繁字形、
全形、標點、語助詞、逐字母縮寫、個位數字、[聽不清]）不算錯；詞彙替換與口音同音字要算錯。
案例和 ``python -m tools.eval selftest`` 共用，見 ``tools/eval/selftest.py``。
"""
import pytest

from tools.eval import selftest
from tools.eval.mer import score_text, tokenize


@pytest.mark.parametrize("case", selftest.MER_CASES, ids=lambda case: case.description)
def test_sentence_errors_and_bucket(case):
    score = score_text(case.reference, case.transcript, case.zh_terms)

    assert score.errors == case.errors
    if case.bucket is not None:
        assert case.bucket in score.buckets


@pytest.mark.parametrize(("text", "tokens"), [
    ("看着", ["看", "著"]),
    ("看著", ["看", "著"]),
    ("著作", ["著", "作"]),   # 本來就是「著」的詞不受影響
])
def test_zhe_is_merged_into_the_traditional_form(text, tokens):
    # 錯誤範例印的是正規化後的 token，所以合併的方向看得到：一律印「著」
    assert tokenize(text) == tokens
