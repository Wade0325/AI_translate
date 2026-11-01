"""執行外部指令，只拿標準輸出：問驅動與 ffmpeg 的版本用。"""

from __future__ import annotations

import subprocess

TIMEOUT_SECONDS = 10
"""指令最多跑多久；卡住時照樣往下走。"""


def command_output(*command: str) -> str | None:
    """執行指令，回傳標準輸出；找不到、失敗或逾時時是 None，呼叫的地方照樣往下走。"""
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None
