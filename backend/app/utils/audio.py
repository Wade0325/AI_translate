import subprocess
import json
import mimetypes
from pathlib import Path
from typing import Optional

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

AUDIO_MIME_MAP = {
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".webm": "audio/webm",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
}


def get_audio_duration(file_path: Path) -> Optional[float]:
    """
    使用 ffprobe 取得音訊檔案時長（秒）。
    支援所有 ffmpeg 可解碼的格式，包括 M4A、MP3、WAV、FLAC 等。
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"ffprobe 執行失敗 ({file_path.name}): {result.stderr.strip()}")
            return None

        info = json.loads(result.stdout)
        duration = float(info["format"]["duration"])
        return duration

    except FileNotFoundError:
        logger.error("ffprobe 未安裝或不在 PATH 中")
        return None
    except (KeyError, json.JSONDecodeError, ValueError) as e:
        logger.error(f"無法解析 ffprobe 輸出 ({file_path.name}): {e}")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"ffprobe 執行逾時 ({file_path.name})")
        return None
    except Exception as e:
        logger.error(f"取得音訊時長時發生未知錯誤 ({file_path.name}): {e}")
        return None


def get_mime_type(file_path: Path) -> Optional[str]:
    """
    取得音訊檔案的 MIME 類型。
    優先使用內建對照表，再 fallback 到 mimetypes 模組。
    """
    suffix = file_path.suffix.lower()
    mime = AUDIO_MIME_MAP.get(suffix)
    if mime:
        return mime
    mime, _ = mimetypes.guess_type(str(file_path))
    return mime


def convert_to_wav(file_path: Path, output_dir: Path) -> Optional[Path]:
    """
    使用 ffmpeg 將音訊檔案轉換為 WAV 格式。
    如果檔案已是 wav 格式則直接回傳原始路徑。
    """
    if file_path.suffix.lower() == ".wav":
        return file_path

    output_path = output_dir / f"{file_path.stem}_converted.wav"
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(file_path),
                "-ar", "16000",
                "-ac", "1",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg 轉換失敗 ({file_path.name}): {result.stderr.strip()}")
            return None

        logger.info(f"音訊已轉換為 WAV: {file_path.name} -> {output_path.name}")
        return output_path

    except FileNotFoundError:
        logger.error("ffmpeg 未安裝或不在 PATH 中")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg 轉換逾時 ({file_path.name})")
        return None
    except Exception as e:
        logger.error(f"音訊轉換時發生未知錯誤 ({file_path.name}): {e}")
        return None
