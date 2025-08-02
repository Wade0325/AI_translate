import re
from datetime import timedelta

# --- 輔助函式 ---


def _seconds_to_timestamp(seconds: float, separator: str = ',') -> str:
    """將秒數轉換為 SRT 或 VTT 的時間格式 (HH:MM:SS,ms or HH:MM:SS.ms)"""
    # 確保秒數不是負數
    if seconds < 0:
        seconds = 0
    # 使用 timedelta 進行時間計算
    td = timedelta(seconds=seconds)
    # 取得總秒數和微秒
    total_seconds = int(td.total_seconds())
    microseconds = td.microseconds
    # 計算時、分、秒
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    # 格式化毫秒
    milliseconds = microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"

# --- 核心轉換邏輯 ---


def _parse_lrc(lrc_text: str):
    """從 LRC 文字中解析出 (時間, 文字) 的元組列表"""
    # [分鐘]:[秒數].[百分秒]
    lrc_line_re = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)')
    parsed_lines = []
    for line in lrc_text.strip().split('\n'):
        match = lrc_line_re.match(line)
        if match:
            minutes, seconds, ms, text = match.groups()
            # 處理2位數或3位數的毫秒
            ms_val = int(ms) if len(ms) == 3 else int(ms) * 10
            time_in_seconds = int(minutes) * 60 + \
                int(seconds) + ms_val / 1000.0
            # 忽略沒有文字的行
            if text.strip():
                parsed_lines.append(
                    {'time': time_in_seconds, 'text': text.strip()})
    return parsed_lines


def _to_srt(lrc_text: str, last_line_duration: float = 5.0) -> str:
    """將 LRC 格式轉換為 SRT 格式"""
    parsed_lines = _parse_lrc(lrc_text)
    if not parsed_lines:
        return ""

    srt_blocks = []
    for i in range(len(parsed_lines)):
        start_time = parsed_lines[i]['time']
        text = parsed_lines[i]['text']

        # 決定結束時間
        if i < len(parsed_lines) - 1:
            # 結束時間是下一行的開始時間
            end_time = parsed_lines[i+1]['time']
        else:
            # 最後一行，給一個固定的持續時間
            end_time = start_time + last_line_duration

        # 建立 SRT 區塊
        srt_blocks.append(
            f"{i+1}\n"
            f"{_seconds_to_timestamp(start_time, ',')} --> {_seconds_to_timestamp(end_time, ',')}\n"
            f"{text}\n"
        )
    return "\n".join(srt_blocks)


def _to_vtt(lrc_text: str, last_line_duration: float = 5.0) -> str:
    """將 LRC 格式轉換為 VTT 格式"""
    parsed_lines = _parse_lrc(lrc_text)
    if not parsed_lines:
        return "WEBVTT\n\n"

    vtt_blocks = ["WEBVTT\n"]
    for i in range(len(parsed_lines)):
        start_time = parsed_lines[i]['time']
        text = parsed_lines[i]['text']

        if i < len(parsed_lines) - 1:
            end_time = parsed_lines[i+1]['time']
        else:
            end_time = start_time + last_line_duration

        vtt_blocks.append(
            f"{_seconds_to_timestamp(start_time, '.')} --> {_seconds_to_timestamp(end_time, '.')}\n"
            f"{text}\n"
        )
    return "\n".join(vtt_blocks)


def convert_to_all_formats(lrc_text: str):
    """將 LRC 文字轉換為所有支援的格式"""
    if not lrc_text or not lrc_text.strip():
        return {
            "lrc": "",
            "srt": "",
            "vtt": "",
            "txt": ""
        }

    # 從LRC中提取純文字
    plain_text = "\n".join(re.findall(r'\](.*)', lrc_text))

    return {
        "lrc": lrc_text,
        "srt": _to_srt(lrc_text),
        "vtt": _to_vtt(lrc_text),
        "txt": plain_text.strip()
    }
