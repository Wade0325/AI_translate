"""錯字率（MER，混合錯誤率）、說話者歸屬與錯誤預算：所有品質比較的計分核心。

**為什麼不用 CER**：主要錯誤是英文術語（Docker→doctor、Zoom→祖母），以字元計算會低估
嚴重度（doctor 對 Docker 只差兩個字元）。改成「漢字、平假名、片假名每字 1 個 token，英文詞
1 個 token」的混合錯誤率，一個術語錯就是一個錯。日文和中文用同一套算法（ADR 0009），不斷詞、
不維護日文的附和詞表；漢字與假名的寫法不同（ありがとう／有難う）照算錯，錯字率的絕對值因此
偏高，但基準和 PR 對的是同一份標準答案，不影響判定（#15 Q2c）。

**正規化兩邊同時做**，避免把聽打規範的差異算成模型的錯：
  NFKC（全形→半形）→ [聽不清] 轉 wildcard → 去草稿標記 → 刪括號標註的非語言聲 → 繁簡統一
  （t2s，再把「着」併成「著」）→ 小寫 → 只保留漢字、假名與英數 token → 去語助詞 → 逐字母
  縮寫合併（S Q L → sql）→ 個位數字轉中文（9 ↔ 九）

**非語言聲不計分**（#15 Q2c）：標準答案不寫笑聲、啜泣這類聲音；轉錄結果用括號標註的
（「（笑）」「[拍手]」「【笑い】」）連同括號整段刪掉，中文的「[掌聲]」也一樣。判斷只看括號，不看
裡面寫什麼，所以真的說出口、卻被寫在括號裡的話也會被刪；目前看到的轉錄結果拿括號標的都是
非語音的聲音（MOSS 的「[笑]」，Gemini 的提示詞範本要求的「[耳語]」），所以沒有另外處理。「」『』《》〈〉裡是說出口的
話或書名，照算。[聽不清] 也是方括號，要在這一步之前換成 wildcard。

繁簡統一用 ``t2s`` 而非 ``tw2sp``：前者只合併字形（檔/档、裡/里），後者會做詞彙替換
（程式→程序），那會把真正的辨識錯誤洗掉。``opencc`` 來自 ``opencc-python-reimplemented``
（純 Python），不是 PyPI 上叫 ``opencc`` 的官方原生綁定；兩者的字典不同，換掉要另外驗證
錯字率不變。

``t2s`` 之後要另外把「着」併成「著」（#243）：「著」在簡體裡也是合法的字（著作、显著），
``t2s`` 不會把繁體的「看著」換成「看着」。不併的話，標準答案寫繁體、轉錄結果寫簡體時，
每個「着」都算一個錯，錯字率就看標準答案用繁體還是簡體而定。併向「著」，所以著作、显著
這類兩邊都寫「著」的詞不受影響。其他 ``t2s`` 換不回去的字（揹/背、簷/檐、暱/昵）在 #242
量到的書面句子裡各只有 1～5 處，沒有處理；要處理時用同樣的辦法加。

**[聽不清] 的處理有近似**：該位置的替換／刪除不計分，緊鄰的插入也不計分，但若
不清楚的區間對應到轉錄結果的多個 token，較遠的那幾個仍會被算成插入。報告會印出 unk
數量，數字很小才能安心使用。
"""

from __future__ import annotations

import itertools
import random
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import opencc
from rapidfuzz.distance import Levenshtein

from . import phon
from .custom_vocabulary import CustomVocabulary
from .reference_set import DOUBT_RE, UNCLEAR, Excerpt, Utterance

_T2S = opencc.OpenCC("t2s")

# [聽不清] 換成這個私用區字元，對齊時當成 wildcard
UNK = ""
# 每字 1 個 token 的字（ADR 0009）：漢字加上「々」，平假名與片假名加上長音「ー」與疊字符號
# （ゝゞヽヾ）。片假名區塊裡的中黑「・」（U+30FB）與單獨的濁點「゛゜」是標點，和其他標點一樣
# 不收：中文的人名也用「・」，收進來中文的分數就會變
_HAN = "一-鿿々"
_HIRAGANA = "ぁ-ゖゝ-ゟ"
_KATAKANA = "ァ-ヺー-ヿㇰ-ㇿ"
TOKEN_RE = re.compile(rf"{UNK}|[{_HAN}{_HIRAGANA}{_KATAKANA}]|[A-Za-z0-9]+")
# 括號標註的非語言聲：（笑）、[拍手]、【笑】。NFKC 之後全形括號都成了半形，所以只列半形與【】
NON_SPEECH_RE = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|【[^【】]*】")
# 只放純語助詞。兩邊同時刪除，所以寫不寫「嗯」不影響分數
FILLERS = set("嗯呃啊喔哦欸誒唉呀哎唔")
DIGIT_ZH = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
            "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"}

