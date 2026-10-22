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


def synthetic_audio(fmt: str = "WAV", voiced=VOICED) -> bytes:
    """有聲段（正弦波）與靜音段交錯的合成音檔，到最後一個有聲段結束；預設見 VOICED。"""
    samples = np.zeros(int(voiced[-1][1] * SAMPLE_RATE), dtype=np.float32)
    for start, end in voiced:
        t = np.arange(int((end - start) * SAMPLE_RATE)) / SAMPLE_RATE
        samples[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)] = 0.3 * np.sin(2 * np.pi * 440 * t)
    buffer = io.BytesIO()
    sf.write(buffer, samples, SAMPLE_RATE, format=fmt)
    return buffer.getvalue()
