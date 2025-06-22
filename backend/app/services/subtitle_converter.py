import re
from datetime import timedelta


def _seconds_to_srt_time(seconds: float) -> str:
    """將總秒數轉換為 SRT/VTT 的時間格式 (HH:MM:SS,ms)"""
    if seconds < 0:
        seconds = 0
    total_seconds_int = int(seconds)
    milliseconds = int((seconds - total_seconds_int) * 1000)

    hours, remainder = divmod(total_seconds_int, 3600)
    minutes, seconds_rem = divmod(remainder, 60)

    return f"{hours:02d}:{minutes:02d}:{seconds_rem:02d},{milliseconds:03d}"


def convert_to_all_formats(lrc_text: str) -> dict:
    """
    將一份完整的 LRC 格式字幕文本轉換為 SRT, VTT, 和 TXT 格式。
    """
    if not lrc_text or not isinstance(lrc_text, str):
        return {"lrc": "", "srt": "", "vtt": "", "txt": ""}

    lines = lrc_text.strip().split('\n')
    srt_lines = []
    vtt_lines = ["WEBVTT", ""]
    txt_lines = []

    time_regex = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)')
    srt_counter = 1

    # 為了計算 SRT 的結束時間，需要窺探下一行的時間戳
    timestamps = []
    for line in lines:
        match = time_regex.match(line)
        if match:
            minutes, seconds, ms_str, text = match.groups()
            total_seconds = int(minutes) * 60 + \
                int(seconds) + float(f"0.{ms_str}")
            timestamps.append({"time": total_seconds, "text": text.strip()})

    if not timestamps:
        # 如果沒有時間戳，就當作純文本處理
        plain_text = "\n".join(l for l in lines if not l.startswith('['))
        return {
            "lrc": lrc_text, "srt": "", "vtt": "", "txt": plain_text
        }

    for i, current in enumerate(timestamps):
        start_time_sec = current["time"]
        text = current["text"]

        # 決定結束時間
        if i + 1 < len(timestamps):
            # 結束時間是下一行的開始時間
            end_time_sec = timestamps[i+1]["time"]
        else:
            # 最後一行，假設持續 5 秒
            end_time_sec = start_time_sec + 5.0

        start_time_srt = _seconds_to_srt_time(start_time_sec)
        end_time_srt = _seconds_to_srt_time(end_time_sec)
        start_time_vtt = start_time_srt.replace(',', '.')
        end_time_vtt = end_time_srt.replace(',', '.')

        # SRT
        srt_lines.append(str(srt_counter))
        srt_lines.append(f"{start_time_srt} --> {end_time_srt}")
        srt_lines.append(text)
        srt_lines.append("")
        srt_counter += 1

        # VTT
        vtt_lines.append(f"{start_time_vtt} --> {end_time_vtt}")
        vtt_lines.append(text)
        vtt_lines.append("")

        # TXT
        txt_lines.append(text)

    return {
        "lrc": lrc_text,
        "srt": "\n".join(srt_lines),
        "vtt": "\n".join(vtt_lines),
        "txt": "\n".join(txt_lines)
    }
