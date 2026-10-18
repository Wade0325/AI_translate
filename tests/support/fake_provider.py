"""假供應商：照劇本回傳每一段的轉錄結果，讓測試只把供應商換掉、其他都走真的。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from app.exceptions import TranscriptionCancelledError
from app.provider.base import LOCAL_QUEUE, ModelCapabilities, TranscribeRequest
from app.services.transcription.models import TranscriptionTaskResult

FAKE_MODEL = "fake-model"
FAKE_TERMINABLE_MODEL = "fake-terminable"

CAPABILITIES = ModelCapabilities(
    single_pass_seconds=0,
    # GPU 佇列只有一個 worker：第二個任務一定排在佇列裡，取消測試靠這點
    queue=LOCAL_QUEUE,
    can_terminate=False,
    split_retry_on_failure=False,
    accepts_prompt=True,
    accepts_user_text=True,
    supports_batch=False,
    pricing="free",
    remove_silence=True,
)

Line = Tuple[float, float, int, str]
"""(起, 迄, 說話者編號, 文字)，時間軸是送進來的這段音檔。"""


@dataclass
class Fail:
    """劇本裡的這一段回報轉錄失敗。"""
    message: str = "假供應商：轉錄失敗"


Step = Union[Sequence[Line], Fail, Exception]


def _lrc(t: float) -> str:
    minutes = int(t // 60)
    return f"[{minutes:02d}:{t - minutes * 60:05.2f}]"


class FakeProvider:
    def __init__(self, script: Sequence[Step] = ()):
        self.script: List[Step] = list(script)
        self.calls: List[Path] = []
        self.released = 0
        # hold 設定後，轉錄會停在這裡直到 hold 被 set 或使用者取消
        self.hold: Optional[threading.Event] = None
        self.started = threading.Event()

    def capabilities(self):
        return {
            FAKE_MODEL: CAPABILITIES,
            FAKE_TERMINABLE_MODEL: replace(CAPABILITIES, can_terminate=True),
        }

    def transcribe(self, audio_path: Path, request: TranscribeRequest) -> TranscriptionTaskResult:
        self.calls.append(audio_path)
        self.started.set()
        if self.hold is not None:
            while not self.hold.wait(0.02):
                if request.cancel_requested():
                    break
            if request.cancel_requested():
                raise TranscriptionCancelledError("使用者已取消任務")

        step = self.script.pop(0) if self.script else []
        if isinstance(step, Exception):
            raise step
        if isinstance(step, Fail):
            return TranscriptionTaskResult(success=False, text=f"[[{step.message}]]")

        segments = [
            {"seg_key": f"{i:04d}", "seq": i, "start": start, "end": end,
             "speaker": f"S{speaker}", "text": text, "source": "fake"}
            for i, (start, end, speaker, text) in enumerate(step)
        ]
        lrc = "\n".join(f"{_lrc(start)}[S{speaker}] {text}"
                        for start, _, speaker, text in step)
        return TranscriptionTaskResult(success=bool(step), text=lrc, segments=segments)

    def release(self) -> None:
        self.released += 1
