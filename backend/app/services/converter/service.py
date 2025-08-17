import re
from typing import List, Optional

from app.utils.logger import setup_logger
from .models import SubtitleFormats

logger = setup_logger(__name__)


class _ParsedLine:
    """一個內部輔助類別，用於表示解析後的單行字幕。"""

    def __init__(self, time: float, text: str):
        self.time = time
        self.text = text


def _seconds_to_timestamp(seconds: float, separator: str = ',') -> str:
    """將秒數轉換為 HH:MM:SS,ms 或 HH:MM:SS.ms 格式的時間戳。"""
    if seconds < 0:
        seconds = 0
    hours = int(seconds / 3600)
    minutes = int((seconds % 3600) / 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


def _parse_lrc(lrc_text: str) -> List[_ParsedLine]:
    """將 LRC 格式的純文字解析成帶有時間戳的行物件列表。"""
    parsed_lines: List[_ParsedLine] = []
    if not lrc_text:
        return parsed_lines

    for line in lrc_text.strip().split('\n'):
        # 匹配 [mm:ss.xx] 或 [mm:ss.xxx] 格式
        match = re.match(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)', line)
        if match:
            minutes, seconds, ms_str, text_content = match.groups()
            time_in_seconds = int(
                minutes) * 60 + int(seconds) + float(f"0.{ms_str}")

            # 移除 Gemini 可能回傳的 "Speaker A: " 標籤
            cleaned_text = re.sub(
                r'^\s*Speaker\s+[A-Z]:\s*', '', text_content.strip())
            parsed_lines.append(
                _ParsedLine(time=time_in_seconds, text=cleaned_text))
    return parsed_lines


def _to_srt(lines: List[_ParsedLine]) -> str:
    """將解析後的行物件列表轉換為 SRT 格式的純文字。"""
    srt_content = []
    for i, line in enumerate(lines):
        start_time = _seconds_to_timestamp(line.time, separator=',')

        # 結束時間設定為下一行的開始時間，或如果是最後一行則預設為 5 秒
        if i + 1 < len(lines):
            end_time = _seconds_to_timestamp(lines[i+1].time, separator=',')
        else:
            end_time = _seconds_to_timestamp(line.time + 5.0, separator=',')

        srt_content.append(f"{i + 1}")
        srt_content.append(f"{start_time} --> {end_time}")
        srt_content.append(line.text)
        srt_content.append("")

    return "\n".join(srt_content)


def _to_vtt(lines: List[_ParsedLine]) -> str:
    """將解析後的行物件列表轉換為 VTT 格式的純文字。"""
    vtt_content = ["WEBVTT", ""]
    for i, line in enumerate(lines):
        start_time = _seconds_to_timestamp(line.time, separator='.')

        if i + 1 < len(lines):
            end_time = _seconds_to_timestamp(lines[i+1].time, separator='.')
        else:
            end_time = _seconds_to_timestamp(line.time + 5.0, separator='.')

        vtt_content.append(f"{start_time} --> {end_time}")
        vtt_content.append(line.text)
        vtt_content.append("")

    return "\n".join(vtt_content)


def _to_txt(lines: List[_ParsedLine]) -> str:
    """將解析後的行物件列表轉換為純文字 (TXT)。"""
    return "\n".join(line.text for line in lines)


def convert_from_lrc(lrc_text: str) -> SubtitleFormats:
    """
    接收 LRC 格式的純文字，並將其轉換為所有支援的字幕格式。

    :param lrc_text: 包含 LRC 內容的字串。
    :return: 一個包含所有格式字幕的 SubtitleFormats 物件。
    """
    if not lrc_text or not lrc_text.strip():
        logger.warning("LRC 輸入為空，回傳空的字幕檔案。")
        return SubtitleFormats(lrc="", srt="", vtt="", txt="")

    logger.info("開始從 LRC 進行字幕格式轉換。")
    parsed_lines = _parse_lrc(lrc_text)

    if not parsed_lines:
        logger.warning("無法從 LRC 輸入中解析出任何有效的行。")
        return SubtitleFormats(lrc=lrc_text, srt="", vtt="", txt="")

    srt = _to_srt(parsed_lines)
    vtt = _to_vtt(parsed_lines)
    txt = _to_txt(parsed_lines)

    logger.info("成功將 LRC 轉換為 SRT, VTT, 和 TXT 格式。")

    return SubtitleFormats(
        lrc=lrc_text,
        srt=srt,
        vtt=vtt,
        txt=txt
    )
