from typing import List, Dict

from app.services.converter.service import _parse_lrc
from app.services.silence_removal import SpeechTimeline


def remap_lrc_timestamps(lrc_text: str, segments: List[Dict[str, float]]) -> str:
    """LRC 的時間從只剩語音的音檔還原回原音檔的時間軸；``segments`` 是去靜音保留下來的有聲段。

    只剩批次在用：單檔任務的轉錄結果是片段，由語音視圖還原（:meth:`SpeechView.restore`）。
    兩邊用同一個時間還原（:class:`SpeechTimeline`），時間軸才不會分岔；LRC 只有開始時間。
    批次改成處理轉錄結果時（#115）刪掉。
    """
    parsed_lines = _parse_lrc(lrc_text)
    if not parsed_lines:
        return ""

    timeline = SpeechTimeline(tuple((seg["start"], seg["end"]) for seg in segments))
    remapped_lrc_lines = []
    for line in parsed_lines:
        remapped_time = timeline.to_original(line.time)
        minutes = int(remapped_time // 60)
        seconds = int(remapped_time % 60)
        centiseconds = int((remapped_time - int(remapped_time)) * 100)  # 保持2位數
        remapped_lrc_lines.append(
            f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]{line.text}")

    return "\n".join(remapped_lrc_lines)