BUCKETS = ("跨語言術語", "術語拼寫", "中文術語", "口音同音", "漏字", "插入", "其他")

Span = tuple[int, int, int, int]


# ----------------------------------------------------------------- 正規化
def tokenize(text: str, drop_fillers: bool = True) -> list[str]:
    s = unicodedata.normalize("NFKC", text)
    s = s.replace(UNCLEAR, UNK)
    s = DOUBT_RE.sub("", s).replace("(?)", "")
    s = NON_SPEECH_RE.sub("", s)
    s = _T2S.convert(s).replace("着", "著").lower()
    toks = TOKEN_RE.findall(s)
    if drop_fillers:
        toks = [t for t in toks if t not in FILLERS]
    toks = _collapse_spelled_letters(toks)
    return [DIGIT_ZH.get(t, t) for t in toks]


def _collapse_spelled_letters(tokens: Sequence[str]) -> list[str]:
    """逐字母唸出的縮寫（S Q L）併成一個 token，避免與 SQL 重複計錯。"""
    out: list[str] = []
    run: list[str] = []

    def flush():
        if len(run) >= 2:
            out.append("".join(run))
        elif run:
            out.append(run[0])
        run.clear()

    for t in tokens:
        if len(t) == 1 and t.isascii() and t.isalpha():
            run.append(t)
        else:
            flush()
            out.append(t)
    flush()
    return out


def _vocabulary_tokens(terms: Iterable[str]) -> set[str]:
    """術語斷成 token 後的中文 token；錯誤分類「中文術語」用它判斷。"""
    return {t for term in terms for t in tokenize(term, drop_fillers=False)
            if not t.isascii()}


# ------------------------------------------------------------------- 對齊
@dataclass
class Block:
    """一段連續的差異。ref（標準答案）／hyp（轉錄結果）其中一邊可能是空的（漏字／插入）。"""

    ref: list[str]
    hyp: list[str]
    src_start: int
    n_errors: int
    bucket: str = "其他"

    def as_example(self) -> str:
        return f"{_join(self.ref)} → {_join(self.hyp)}"


def _join(tokens: Sequence[str]) -> str:
    """英文 token 之間補空白，否則 ['open','source'] 會印成 opensource。"""
    if not tokens:
        return "∅"
    out = ""
    for t in tokens:
        if out and (t[0].isascii() or out[-1].isascii()):
            out += " "
        out += t
    return out


def _op_spans(ops) -> list[Span]:
    """把 editops 轉成 (src_start, src_end, dest_start, dest_end)。"""
    spans = []
    for op in ops:
        if op.tag == "replace":
            spans.append((op.src_pos, op.src_pos + 1, op.dest_pos, op.dest_pos + 1))
        elif op.tag == "delete":
            spans.append((op.src_pos, op.src_pos + 1, op.dest_pos, op.dest_pos))
        else:  # insert
            spans.append((op.src_pos, op.src_pos, op.dest_pos, op.dest_pos + 1))
    return spans


def _scored_spans(spans: Sequence[Span], ref: Sequence[str]) -> list[Span]:
    """去掉 [聽不清] 位置的替換／刪除，以及緊鄰它的插入。"""
    unk_pos = {i for i, t in enumerate(ref) if t == UNK}

    def ignored(s0: int, s1: int) -> bool:
        if s1 > s0:
            return any(p in unk_pos for p in range(s0, s1))
        return (s0 in unk_pos) or (s0 - 1 in unk_pos)

    return [sp for sp in spans if not ignored(sp[0], sp[1])]


def group_blocks(ref: Sequence[str], hyp: Sequence[str], spans) -> list[Block]:
    blocks = []
    cur = None
    for s0, s1, d0, d1 in spans:
        if cur and s0 <= cur[1] and d0 <= cur[3]:
            cur = (cur[0], max(cur[1], s1), cur[2], max(cur[3], d1), cur[4] + 1)
        else:
            if cur:
                blocks.append(cur)
            cur = (s0, s1, d0, d1, 1)
    if cur:
        blocks.append(cur)
    return [Block(ref=list(ref[a:b]), hyp=list(hyp[c:d]), src_start=a, n_errors=n)
            for a, b, c, d, n in blocks]


