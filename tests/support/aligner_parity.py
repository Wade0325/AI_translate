"""用真的對齊器斷詞，確認本機存下來的逐字時間，輸出格式模組都用得上。

tests/unit/test_output_format.py 另開一個直譯器執行這支腳本：conftest 把 torch 換成假的，
同一個行程裡匯入不了 transformers。斷詞用不到 torch，這裡把它擋掉，載入只要一兩秒。

本機的轉接器把片段文字先在斷行標點後補空白（asr._insert_align_breaks），再交給
Qwen3-ForcedAligner；存下來的逐字時間就是它照 Qwen3ASRProcessor.split_words_for_alignment
（不指定語言）斷出來的詞。輸出格式模組自己照同樣的規則斷詞，和存下來的詞一個一個相同時才用
逐字時間斷行，對不上就整段一行、時間是片段的開頭。

隨機產生含各種字元（假名、全形與半形、符號、表情符號、合成字元、擴展區漢字……）的片段，
逐字時間照真的對齊器斷詞，每一段的第一行都要從第一個詞開始，而不是片段的開頭。
有不同時印出前幾個，結束碼 1。
"""

import random
import sys
from pathlib import Path

sys.modules["torch"] = None
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from transformers.models.qwen3_asr.processing_qwen3_asr import Qwen3ASRProcessor  # noqa: E402

from app.provider.local import asr  # noqa: E402
from app.services import output_format  # noqa: E402
from app.services.transcription.models import TranscriptionTaskResult  # noqa: E402

POOLS = [
    "今日本当天気時程預算先定再談人来食待々〆ヶ",
    "おはようございますそうなのラーメンカタカナｶﾞﾝﾊﾞﾚ",
    "abcXYZ0123456789０１２３'’",
    "。．！？!?…、，,",
    " 　\t ",
    "「」『』（）()[]【】♡♪～~ー―-・：:;＊*#＃@＠%％&＆\"“”",
    "😀🎵𠀋𪚲゙́",
]
WORD_SECONDS = 0.08
"""對齊器的時間一格 80 毫秒；片段從 0 秒開始，第一個詞從第一格開始。"""


def stored_words(text: str) -> list[str]:
    """本機存下來的逐字時間的詞：真的對齊器斷本機餵給它的文字。"""
    return Qwen3ASRProcessor.split_words_for_alignment(None, asr._insert_align_breaks(text), None)


def first_line(text: str, words: list[str]) -> str:
    """片段（0 秒開始，第 i 個詞在第 i + 1 格）產生的 LRC 的第一行。"""
    segment = {"start": 0.0, "end": WORD_SECONDS * (len(words) + 2), "speaker": "S0",
               "text": text,
               "words": [{"text": word, "start": WORD_SECONDS * (i + 1),
                          "end": WORD_SECONDS * (i + 2)} for i, word in enumerate(words)]}
    lrc = output_format.for_result(TranscriptionTaskResult(success=True, segments=[segment])).lrc
    return lrc.split("\n")[0]


def main() -> int:
    rng = random.Random(109)
    mismatches = []
    checked = 0
    while checked < 2000:
        text = "".join(rng.choice(rng.choice(POOLS)) for _ in range(rng.randint(1, 40))).strip()
        words = stored_words(text)
        if not words:
            continue
        checked += 1
        line = first_line(text, words)
        if not line.startswith("[00:00.08]"):
            mismatches.append((text, words, line))
    for text, words, line in mismatches[:5]:
        print(f"文字 {text!r}\n  對齊器的詞 {words!r}\n  第一行 {line!r}")
    print(f"{len(mismatches)} / {checked} 個片段沒用上逐字時間")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
