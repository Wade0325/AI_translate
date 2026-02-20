import subprocess
import json
from pathlib import Path
from typing import Optional

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


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
