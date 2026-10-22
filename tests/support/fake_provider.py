"""假供應商：照劇本回傳每一段的轉錄結果，讓測試只把供應商換掉、其他都走真的。

它同時是自己的 ProviderFactory：``registry.register("fake", fake)`` 之後，
每個任務建立轉接器時拿到的都是同一個實例，測試可以事後檢查它被怎麼用。

模型能力設成支援批次（``supports_batch``）時也能跑批次：送出時照劇本給每個請求一份結果，
查到成功結束時附上，和 Gemini 一樣。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.provider.base import (
    LOCAL_QUEUE,
    BatchStatus,
    ModelCapabilities,
    ProgressAndCancel,
    ProviderInfo,
    TranscribeRequest,
)
from app.services.transcription.models import TranscriptionTaskResult
from app.utils.audio import get_audio_duration

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

Line = Union[Tuple[float, Optional[float], int, str],
             Tuple[float, Optional[float], int, str, Sequence[Word]]]
"""(起, 迄, 說話者編號, 文字[, 逐字時間])，時間軸是送進來的這段音檔；迄是 None 時片段沒有結束時間。"""


@dataclass
class Fail:
    """劇本裡的這一段回報轉錄失敗。"""
    message: str = "假供應商：轉錄失敗"


@dataclass
class ServedAs:
    """劇本裡的這一段照樣轉錄成功，實際用到的處理模式卻不同（例如 Flex 退回標準）。"""
    service_tier: str
    lines: Sequence[Line]


Step = Union[Sequence[Line], Fail, ServedAs, Exception]
"""劇本的一步：這一段的轉錄結果、回報失敗、用了別的處理模式，或拋出這個例外。批次的請求只能是
轉錄結果或回報失敗。"""

class Restart(BaseException):
    """查詢批次時應用程式重啟（例如關掉免安裝版再打開）：批次的這次執行停在這裡。

    不是 Exception，批次接不住它：和行程被關掉一樣，檔案不記成失敗，批次停在輪詢中，
    之後從復原入口接著結束。
    """


BatchPoll = Union[str, BaseException]
"""查一次批次的結果：Gemini 的狀態名稱去掉 ``JOB_STATE_``（例如 ``"RUNNING"``），或拋出這個例外
（例如 :class:`Restart`）。"""

BATCH_DONE = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"})


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
        # 模型清單拿掉了這個模型（例如升級之後）：查模型能力時列不出它，建立轉接器照樣可以
        self.withdrawn = False
        self.opened = 0
        # 建立轉接器時拋的錯，例如金鑰無效時的 ValueError
        self.open_error: Optional[Exception] = None
        self.calls: List[Path] = []
        # 每一段轉錄收到的音檔有多長（秒）：看得出送進來的是只剩語音的音檔還是原音檔，以及切在哪裡
        self.durations: List[Optional[float]] = []
        self.released = 0
        # 看到使用者取消而停下的次數
        self.cancelled = 0
        # 每一段轉錄經進度與取消物件回報的進度文字
        self.reports: List[str] = []
        # 每一段轉錄回報的用量（輸入、輸出 token）與實際用到的處理模式；失敗的回應照樣帶用量，
        # 和 Gemini 的回應被阻擋時一樣照樣收費
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
        # 依序收到的提示詞：每一段轉錄一則，送出的批次每個請求一則
        self.prompts: List[str] = []
        # 批次：上傳時依序拋的錯（None 代表那一個照常上傳）、送出時依序拋的錯，以及每次查詢依序
        # 的結果；查詢用完之後一律回報 batch_outcome，"SUCCEEDED" 時附上送出時照劇本轉錄的結果
        self.upload_errors: List[Optional[Exception]] = []
        self.submit_errors: List[Exception] = []
        self.batch_polls: List[BatchPoll] = []
        self.batch_outcome = "SUCCEEDED"
        # 查了幾次批次；poll_hold 設定後，查詢停在這裡直到放行，開始等的時候 polling 會 set
        self.polls = 0
        self.poll_hold: Optional[threading.Event] = None
        self.polling = threading.Event()
        # 成功結束時，最後這麼多個請求沒有結果（供應商少給了）
        self.missing_results = 0
        self.submitted: Dict[str, Tuple[TranscriptionTaskResult, ...]] = {}
        """送出的批次：名稱 → 每個請求的結果。"""

    # ── ProviderFactory ──────────────────────────────────────────
    def capabilities(self):
        return {} if self.withdrawn else {FAKE_MODEL: self.model_capabilities}

    def __call__(self, model: str, api_key: str) -> "FakeProvider":
        self.opened += 1
        if self.open_error is not None:
            raise self.open_error
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
        self.durations.append(get_audio_duration(audio_path))
        self.prompts.append(request.prompt)
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
        service_tier = self.service_tier
        if isinstance(step, ServedAs):
            service_tier, step = step.service_tier, step.lines
        return self._result(step, service_tier)

    def release(self) -> None:
        self.released += 1

    # ── BatchProvider ────────────────────────────────────────────
    def upload(self, audio_path: Path) -> Any:
        """批次的上傳：和轉錄一樣記下收到的音檔與它的長度；hold 設定後停在這裡直到放行。"""
        self.calls.append(audio_path)
        self.durations.append(get_audio_duration(audio_path))
        self.started.set()
        if self.hold is not None:
            self.hold.wait(30)
        error = self.upload_errors.pop(0) if self.upload_errors else None
        if error is not None:
            raise error
        return audio_path

    def submit_batch(self, requests: Sequence[Tuple[Any, str]], display_name: str) -> str:
        """照劇本給每個請求一份結果，一個請求一步、依送出的順序；處理模式是批次。"""
        self.prompts.extend(prompt for _, prompt in requests)
        if self.submit_errors:
            raise self.submit_errors.pop(0)
        name = f"fake-batches/{len(self.submitted) + 1}"
        steps = [self.script.pop(0) if self.script else [] for _ in requests]
        assert all(isinstance(step, (Fail, list, tuple)) for step in steps), (
            "批次的請求只能照劇本轉錄成功或回報失敗")
        self.submitted[name] = tuple(self._result(step, "batch") for step in steps)
        return name

    def poll_batch(self, name: str) -> BatchStatus:
        self.polls += 1
        self.polling.set()
        if self.poll_hold is not None:
            self.poll_hold.wait(30)
        step = self.batch_polls.pop(0) if self.batch_polls else self.batch_outcome
        if isinstance(step, BaseException):
            raise step
        if step == "SUCCEEDED":
            results = self.submitted[name]
            return BatchStatus(state=f"JOB_STATE_{step}", done=True, succeeded=True,
                               results=results[:len(results) - self.missing_results])
        return BatchStatus(state=f"JOB_STATE_{step}", done=step in BATCH_DONE)

    def _result(self, step: Union[Sequence[Line], Fail],
                service_tier: Optional[str]) -> TranscriptionTaskResult:
        """劇本的一步換成轉錄結果，帶著用量與處理模式。"""
        input_tokens, output_tokens = self.usage
        usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                 "total_tokens": input_tokens + output_tokens, "service_tier_used": service_tier}
        if isinstance(step, Fail):
            return TranscriptionTaskResult(success=False, text=f"[[{step.message}]]", **usage)
        # 和真的轉接器一樣，轉錄結果只有片段與用量，不附著 LRC 文字
        segments = [_segment(i, line) for i, line in enumerate(step)]
        return TranscriptionTaskResult(success=bool(step), segments=segments, **usage)
