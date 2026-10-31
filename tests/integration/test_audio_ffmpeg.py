"""用真的 ffmpeg 與 ffprobe 處理合成音檔：取得長度、轉檔、切音檔（#103），從影片抽出音訊（#258），
以及失敗時不把音檔的標籤寫進 log 與錯誤訊息（#234）。

找不到 ffmpeg 時要失敗而不是跳過：CI 的 Python job 會裝好釘版的 ffmpeg，
本機要自己裝，或用 AIT_FFMPEG_DIR 指到放 ffmpeg 的資料夾。
"""

import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from app.core.upload_formats import UPLOAD_FORMATS
from app.provider.local import asr
from app.utils.audio import (
    AudioExtraction,
    convert_to_wav,
    extract_audio,
    get_audio_duration,
    has_video,
    slice_audio,
)
from app.utils.binaries import ffmpeg_bin, ffprobe_bin
from tests.support.synthetic_audio import VOICED
from tests.support.synthetic_video import CODECS, audio_with_cover, stream_types, synthetic_video

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


@pytest.fixture
def tagged_flac(tmp_path):
    """標題標籤寫著人名與地點的 FLAC（手機錄音常把地點寫進標題）。"""
    path = tmp_path / "tagged.flac"
    with sf.SoundFile(path, "w", SAMPLE_RATE, 1, format="FLAC") as f:
        f.title = "王小明家住台北市"
        f.write(np.zeros(SAMPLE_RATE))
    return path


@pytest.mark.parametrize("fails", [
    lambda audio, folder: convert_to_wav(audio, folder) is None,
    lambda audio, folder: not slice_audio(audio, folder / "part.wav", 0.0, 0.5),
], ids=["convert", "slice"])
def test_failure_is_logged_without_the_audio_tags(tagged_flac, tmp_path, app_log, fails):
    # 失敗時 log 照記 ffmpeg 的錯誤，但不記音檔的標籤：日誌檔不寫個人資料（#231 Q5）。
    # 輸出的資料夾不存在，ffmpeg 一定失敗
    assert fails(tagged_flac, tmp_path / "missing-folder")

    log = "\n".join(app_log)
    assert "missing-folder" in log
    assert "王小明" not in log


def test_local_mono_failure_message_has_no_audio_tags(tagged_flac):
    # 本機轉錄先轉成單聲道；失敗時 ffmpeg 的錯誤進任務的錯誤訊息與 log，一樣不能有標籤。
    # 輸出的位置已經是資料夾，ffmpeg 一定失敗
    output = tagged_flac.parent / f"{tagged_flac.stem}_mono16k.wav"
    output.mkdir()

    with pytest.raises(RuntimeError) as failure:
        asr._to_mono(tagged_flac, asr.MOSS_SAMPLE_RATE)

    assert output.name in str(failure.value)
    assert "王小明" not in str(failure.value)


# ─── 從影片抽出音訊（#258） ─────────────────────────────────────────────────

VIDEO_FORMATS = [f for f in UPLOAD_FORMATS if f.kind == "video"]


def first_sound_and_length(path) -> tuple[float, float]:
    """音檔裡第一個有聲音的時間點與總長（秒）。"""
    samples, rate = sf.read(path)
    return float(np.flatnonzero(np.abs(samples) > 0.05)[0] / rate), len(samples) / rate


def tags(path) -> str:
    result = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_entries", "format_tags:stream_tags", "-of", "json",
         str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30)
    return result.stdout


@pytest.mark.parametrize("video_format", VIDEO_FORMATS, ids=lambda f: f.label)
def test_every_accepted_video_format_gives_audio_only_flac(video_format, tmp_path):
    # 收的格式都要真的抽得出來：清單加了新格式，這裡要能做出那種影片（CODECS）
    assert video_format.extension in CODECS, f"tests/support/synthetic_video.py 做不出 {video_format.label}"
    video = synthetic_video(tmp_path / f"clip{video_format.extension}")
    audio = tmp_path / "clip.flac"

    assert extract_audio(video, audio) is AudioExtraction.EXTRACTED

    assert stream_types(video) == ["video", "audio"]
    assert stream_types(audio) == ["audio"]
    assert sf.info(audio).format == "FLAC"
    assert get_audio_duration(audio) == pytest.approx(VOICED[-1][1], abs=0.1)


def test_audio_that_starts_after_the_picture_keeps_the_video_timeline(tmp_path):
    # 音軌比畫面晚 1.5 秒開始：前面補 1.5 秒靜音，字幕的時間才對得上影片。不補的話第一個聲音在 0 秒
    video = synthetic_video(tmp_path / "late.mp4", audio_starts_at=1.5)
    audio = tmp_path / "late.flac"

    assert extract_audio(video, audio) is AudioExtraction.EXTRACTED

    first_sound, length = first_sound_and_length(audio)
    assert first_sound == pytest.approx(1.5, abs=0.02)
    assert length == pytest.approx(1.5 + VOICED[-1][1], abs=0.1)


def test_the_video_tags_are_not_carried_over(tmp_path):
    # 手機拍的影片常把拍攝地點、人名寫在標籤裡；抽出的音訊可能原檔送到 Gemini
    video = synthetic_video(tmp_path / "phone.mov", title="王小明家住台北市")
    audio = tmp_path / "phone.flac"

    assert extract_audio(video, audio) is AudioExtraction.EXTRACTED

    assert "王小明" in tags(video)
    assert "王小明" not in tags(audio)


def test_video_without_sound(tmp_path):
    video = synthetic_video(tmp_path / "silent.mp4", with_audio=False)
    audio = tmp_path / "silent.flac"

    assert extract_audio(video, audio) is AudioExtraction.NO_AUDIO
    assert not audio.exists()


@pytest.mark.parametrize("content", [b"\x00" * 1024, b"not a video at all"])
def test_unreadable_video_fails_and_leaves_nothing(tmp_path, content, app_log):
    video = tmp_path / "broken.mp4"
    video.write_bytes(content)
    audio = tmp_path / "broken.flac"

    assert extract_audio(video, audio) is AudioExtraction.FAILED
    assert not audio.exists()
    assert any("broken.mp4" in entry for entry in app_log)


def test_video_renamed_as_audio_has_video(tmp_path):
    video = synthetic_video(tmp_path / "clip.mp4")
    renamed = video.rename(tmp_path / "clip.m4a")

    assert has_video(renamed)


@pytest.mark.parametrize("name", ["song.mp3", "song.m4a"])
def test_album_cover_is_not_video(tmp_path, name):
    audio = audio_with_cover(tmp_path / name)

    assert stream_types(audio) == ["audio", "video"]
    assert not has_video(audio)


def test_plain_and_unreadable_audio_have_no_video(stereo_flac, tmp_path):
    broken = tmp_path / "broken.m4a"
    broken.write_bytes(b"\x00" * 512)

    assert not has_video(stereo_flac)
    assert not has_video(broken)
