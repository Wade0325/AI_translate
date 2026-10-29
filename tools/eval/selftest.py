"""自我驗證：正規化、錯誤分類與同音判斷的已知案例。

``python -m tools.eval selftest`` 逐條印出結果；pytest（``tests/unit/test_eval_*.py``）跑同一組
案例。案例全是自造的例句，不取自任何真實錄音；新增案例時也一樣。
"""

from __future__ import annotations

from typing import NamedTuple

from .mer import score_text
from .phon import homophone, norm_pinyin

# (聽成, 原本) ：口音合併後同音，應判為同音
HOMOPHONES = [
    ("字形", "執行"),   # zh→z、ing→in
    ("函素", "函數"),   # sh→s
    ("深沉", "生成"),   # sh→s、ch→c、eng→en
    ("牛成", "流程"),   # n→l
]

# 相近但不在合併規則裡，應擋掉
NOT_HOMOPHONES = [
    ("飼料", "資料"),   # s 與 z 不合併
    ("便宜", "編譯"),   # 送氣與否不合併
    ("意外", "例外"),   # 聲母不同
    ("決定", "設定"),
    ("零件", "物件"),
    ("回選", "迴圈"),
    ("模具", "模組"),   # ju 與 zu
    ("選購", "宣告"),   # ou 與 ao
    ("所以", "索引"),   # 有沒有鼻音
    ("記憶", "記憶體"),  # 長度不同
]


class MerCase(NamedTuple):
    description: str
    reference: str
    transcript: str
    errors: int
    bucket: str | None     # 期望錯誤分類裡有這一類；None 表示不檢查
    zh_terms: tuple[str, ...] = ()


MER_CASES = [
    MerCase("完全相同", "今天要講資料庫", "今天要講資料庫", 0, None),
    MerCase("簡繁只是字形差異", "請把檔案傳給我", "请把档案传给我", 0, None),
    # 「著」在簡體裡也合法（著作、显著），t2s 不會把它換成「着」，要另外合併
    MerCase("「著」與「着」只是字形差異", "他一直看著我", "他一直看着我", 0, None),
    MerCase("語助詞兩邊都濾掉", "嗯，對啊，就這樣", "對啊就這樣", 0, None),
    MerCase("全形英文", "打開 Docker 之後", "打開 Ｄｏｃｋｅｒ 之後", 0, None),
    MerCase("標點不計分", "好，接下來。", "好接下來", 0, None),
    MerCase("個位數字寫法", "Python 3 的版本", "Python 三 的版本", 0, None),
    MerCase("逐字母縮寫", "用 SQL 查詢", "用 S Q L 查詢", 0, None),
    MerCase("[聽不清] 不計分", "我們先把 [聽不清] 關掉", "我們先把那個關掉", 0, None),
    MerCase("術語拼錯", "把 Docker 重開", "把 doctor 重開", 1, "術語拼寫"),
    MerCase("英文術語變中文", "開 Zoom 會議", "開祖母會議", 2, "跨語言術語"),
    MerCase("口音同音字", "這一步要先執行", "這一步要先字形", 2, "口音同音"),
    # 詞彙替換不該被繁簡正規化洗掉（s2twp 把「默認」換成「預設」就是這種替換）
    MerCase("中文用詞被換掉", "預設值是零", "默認值是零", 2, "中文術語", ("預設",)),
    MerCase("整句漏掉", "等一下再上傳", "", 6, "漏字"),
]


def run() -> bool:
    """逐條印出結果，全部通過時回傳 True。"""
    ok = True
    for title, pairs, expected in (("應判為同音", HOMOPHONES, True),
                                   ("\n應擋掉", NOT_HOMOPHONES, False)):
        print(title)
        for a, b in pairs:
            good = homophone(a, b) == expected
            ok &= good
            print(f"  {'PASS' if good else 'FAIL'}  {a} ({'-'.join(norm_pinyin(a))})"
                  f"  vs  {b} ({'-'.join(norm_pinyin(b))})")

    print("\n錯字率的正規化與錯誤分類")
    for case in MER_CASES:
        score = score_text(case.reference, case.transcript, case.zh_terms)
        good = (score.errors == case.errors
                and (case.bucket is None or case.bucket in score.buckets))
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'}  {case.description}：錯誤 {score.errors}"
              f"（期望 {case.errors}）分類 {score.buckets or '—'}"
              + (f"（期望含 {case.bucket}）" if case.bucket else ""))
    print(f"\n整體：{'PASS' if ok else 'FAIL'}")
    return ok
