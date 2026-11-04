"""掉尾的門檻（#257、#326）：停下的地方之後要有多少聲音才算可能掉尾。

一般情況（提早停止的任務記下起點、片尾靜音不算、分段轉錄取最早的起點）從 API 跑完一個任務來測，見
tests/integration/test_provider_seam.py 的 TestTailLoss 與 TestContinuation；這裡用 #326 的實際長度，
看兩個門檻各自什麼時候成立。
"""
from app.services import tail_loss

END = 1842.35
"""#326 的立法院質詢有 30:42.35。"""
COVERED = 1815.60
"""MOSS 用完生成預算時擔保轉錄到的地方：之後還有 26.75 秒都有聲音。"""
SEGMENTS = [{"start": 1812.98, "end": COVERED}]


def test_truncated_output_with_less_than_a_minute_left_is_tail_loss():
    # 輸出被截斷（轉接器回報了擔保點）：擔保點之後還有 26.75 秒的聲音，不到一分鐘也算
    assert tail_loss.tail_loss_from(SEGMENTS, start=0.0, end=END, silences=(),
                                    covered_until=COVERED) == COVERED


def test_output_that_ended_by_itself_keeps_the_one_minute_margin():
    # 同樣停在 1,815.60 秒，但模型沒有回報擔保點（自己停下、輸出完整）：之後的 26.75 秒可能只是片尾
    # 音樂或環境音，照樣要一分鐘以上的聲音才算
    assert tail_loss.tail_loss_from(SEGMENTS, start=0.0, end=END, silences=()) is None


def test_truncated_output_followed_only_by_silence_is_not_tail_loss():
    # 擔保點之後只剩半秒的聲音、其餘都是靜音：沒有沒轉到的話
    silences = [(COVERED + 0.5, END)]
    assert tail_loss.tail_loss_from(SEGMENTS, start=0.0, end=END, silences=silences,
                                    covered_until=COVERED) is None