# --------------------------------------------------------------- 錯誤分類
def _has_ascii(tokens: Sequence[str]) -> bool:
    return any(t.isascii() and t[0].isalpha() for t in tokens)


def classify(block: Block, zh_terms: set[str]) -> str:
    r, h = block.ref, block.hyp
    r_txt, h_txt = "".join(r), "".join(h)
    r_ascii, h_ascii = _has_ascii(r), _has_ascii(h)

    if r and h and (r_ascii != h_ascii):
        return "跨語言術語"
    if r_ascii and h_ascii:
        return "術語拼寫"
    if r and h and phon.homophone(r_txt, h_txt):
        return "口音同音"
    if any(t in zh_terms for t in r):
        return "中文術語"
    if not h:
        return "漏字"
    if not r:
        return "插入"
    return "其他"


# ------------------------------------------------------------------- 單句
@dataclass
class SentenceScore:
    errors: int
    buckets: list[str]


def score_text(reference: str, transcript: str, zh_terms: Iterable[str] = ()) -> SentenceScore:
    """單句比對：錯誤數與每段差異的分類；與 :func:`evaluate` 走同一套規則。

    zh_terms 是術語表的術語（原文，不必先斷詞）。
    """
    ref, hyp_tokens = tokenize(reference), tokenize(transcript)
    kept = _scored_spans(_op_spans(Levenshtein.editops(ref, hyp_tokens)), ref)
    blocks = group_blocks(ref, hyp_tokens, kept)
    terms = _vocabulary_tokens(zh_terms)
    for b in blocks:
        b.bucket = classify(b, terms)
    return SentenceScore(errors=sum(b.n_errors for b in blocks),
                         buckets=[b.bucket for b in blocks])


# ----------------------------------------------------------------- 說話者
def _by_speaker(utts: Sequence[Utterance]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for u in utts:
        out.setdefault(u.speaker, []).extend(t for t in tokenize(u.text) if t != UNK)
    return out


def speaker_distances(ref_spk: dict[str, list[str]],
                      hyp_spk: dict[str, list[str]]) -> dict[tuple[str, str], int]:
    """所有 (標準答案的說話者, 轉錄結果的說話者標記) 組合的編輯距離，含「對應到空」的成本。"""
    d: dict[tuple[str, str], int] = {}
    for rk, rv in ref_spk.items():
        d[(rk, "")] = len(rv)
        for hk, hv in hyp_spk.items():
            d[(rk, hk)] = Levenshtein.distance(rv, hv)
    for hk, hv in hyp_spk.items():
        d[("", hk)] = len(hv)
    return d


def best_mapping(ref_spk, hyp_spk, dist=None) -> tuple[int, dict[str, str]]:
    """列舉一對一對應，取總編輯距離最小者（cpWER 的標準做法）。"""
    dist = dist or speaker_distances(ref_spk, hyp_spk)
    rk = sorted(ref_spk)
    hk = sorted(hyp_spk)
    n = max(len(rk), len(hk))
    rk_p = rk + [""] * (n - len(rk))
    hk_p = hk + [""] * (n - len(hk))
    best = None
    for perm in itertools.permutations(hk_p):
        total = 0
        for r, h in zip(rk_p, perm, strict=True):
            if not r and not h:
                continue
            total += dist.get((r, h), 0)
        if best is None or total < best[0]:
            best = (total, {h: r for r, h in zip(rk_p, perm, strict=True) if h})
    return best if best else (0, {})


def mapping_cost(ref_spk, hyp_spk, mapping: dict[str, str], dist=None) -> int:
    """指定對應下的總編輯距離（用來算全域對應的成本）。"""
    dist = dist or speaker_distances(ref_spk, hyp_spk)
    total = 0
    used = set()
    for hk in hyp_spk:
        rk = mapping.get(hk, "")
        total += dist.get((rk, hk), len(hyp_spk[hk]))
        if rk:
            used.add(rk)
    for rk in ref_spk:
        if rk not in used:
            total += dist[(rk, "")]
    return total


# ------------------------------------------------------------------- 計分
@dataclass
class Result:
    name: str
    window: tuple[float, float]
    n_utts: int
    ref_len: int
    transcript_len: int
    subs: int = 0
    dels: int = 0
    ins: int = 0
    unk: int = 0
    mer: float = 0.0
    ci: tuple[float, float] = (0.0, 0.0)
    mer_no_overlap: float = 0.0
    cp_mer_local: float = 0.0
    mapping_local: dict[str, str] = field(default_factory=dict)
    cp_mer_global: float = 0.0
    cp_mer_skip: str | None = None  # 標準答案註明不算 cpMER 的理由（reference_set.Excerpt）
    budget: dict[str, int] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)
    term_total: int = 0
    term_hit: int = 0
    term_false_ins: int = 0
    line_errors: list[int] = field(default_factory=list)
    line_ref_len: list[int] = field(default_factory=list)
    ref_spk: dict[str, list[str]] = field(default_factory=dict)
    transcript_spk: dict[str, list[str]] = field(default_factory=dict)

    @property
    def errors(self) -> int:
        return self.subs + self.dels + self.ins

    @property
    def term_recall(self) -> float:
        return self.term_hit / self.term_total if self.term_total else 0.0

    def to_dict(self) -> dict:
        """寫進 --json 的數字（比率取到小數第四位）。"""
        return {
            "name": self.name, "window": self.window, "utts": self.n_utts,
            "ref_len": self.ref_len, "transcript_len": self.transcript_len, "unk": self.unk,
            "subs": self.subs, "dels": self.dels, "ins": self.ins,
            "mer": round(self.mer, 4), "ci": [round(c, 4) for c in self.ci],
            "mer_no_overlap": round(self.mer_no_overlap, 4),
            "cp_mer_local": round(self.cp_mer_local, 4),
            "cp_mer_global": round(self.cp_mer_global, 4),
            "cp_mer_scored": self.cp_mer_skip is None,
            "cp_mer_skip": self.cp_mer_skip,
            "mapping_local": self.mapping_local,
            "term_recall": round(self.term_recall, 4),
            "term_hit": self.term_hit, "term_total": self.term_total,
            "term_false_ins": self.term_false_ins,
            "budget": self.budget, "examples": self.examples,
        }


