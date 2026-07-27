"""ffmpeg / ffprobe 執行檔定位。

docker 模式（含主機 GPU worker）維持現狀：直接用 PATH 上的執行檔名。
standalone 模式由 launcher 以 AIT_FFMPEG_DIR 指向隨包的 bin/ 目錄。
"""

from pathlib import Path

from app.core.config import get_settings


def _resolve(name: str) -> str:
    ffmpeg_dir = get_settings().ffmpeg_dir
    if not ffmpeg_dir:
        return name
    base = Path(ffmpeg_dir) / name
    exe = base.with_suffix(".exe")
    return str(exe if exe.exists() else base)


def ffmpeg_bin() -> str:
    return _resolve("ffmpeg")


def ffprobe_bin() -> str:
    return _resolve("ffprobe")
