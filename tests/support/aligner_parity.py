"""用真的對齊器斷詞，對照本機的 LRC 和從片段產生的 LRC。

tests/unit/test_output_format.py 另開一個直譯器執行這支腳本：conftest 把 torch 換成假的，
同一個行程裡匯入不了 transformers。斷詞用不到 torch，這裡把它擋掉，載入只要一兩秒。

隨機產生含各種字元（假名、全形與半形、符號、表情符號、合成字元、擴展區漢字……）的本機片段，
詞照 Qwen3ASRProcessor.split_words_for_alignment（不指定語言）斷，和本機一樣。從片段產生的
LRC 要和本機的斷行（asr._entry_to_lines）逐字相同。文字不含換行：那是刻意不同的地方。
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
GAPS_MS = (0, 0, 80, 160, 400, 1200, 4000, 9600, 37)
LENGTHS_MS = (80, 160, 320, 640, 1600, 6000, 113)


def aligner_words(text: str) -> list[str]:
    return Qwen3ASRProcessor.split_words_for_alignment(None, asr._insert_align_breaks(text), None)


def random_entry(rng: random.Random) -> dict:
    text = ""
    while not text:
        text = "".join(rng.choice(rng.choice(POOLS)) for _ in range(rng.randint(1, 40))).strip()
    ms, timings = 0, []
    for word in aligner_words(text):
        ms += rng.choice(GAPS_MS)
        start_ms = ms
        ms += rng.choice(LENGTHS_MS)
        timings.append({"text": word, "start_time": round(start_ms / 1000.0, 3),
                        "end_time": round(ms / 1000.0, 3)})
    start = round(rng.uniform(0, 5000), 2)
    return {"start": start, "end": round(start + ms / 1000 + 0.5, 2),
            "speaker": rng.randint(0, 2), "text": text, "text_alt": None, "words": timings}


def main() -> int:
    rng = random.Random(109)
    mismatches = []
    for _ in range(2000):
        entry = random_entry(rng)
        expected = "\n".join(asr._entry_to_lines(entry, lambda text: len(aligner_words(text))))
        segments = asr._build_segment_records([entry])
        actual = output_format.for_result(
            TranscriptionTaskResult(success=True, segments=segments)).lrc
        if actual != expected:
            mismatches.append((entry["text"], expected, actual))
    for text, expected, actual in mismatches[:5]:
        print(f"文字 {text!r}\n  本機 {expected!r}\n  片段 {actual!r}")
    print(f"{len(mismatches)} / 2000 個片段不同")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