def _term_token_lists(vocabulary: CustomVocabulary) -> list[list[str]]:
    out = []
    for term in vocabulary.all_terms:
        toks = tokenize(term, drop_fillers=False)
        if toks:
            out.append(toks)
    return out


def _find(seq: Sequence[str], pat: Sequence[str]) -> list[int]:
    n, m = len(seq), len(pat)
    return [i for i in range(n - m + 1) if list(seq[i:i + m]) == list(pat)]


def evaluate(excerpt: Excerpt, transcript: Sequence[Utterance], vocabulary: CustomVocabulary,
             bootstrap: int = 1000, seed: int = 20260920) -> Result:
    ref_lines = [tokenize(u.text) for u in excerpt.utterances]
    ref: list[str] = []
    line_of: list[int] = []
    for i, toks in enumerate(ref_lines):
        ref.extend(toks)
        line_of.extend([i] * len(toks))
    hyp_tokens: list[str] = []
    for u in transcript:
        hyp_tokens.extend(tokenize(u.text))

    unk = sum(1 for t in ref if t == UNK)
    spans = _op_spans(Levenshtein.editops(ref, hyp_tokens))
    kept = _scored_spans(spans, ref)

    res = Result(name=excerpt.name, window=(excerpt.start, excerpt.end),
                 n_utts=len(excerpt.utterances), ref_len=len(ref) - unk,
                 transcript_len=len(hyp_tokens), unk=unk, cp_mer_skip=excerpt.cp_mer_skip)

    n_lines = len(ref_lines)
    res.line_errors = [0] * n_lines
    res.line_ref_len = [sum(1 for t in toks if t != UNK) for toks in ref_lines]

    for s0, s1, d0, d1 in kept:
        if s1 > s0 and d1 > d0:
            res.subs += 1
        elif s1 > s0:
            res.dels += 1
        else:
            res.ins += 1
        idx = line_of[min(s0, len(line_of) - 1)] if line_of else 0
        res.line_errors[idx] += 1

    res.mer = res.errors / res.ref_len if res.ref_len else (1.0 if hyp_tokens else 0.0)

    # 排除「對方講話時插進來的附和」：從分子分母同時扣掉那幾行
    ov = {i for i, u in enumerate(excerpt.utterances) if u.overlap}
    if ov:
        e = res.errors - sum(res.line_errors[i] for i in ov)
        n = res.ref_len - sum(res.line_ref_len[i] for i in ov)
        res.mer_no_overlap = e / n if n else 0.0
    else:
        res.mer_no_overlap = res.mer

    # 錯誤預算
    zh_terms = _vocabulary_tokens(vocabulary.all_terms)
    blocks = group_blocks(ref, hyp_tokens, kept)
    res.budget = {b: 0 for b in BUCKETS}
    res.examples = {b: [] for b in BUCKETS}
    for b in blocks:
        b.bucket = classify(b, zh_terms)
        res.budget[b.bucket] += b.n_errors
        if len(res.examples[b.bucket]) < 4:
            res.examples[b.bucket].append(b.as_example())

    # 術語召回與誤插入
    matched_ref = set(range(len(ref)))
    matched_hyp = set(range(len(hyp_tokens)))
    for s0, s1, d0, d1 in spans:
        matched_ref -= set(range(s0, s1))
        matched_hyp -= set(range(d0, d1))
    for pat in _term_token_lists(vocabulary):
        for i in _find(ref, pat):
            res.term_total += 1
            if all(p in matched_ref for p in range(i, i + len(pat))):
                res.term_hit += 1
        for j in _find(hyp_tokens, pat):
            if not any(p in matched_hyp for p in range(j, j + len(pat))):
                res.term_false_ins += 1

    # 說話者歸屬
    res.ref_spk = _by_speaker(excerpt.utterances)
    res.transcript_spk = _by_speaker(transcript)
    cost, mapping = best_mapping(res.ref_spk, res.transcript_spk)
    denom = sum(len(v) for v in res.ref_spk.values()) or 1
    res.cp_mer_local = cost / denom
    res.mapping_local = mapping

    res.ci = bootstrap_ci(res.line_errors, res.line_ref_len, bootstrap, seed)
    return res


