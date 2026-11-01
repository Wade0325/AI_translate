import subprocess
import json
import mimetypes
from enum import Enum
from pathlib import Path
from typing import Optional

from app.utils.binaries import ffmpeg_bin, ffprobe_bin
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
                ffprobe_bin(),
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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


FFMPEG_ERRORS_ONLY = ("-hide_banner", "-loglevel", "error")
"""ffmpeg 的 stderr 只輸出錯誤：失敗時 stderr 會寫進 log 與任務的錯誤訊息，預設還會列出音檔的標籤
（標題、作者等，常有人名或地點），日誌檔不能有這些（#231 Q5、#234）。只影響 ffmpeg 輸出的訊息，
不影響轉出的音訊。每個呼叫 ffmpeg 的地方都要加（本機的 asr._to_mono 也用）。"""


def slice_audio(
    file_path: Path,
    output_path: Path,
    start: float = 0.0,
    end: Optional[float] = None,
) -> bool:
    """使用 ffmpeg 切出 [start, end) 區間並輸出為 WAV。

    重新編碼為 PCM 以取得取樣點級精度（stream copy 只能切在封包邊界），
    end=None 表示切到檔尾。
    """
    cmd = [ffmpeg_bin(), *FFMPEG_ERRORS_ONLY, "-y", "-i", str(file_path), "-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-t", f"{end - start:.3f}"]
    cmd.append(str(output_path))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if result.returncode != 0:
            logger.error(
                f"ffmpeg 切割失敗 ({file_path.name}): {result.stderr.strip()[-200:]}")
            return False
        return True
    except FileNotFoundError:
        logger.error("ffmpeg 未安裝或不在 PATH 中")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg 切割逾時 ({file_path.name})")
        return False
    except Exception as e:
        logger.error(f"音訊切割時發生未知錯誤 ({file_path.name}): {e}")
        return False


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
                ffmpeg_bin(), *FFMPEG_ERRORS_ONLY, "-y",
                "-i", str(file_path),
                "-ar", "16000",
                "-ac", "1",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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


EXTRACTED_AUDIO_SUFFIX = ".flac"
"""從影片抽出的音訊存成的格式：無損，Gemini 與本機都收，大小約是 WAV 的一半。"""

EXTRACT_TIMEOUT_SECONDS = 1800
"""抽音訊最多等多久（秒）：2 GB 的影片要讀完整個檔案，在慢的硬碟上也要留足時間。"""


class AudioExtraction(Enum):
    """從影片抽音訊的結果。"""

    EXTRACTED = "extracted"
    NO_AUDIO = "no_audio"
    """影片裡沒有音軌。"""
    FAILED = "failed"
    """ffprobe 或 ffmpeg 讀不了這個檔案（損壞、不支援的編碼、逾時）；原因只記在 log。"""


def has_video(path: Path) -> bool:
    """檔案裡有沒有影像（封面圖不算）：副檔名是音檔、裡面卻是影片時（例如把 .mp4 改成 .m4a），
    上傳時一樣先抽出音訊（#258）。

    MP3、M4A 常附專輯封面，那是 ffprobe 標成 attached_pic 的一張圖，不是影片。ffprobe 讀不了這個檔案
    時當成沒有影像：照原檔留著，轉錄時再以讀不出音檔回報。
    """
    out = _run(
        [ffprobe_bin(), "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=index:stream_disposition=attached_pic", "-of", "json", str(path)],
        path, "ffprobe 檢查影像", timeout=60)
    if out is None:
        return False
    try:
        streams = json.loads(out).get("streams", [])
    except json.JSONDecodeError:
        return False
    return any(not stream.get("disposition", {}).get("attached_pic") for stream in streams)


def extract_audio(video: Path, output: Path) -> AudioExtraction:
    """從影片抽出第一條音軌，存成 FLAC（``output``，副檔名用 :data:`EXTRACTED_AUDIO_SUFFIX`）。

    上傳影片時在本機做，之後只有抽出的音訊會被轉錄或送到供應商（#258）。

    - 不帶影片的標籤與章節（``-map_metadata -1``）：手機拍的影片常把拍攝地點、標題寫在標籤裡，
      沒有去靜音時抽出的音訊會原檔送到 Gemini。
    - 音訊的時間和影片一致（``aresample=async=1:first_pts=0``）：音軌比畫面晚開始時，前面補靜音；
      中間缺的地方也補靜音。不這樣做的話音訊會整段往前移，字幕疊回影片時就對不上。
    - 16-bit：轉錄用不到更高的位元深度，檔案也比較小。

    失敗時刪掉寫了一半的 ``output``；``video`` 由呼叫端處理。
    """
    streams = _run(
        [ffprobe_bin(), "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", str(video)],
        video, "ffprobe 讀取影片", timeout=60)
    if streams is None:
        return AudioExtraction.FAILED
    if not streams.strip():
        logger.info(f"影片沒有音軌: {video.name}")
        return AudioExtraction.NO_AUDIO

    extracted = _run(
        [ffmpeg_bin(), *FFMPEG_ERRORS_ONLY, "-y", "-i", str(video),
         "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
         "-af", "aresample=async=1:first_pts=0", "-sample_fmt", "s16", "-c:a", "flac",
         str(output)],
        video, "ffmpeg 抽出音訊", timeout=EXTRACT_TIMEOUT_SECONDS)
    if extracted is None:
        output.unlink(missing_ok=True)
        return AudioExtraction.FAILED
    logger.info(f"已從影片抽出音訊: {video.name} -> {output.name}")
    return AudioExtraction.EXTRACTED


def _run(cmd: list, source: Path, step: str, *, timeout: float) -> Optional[str]:
    """執行 ffmpeg 或 ffprobe，成功時回傳 stdout；失敗時把原因記進 log、回傳 None。"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.error(f"{step}失敗：找不到 {cmd[0]}")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"{step}逾時（{timeout} 秒）: {source.name}")
        return None
    except Exception as e:
        logger.error(f"{step}時發生未知錯誤 ({source.name}): {e}")
        return None
    if result.returncode != 0:
        logger.error(f"{step}失敗 ({source.name}): {result.stderr.strip()[-500:]}")
        return None
    return result.stdout
