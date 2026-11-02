"""字幕格式驗收（#271）：免安裝模式起一個獨立的 app，供應商換成照劇本回傳的假供應商。

劇本是刻意設計的轉錄結果，涵蓋顏色、重疊、特殊字元、時間的捨入與超過一小時、長字幕拆開；
搭配 1:01:00 的測試影片（subtitle-test.mp4，畫面上方燒進時間碼）。不去靜音、不切段，所以劇本
的時間就是原音檔的時間。

用法：APP_MODE=standalone AIT_DATA_DIR=<暫存資料夾> python launch_app.py <repo> <埠>
"""
import dataclasses
import sys

REPO, PORT = sys.argv[1], int(sys.argv[2])
sys.path[:0] = [REPO + "/backend", REPO]

from app.provider import registry  # noqa: E402
from app.services.output_format import aligner_words  # noqa: E402
from tests.support.fake_provider import CAPABILITIES, FakeProvider  # noqa: E402


def words(text, start, end):
    """對齊器會斷出的詞，平均分配在 start 到 end 之間；start == end 時每個詞都是零長度。"""
    tokens = aligner_words(text)
    step = (end - start) / len(tokens)
    return [(w, round(start + i * step, 3), round(start + (i + 1) * step, 3))
            for i, w in enumerate(tokens)]


def line(start, end, speaker, text):
    return (start, end, speaker, text, words(text, start, end))


LINES = [
    # 顏色：S0 白、S1 黃、S2 青、S3 綠
    line(1.0, 3.5, 0, "字幕測試開始。這行是白色。"),
    line(4.0, 6.0, 1, "黃色的說話者。こんにちは。"),
    line(6.5, 8.5, 2, "青色的說話者。"),
    line(9.0, 11.0, 3, "綠色的說話者。"),
    # 重疊（ADR-0008）：S1 講長句，S0 在 15.97 插一個零長度的「對」，至少顯示 0.8 秒
    line(12.0, 20.45, 1, "我們下週一要交報告，資料我已經整理好了，等一下寄給大家。"),
    line(15.97, 15.97, 0, "對。"),
    # 特殊字元
    line(22.0, 24.0, 0, "A & B <笑> --> x"),
    line(25.0, 27.0, 1, "1 < 2 && 3 > 2"),
    line(28.0, 30.0, 2, "<i>はい</i>です"),
    line(31.0, 33.0, 3, "♪～「引號」『括號』…！？ 😊♡"),
    # 時間的捨入：34.996 → 35.00；59.996 → LRC 寫 [01:00.00]，不是 [00:60.00]
    line(34.996, 36.5, 0, "這行從三十四點九九六秒開始"),
    line(59.996, 61.5, 1, "這行從五十九點九九六秒開始"),
    # 長字幕依逐字時間拆成數則（#12）：日文上限 26 個全形字寬，其他 32
    line(63.0, 74.0, 2, "今日はとてもいい天気ですね、みんなで公園に行ってゆっくり休んでから、"
                        "おいしいご飯を食べに行きましょう。"),
    line(76.0, 86.0, 3, "這是一句很長的中文字幕，用來檢查超過三十二個全形字寬時，"
                        "會不會依照逐字時間拆成好幾則字幕。"),
    # 超過一小時：SRT／VTT 的小時欄、LRC 的分鐘欄 ≥ 60
    line(3599.5, 3601.5, 0, "跨過一小時。"),
    line(3605.0, 3608.0, 1, "這行在一小時零五秒開始"),
    line(3650.0, 3655.0, 0, "最後一行。"),
]

fake = FakeProvider(script=[LINES] * 20)
# 不去靜音、不切段：劇本的時間就是原音檔的時間
fake.model_capabilities = dataclasses.replace(CAPABILITIES, single_pass_seconds=7200,
                                              remove_silence=False)
registry.register("fake", fake)

import uvicorn  # noqa: E402
from main import app  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=PORT)