def bootstrap_ci(errors: Sequence[int], lens: Sequence[int],
                 n: int = 1000, seed: int = 20260920) -> tuple[float, float]:
    """對「行」重抽樣，回傳 MER 的 95% 信賴區間。改善要大於這個區間才算真的。"""
    if not errors or n <= 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    k = len(errors)
    vals = []
    for _ in range(n):
        idx = [rng.randrange(k) for _ in range(k)]
        e = sum(errors[i] for i in idx)
        total = sum(lens[i] for i in idx)
        vals.append(e / total if total else 0.0)
    vals.sort()
    return (vals[int(0.025 * n)], vals[min(n - 1, int(0.975 * n))])


def paired_delta_ci(a: Sequence[int], b: Sequence[int], lens: Sequence[int],
                    n: int = 1000, seed: int = 20260920) -> tuple[float, float, float]:
    """兩個轉錄結果的 MER 差（b − a）與其 95% 區間；同一組重抽樣索引（成對）。"""
    rng = random.Random(seed)
    k = len(lens)
    vals = []
    for _ in range(n):
        idx = [rng.randrange(k) for _ in range(k)]
        total = sum(lens[i] for i in idx) or 1
        vals.append((sum(b[i] for i in idx) - sum(a[i] for i in idx)) / total)
    vals.sort()
    mean = sum(vals) / len(vals)
    return (mean, vals[int(0.025 * n)], vals[min(n - 1, int(0.975 * n))])


