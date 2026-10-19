"""用真的 ffmpeg 與 ffprobe 處理合成音檔：取得長度、轉檔、切音檔（#103）。

找不到 ffmpeg 時要失敗而不是跳過：CI 的 Python job 會裝好釘版的 ffmpeg，
本機要自己裝，或用 AIT_FFMPEG_DIR 指到放 ffmpeg 的資料夾。
"""

import shutil

import numpy as np
import pytest
import soundfile as sf

from app.utils.audio import convert_to_wav, get_audio_duration, slice_audio
from app.utils.binaries import ffmpeg_bin, ffprobe_bin

SAMPLE_RATE = 44100
DURATION = 3.0


@pytest.fixture(scope="module", autouse=True)
def require_ffmpeg():
    for exe in (ffmpeg_bin(), ffprobe_bin()):
        assert shutil.which(exe), f"找不到 {exe}：測試需要 ffmpeg 與 ffprobe"


@pytest.fixture
def stereo_flac(tmp_path):
    """3 秒、44.1 kHz 雙聲道的 440 Hz 正弦波，存成 FLAC（不是 wav，轉檔才會真的跑）。"""
    t = np.arange(int(SAMPLE_RATE * DURATION)) / SAMPLE_RATE
    tone = 0.3 * np.sin(2 * np.pi * 440 * t)
    path = tmp_path / "tone.flac"
    sf.write(path, np.column_stack([tone, tone]), SAMPLE_RATE)
    return path


def test_duration_of_synthetic_audio(stereo_flac):
    assert get_audio_duration(stereo_flac) == pytest.approx(DURATION, abs=0.01)


def test_convert_to_16k_mono_wav(stereo_flac, tmp_path):
    out = convert_to_wav(stereo_flac, tmp_path)

    assert out is not None and out.suffix == ".wav"
    info = sf.info(out)
    assert (info.samplerate, info.channels) == (16000, 1)
    assert get_audio_duration(out) == pytest.approx(DURATION, abs=0.01)


def test_slice_keeps_requested_range(stereo_flac, tmp_path):
    out = tmp_path / "slice.wav"

    assert slice_audio(stereo_flac, out, start=0.5, end=2.0)
    assert sf.info(out).duration == pytest.approx(1.5, abs=0.01)
