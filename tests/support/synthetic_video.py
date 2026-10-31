"""合成影片：合成音檔（:func:`~tests.support.synthetic_audio.synthetic_audio`）配上純色畫面，用真的 ffmpeg
封裝成上傳收的每一種影片格式（#258）。

只用 CI 與免安裝版的 ffmpeg（BtbN 的 LGPL build）有的編碼器。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.utils.binaries import ffmpeg_bin, ffprobe_bin
from tests.support.synthetic_audio import VOICED, synthetic_audio

CODECS: Dict[str, Tuple[str, ...]] = {
    ".mp4": ("-c:v", "mpeg4", "-c:a", "aac"),
    ".m4v": ("-c:v", "mpeg4", "-c:a", "aac"),
    ".mov": ("-c:v", "mpeg4", "-c:a", "aac"),
    ".mkv": ("-c:v", "mpeg4", "-c:a", "aac"),
    ".webm": ("-c:v", "libvpx", "-c:a", "libopus"),
    ".avi": ("-c:v", "mpeg4", "-c:a", "pcm_s16le"),
    ".wmv": ("-c:v", "wmv2", "-c:a", "wmav2"),
    # MPEG-1 的系統串流：MP2 要 32 kHz 以上
    ".mpg": ("-c:v", "mpeg1video", "-c:a", "mp2", "-ar", "44100"),
    ".mpeg": ("-c:v", "mpeg1video", "-c:a", "mp2", "-ar", "44100"),
}
"""每種影片格式用的編碼器，key 是副檔名。"""


def synthetic_video(
    path: Path,
    voiced: Sequence[Tuple[float, float]] = VOICED,
    *,
    audio_starts_at: float = 0.0,
    with_audio: bool = True,
    title: Optional[str] = None,
) -> Path:
    """寫一個合成影片到 ``path``（格式照副檔名，見 :data:`CODECS`），回傳 ``path``。

    聲音是有聲段（正弦波）與靜音交錯的合成音檔（見 ``synthetic_audio``）；畫面是 64×64 的黑色，
    長度到聲音結束為止。``audio_starts_at`` 秒讓音軌比畫面晚開始（音軌本身的起點，不是前面補
    靜音）；``with_audio`` 是 False 時只有畫面；``title`` 寫進影片的標題標籤。
    """
    duration = audio_starts_at + voiced[-1][1]
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=25:d={duration}"]
    if with_audio:
        audio = path.with_name(f"{path.stem}_source.wav")
        audio.write_bytes(synthetic_audio("WAV", voiced))
        cmd += ["-itsoffset", str(audio_starts_at), "-i", str(audio), "-map", "0:v", "-map", "1:a"]
    if title is not None:
        cmd += ["-metadata", f"title={title}"]
    cmd += [*CODECS[path.suffix.lower()], str(path)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    if with_audio:
        audio.unlink()
    return path


def stream_types(path: Path) -> List[str]:
    """檔案裡每個串流的類型（ffprobe 的 codec_type），依串流順序，例如 ``["video", "audio"]``。"""
    result = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=30)
    return [stream["codec_type"] for stream in json.loads(result.stdout)["streams"]]