# ----------------------------------------------------------------- 全域對應
def global_mapping(results: Sequence[Result]) -> tuple[dict[str, str], float | None]:
    """評測集的所有音檔共用同一組說話者對應時的最佳解與 cpMER。

    與每段音檔各自最佳（cp_mer_local）的差距，就是說話者標記在音檔之間不一致的代價。
    標準答案註明「cpMER 不計」的片段不參與對應，它的 cp_mer_global 只列出局部對應的值；
    每一段都不計時，cpMER 是 None。
    """
    for r in results:
        if r.cp_mer_skip is not None:
            r.cp_mer_global = r.cp_mer_local
    results = [r for r in results if r.cp_mer_skip is None]
    if not results:
        return {}, None
    labels_hyp = sorted({k for r in results for k in r.transcript_spk})
    labels_ref = sorted({k for r in results for k in r.ref_spk})
    n = max(len(labels_hyp), len(labels_ref))
    hyp_p = labels_hyp + [""] * (n - len(labels_hyp))
    ref_p = labels_ref + [""] * (n - len(labels_ref))
    dists = [speaker_distances(r.ref_spk, r.transcript_spk) for r in results]
    denom = sum(sum(len(v) for v in r.ref_spk.values()) for r in results) or 1

    best: tuple[int, dict[str, str]] = (0, {})
    for i, perm in enumerate(itertools.permutations(ref_p)):
        mapping = {h: r for h, r in zip(hyp_p, perm, strict=True) if h}
        total = sum(mapping_cost(r.ref_spk, r.transcript_spk, mapping, d)
                    for r, d in zip(results, dists, strict=True))
        if i == 0 or total < best[0]:
            best = (total, mapping)
    for r, d in zip(results, dists, strict=True):
        r.cp_mer_global = mapping_cost(r.ref_spk, r.transcript_spk, best[1], d) / (
            sum(len(v) for v in r.ref_spk.values()) or 1)
    return best[1], best[0] / denom


# ------------------------------------------------------------------- 報告
def format_report(results: Sequence[Result], transcript_label: str,
                  global_map: dict[str, str], cp_global: float | None) -> str:
    out: list[str] = [f"轉錄結果：{transcript_label}", ""]
    tot_err = sum(r.errors for r in results)
    tot_ref = sum(r.ref_len for r in results)
    for r in results:
        out += [
            f"── {r.name}  {_window(r.window)}  標準答案 {r.n_utts} 句 / {r.ref_len} token"
            + (f"（unk {r.unk}）" if r.unk else ""),
            f"   MER            {r.mer*100:6.2f}%   "
            f"(替換 {r.subs} / 漏 {r.dels} / 插 {r.ins})"
            f"   95% CI [{r.ci[0]*100:.2f}, {r.ci[1]*100:.2f}]",
            f"   排除附和後      {r.mer_no_overlap*100:6.2f}%",
            f"   cpMER 局部對應  {r.cp_mer_local*100:6.2f}%   "
            f"對應 {_mapping_text(r.mapping_local)}",
            f"   cpMER 全域對應  {r.cp_mer_global*100:6.2f}%" if r.cp_mer_skip is None else
            f"   cpMER          不計（{r.cp_mer_skip}）：上面的局部對應只列出，不進判定",
            f"   術語召回        {r.term_recall*100:6.1f}%   "
            f"({r.term_hit}/{r.term_total})   誤插入 {r.term_false_ins}",
            "   錯誤預算：" + "  ".join(
                f"{k} {v}（{v/max(1,r.errors)*100:.0f}%）"
                for k, v in sorted(r.budget.items(), key=lambda kv: -kv[1]) if v),
        ]
        for b in BUCKETS:
            if r.examples.get(b):
                out.append(f"     {b}: " + " ｜ ".join(r.examples[b]))
        out.append("")
    out.append(f"總計  MER {tot_err/max(1,tot_ref)*100:.2f}%  "
               f"({tot_err} 錯 / {tot_ref} token)")
    scored = [r for r in results if r.cp_mer_skip is None]
    if cp_global is None or not scored:
        out.append("      cpMER 不計：每一段的標準答案都註明「cpMER 不計」")
        return "\n".join(out)
    out.append(f"      cpMER 全域對應 {cp_global*100:.2f}%   對應 {_mapping_text(global_map)}"
               + (f"（不含註明不計的 {len(results) - len(scored)} 段）" if len(scored) < len(results) else ""))
    local = sum(r.cp_mer_local * max(1, sum(len(v) for v in r.ref_spk.values()))
                for r in scored) / max(1, sum(
                    sum(len(v) for v in r.ref_spk.values()) for r in scored))
    gap = cp_global - local
    if len(scored) > 1:
        out.append(f"      cpMER 局部對應 {local*100:.2f}%"
                   f"   差距 {gap*100:+.2f} pp"
                   + ("   ← 說話者標記在音檔之間不一致" if gap > 0.01 else ""))
    return "\n".join(out)


def _window(win: tuple[float, float]) -> str:
    return f"{int(win[0]//60):02d}:{win[0]%60:05.2f}-{int(win[1]//60):02d}:{win[1]%60:05.2f}"


def _mapping_text(m: dict[str, str]) -> str:
    return ", ".join(f"{h}→{r}" for h, r in sorted(m.items())) or "（無）"
