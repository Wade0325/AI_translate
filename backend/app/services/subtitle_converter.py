import re


def convert_to_all_formats(lrc_text: str) -> dict:
    """
    將LRC格式的字幕文本轉換為SRT, VTT, 和 TXT 格式。
    這是一個簡化的實作，主要處理時間標籤。
    """
    if not lrc_text:
        return {"lrc": "", "srt": "", "vtt": "", "txt": ""}

    lines = lrc_text.strip().split('\n')
    srt_lines = []
    vtt_lines = ["WEBVTT", ""]
    txt_lines = []

    # 簡化的時間轉換，例如 [00:01.23]
    time_regex = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)')

    srt_counter = 1
    for line in lines:
        match = time_regex.match(line)
        if match:
            minutes, seconds, ms, text = match.groups()
            text = text.strip()

            # 假設每個字幕持續5秒
            start_time_srt = f"00:{minutes}:{seconds},{ms.ljust(3, '0')}"
            end_seconds = int(seconds) + 5
            end_minutes = int(minutes)
            if end_seconds >= 60:
                end_minutes += 1
                end_seconds -= 60
            end_time_srt = f"00:{str(end_minutes).zfill(2)}:{str(end_seconds).zfill(2)},{ms.ljust(3, '0')}"

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
