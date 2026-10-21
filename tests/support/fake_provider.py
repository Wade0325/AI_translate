"""假供應商：照劇本回傳每一段的轉錄結果，讓測試只把供應商換掉、其他都走真的。

它同時是自己的 ProviderFactory：``registry.register("fake", fake)`` 之後，
每個任務建立轉接器時拿到的都是同一個實例，測試可以事後檢查它被怎麼用。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from app.provider.base import (
    LOCAL_QUEUE,
    ModelCapabilities,
    ProgressAndCancel,
    ProviderInfo,
    TranscribeRequest,
)
from app.services.transcription.models import TranscriptionTaskResult

FAKE_MODEL = "fake-model"

CAPABILITIES = ModelCapabilities(
    single_pass_seconds=600,
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

Word = Tuple[str, float, float]
"""(詞, 起, 迄)：對齊器的一個詞，時間軸和所屬的那一行相同。"""

Line = Union[Tuple[float, float, int, str], Tuple[float, float, int, str, Sequence[Word]]]
"""(起, 迄, 說話者編號, 文字[, 逐字時間])，時間軸是送進來的這段音檔。"""


@dataclass
class Fail:
    """劇本裡的這一段回報轉錄失敗。"""
    message: str = "假供應商：轉錄失敗"


Step = Union[Sequence[Line], Fail, Exception]
"""劇本的一步：這一段的轉錄結果、回報失敗，或拋出這個例外。"""


def _segment(i: int, line: Line) -> dict:
    start, end, speaker, text, *timings = line
    segment = {"seg_key": f"{i:04d}", "seq": i, "start": start, "end": end,
               "speaker": f"S{speaker}", "text": text, "source": "fake"}
    if timings:
        segment["words"] = [{"text": word, "start": word_start, "end": word_end}
                            for word, word_start, word_end in timings[0]]
    return segment


class FakeProvider:
    info = ProviderInfo(label="假供應商", requires_api_key=False)

    def __init__(self, script: Sequence[Step] = ()):
        self.script: List[Step] = list(script)
        self.model_capabilities = CAPABILITIES
        self.opened = 0
        self.calls: List[Path] = []
        self.released = 0
        # 看到使用者取消而停下的次數
        self.cancelled = 0
        # 每一段轉錄經進度與取消物件回報的進度文字
        self.reports: List[str] = []
        # 每一段轉錄成功時回報的用量（輸入、輸出 token）與實際用到的處理模式
        self.usage: Tuple[int, int] = (0, 0)
        self.service_tier: Optional[str] = None
        # hold 設定後，轉錄會停在這裡直到 hold 被 set 或使用者取消
        self.hold: Optional[threading.Event] = None
        self.started = threading.Event()
        # 不理會取消：照樣等到 hold 放行、回傳結果
        self.ignores_cancel = False
        # 看到取消時改丟這個例外：模擬 503 剛好在取消之後回來，或執行模式強制終止執行中的
        # 任務（Docker 模式的 gevent worker 在任務裡丟 GreenletExit）
        self.raises_when_cancelled: Optional[BaseException] = None
        # 設定頁的「測試」（check_ready）：就緒時回傳 ready_message；not_ready 設定後改拋它。
        # checked_keys 是每次檢查收到的 API 金鑰
        self.ready_message = "假供應商可以轉錄"
        self.not_ready: Optional[ValueError] = None
        self.checked_keys: List[str] = []

    # ── ProviderFactory ──────────────────────────────────────────
    def capabilities(self):
        return {FAKE_MODEL: self.model_capabilities}

    def __call__(self, model: str, api_key: str) -> "FakeProvider":
        self.opened += 1
        return self

    def check_ready(self, model: str, api_key: str) -> str:
        self.checked_keys.append(api_key)
        if self.not_ready is not None:
            raise self.not_ready
        return self.ready_message

    # ── Provider ─────────────────────────────────────────────────
    def transcribe(
        self, audio_path: Path, request: TranscribeRequest, progress: ProgressAndCancel,
    ) -> TranscriptionTaskResult:
        self.calls.append(audio_path)
        self.started.set()
        for text in self.reports:
            progress.report(text)
        if self.hold is not None:
            while not self.hold.wait(0.02):
                if not self.ignores_cancel and progress.cancel_requested():
                    break
        # 取消只能從進度與取消物件得知
        if not self.ignores_cancel and progress.cancel_requested():
            self.cancelled += 1
            if self.raises_when_cancelled is not None:
                raise self.raises_when_cancelled
            progress.raise_if_cancelled()

        step = self.script.pop(0) if self.script else []
        if isinstance(step, Exception):
            raise step
        if isinstance(step, Fail):
            return TranscriptionTaskResult(success=False, text=f"[[{step.message}]]")

        # 和真的轉接器一樣，轉錄結果只有片段與用量，不附著 LRC 文字
        segments = [_segment(i, line) for i, line in enumerate(step)]
        input_tokens, output_tokens = self.usage
        return TranscriptionTaskResult(
            success=bool(step), segments=segments,
            input_tokens=input_tokens, output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens, service_tier_used=self.service_tier)

    def release(self) -> None:
        self.released += 1
