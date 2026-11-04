"""合成音檔：有聲段（正弦波）與靜音段交錯，用 numpy 與 soundfile 產生（#103）。

整合測試用它經真實的 ffmpeg 轉檔、去靜音、切音檔與取得長度。
"""

import io

import numpy as np
import soundfile as sf

SAMPLE_RATE = 16000

VOICED = [(0.0, 2.0), (5.0, 7.0), (10.0, 12.0)]
"""預設的有聲段（秒）：有聲 2、靜音 3 交錯，共 12 秒。語音佔比 60%，低於門檻，會去靜音：有聲段前後
各留 0.3 秒，送進模型的是 0–2.3、4.7–7.3、9.7–12 秒接成的 7.2 秒。"""

TONE = 440
"""有聲段預設的正弦波頻率（Hz）。"""


def synthetic_audio(fmt: str = "WAV", voiced=VOICED, length: float | None = None) -> bytes:
    """有聲段（正弦波）與靜音段交錯的合成音檔；預設見 VOICED。

    每個有聲段是（起, 迄）或（起, 迄, 頻率 Hz），沒給頻率時是 :data:`TONE`：假供應商照音檔回答時
    （``Listen``）依頻率分辨說話者。``length`` 是音檔的長度（秒），最後一個有聲段之後補靜音到這麼長；
    沒給時到最後一個有聲段結束。
    """
    samples = np.zeros(int(max(voiced[-1][1], length or 0.0) * SAMPLE_RATE), dtype=np.float32)
    for start, end, *tone in voiced:
        t = np.arange(int((end - start) * SAMPLE_RATE)) / SAMPLE_RATE
        frequency = tone[0] if tone else TONE
        samples[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)] = (
            0.3 * np.sin(2 * np.pi * frequency * t))
    buffer = io.BytesIO()
    sf.write(buffer, samples, SAMPLE_RATE, format=fmt)
    return buffer.getvalue()
