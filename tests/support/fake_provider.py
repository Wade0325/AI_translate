"""假供應商：照劇本回傳每一段的轉錄結果，讓測試只把供應商換掉、其他都走真的。

它同時是自己的 ProviderFactory：``registry.register("fake", fake)`` 之後，
每個任務建立轉接器時拿到的都是同一個實例，測試可以事後檢查它被怎麼用。

模型能力設成支援批次（``supports_batch``）時也能跑批次：送出時照劇本給每個請求一份結果，
查到成功結束時附上，和 Gemini 一樣。

劇本的一步也可以是「照收到的音檔回答」（:class:`Listen`）：不必事先知道每一段切在哪裡，用來模擬本機的
MOSS 在長度上限提早停下、接續時從中途再轉一次（#94）。

劇本裡空的一步（``[]``）回報失敗；要像本機的模型那樣「跑完了、沒有片段」算成功，用 :class:`Empty`。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import soundfile as sf

from app.core.error_codes import ErrorCode
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
    continuation=False,
    accepts_prompt=True,
    accepts_user_text=True,
    supports_batch=False,
    supports_flex=False,
    pricing="free",
    remove_silence=True,
)

Word = Tuple[str, float, float]
"""(詞, 起, 迄)：對齊器的一個詞，時間軸和所屬的那一行相同。"""

Line = Union[Tuple[float, Optional[float], Optional[int], str],
             Tuple[float, Optional[float], Optional[int], str, Sequence[Word]]]
"""(起, 迄, 說話者編號, 文字[, 逐字時間])，時間軸是送進來的這段音檔；迄是 None 時片段沒有結束時間，
說話者編號是 None 時片段沒有說話者編號（例如 Gemini 沒寫說話者代號的行）。"""


@dataclass
class Fail:
    """劇本裡的這一段回報轉錄失敗。"""
    message: str = "假供應商：轉錄失敗"


@dataclass
class ServedAs:
    """劇本裡的這一段照樣轉錄成功，實際用到的處理模式卻不同（例如 Flex 退回標準）。"""
    service_tier: str
    lines: Sequence[Line]


@dataclass
class Listen:
    """劇本裡的這一段照收到的音檔回答，像本機的 MOSS（#94）：音檔裡每個有聲段（合成音檔的正弦波，見
    tests/support/synthetic_audio.py）一個片段，起訖是它在這段音檔裡的位置；說話者編號照聲音的頻率在
    這段音檔裡出場的先後，從 S0 編起，文字寫出頻率（取到 100 Hz，例如「400Hz」）。

    ``stops_after`` 設定時模擬提早停止：只輸出結束在這段音檔的這麼多秒以內的有聲段，像 MOSS 輸出到約
    16k token 就停。``reports`` 是停下時要不要回報擔保轉錄到哪一秒（``covered_until``，最後一個輸出的
    片段的結束），像 MOSS 用完生成預算、輸出被截斷時那樣；False 模擬模型自己不知道停早了，像 MOSS 在
    約 16k token 自己停下（輸出完整），或長段非語音之後就結束。
    """
    stops_after: Optional[float] = None
    reports: bool = True


@dataclass
class Empty:
    """劇本裡的這一段跑完了，卻沒有轉錄出任何內容，像本機的模型遇到整段只有靜音或測試音（空段，#327）：
    算成功、沒有片段，``text`` 寫為什麼沒有。``covered_until`` 是擔保轉錄到這段音檔的哪一秒，例如 MOSS
    輸出一長串只有說話者標籤的段、丟掉之後（#325）；None 是沒有回報。"""
    text: str = "假供應商：沒有轉錄出任何內容"
    covered_until: Optional[float] = None


Step = Union[Sequence[Line], Fail, ServedAs, Listen, Empty, Exception]
"""劇本的一步：這一段的轉錄結果、回報失敗、用了別的處理模式、照收到的音檔回答、跑完了卻沒有內容，或拋出
這個例外。批次的請求只能是轉錄結果或回報失敗。"""

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
               "speaker": None if speaker is None else f"S{speaker}", "text": text,
               "source": "fake"}
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
        # 設定後，每一段轉錄（與批次的上傳）收到的檔案當場交給它檢查，結果依序記在 examined；任務結束後
        # 暫存檔就清掉了，事後看不到。例如看送進來的檔案有哪些串流（#258）
        self.examine: Optional[Callable[[Path], Any]] = None
        self.examined: List[Any] = []
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
        # 批次：上傳時依序拋的錯（None 代表那一個照常上傳，Restart 代表上傳時重啟）、送出時依序拋的
        # 錯，以及每次查詢依序的結果；查詢用完之後一律回報 batch_outcome，"SUCCEEDED" 時附上送出時
        # 照劇本轉錄的結果
        self.upload_errors: List[Optional[BaseException]] = []
        self.submit_errors: List[Exception] = []
        self.batch_polls: List[BatchPoll] = []
        self.batch_outcome = "SUCCEEDED"
        # 查了幾次批次。poll_holds[i] 擋下第 i 次查詢（從 0 數），直到它被 set；沒列到的查詢不擋。
        # 查詢一開始 polling 就會 set
        self.polls = 0
        self.poll_holds: List[threading.Event] = []
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
        self._received(audio_path)
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
        if isinstance(step, Listen):
            return self._listened(audio_path, step)
        if isinstance(step, Empty):
            return self._result([], self.service_tier).model_copy(update={
                "success": True, "text": step.text, "error_code": ErrorCode.NO_TRANSCRIPT,
                "covered_until": step.covered_until})
        service_tier = self.service_tier
        if isinstance(step, ServedAs):
            service_tier, step = step.service_tier, step.lines
        return self._result(step, service_tier)

    def release(self) -> None:
        self.released += 1

    # ── BatchProvider ────────────────────────────────────────────
    def upload(self, audio_path: Path) -> Any:
        """批次的上傳：和轉錄一樣記下收到的音檔與它的長度；hold 設定後停在這裡直到放行。"""
        self._received(audio_path)
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
        poll = self.polls
        self.polls += 1
        self.polling.set()
        if poll < len(self.poll_holds):
            self.poll_holds[poll].wait(30)
        step = self.batch_polls.pop(0) if self.batch_polls else self.batch_outcome
        if isinstance(step, BaseException):
            raise step
        if step == "SUCCEEDED":
            results = self.submitted[name]
            return BatchStatus(state=f"JOB_STATE_{step}", done=True, succeeded=True,
                               results=results[:len(results) - self.missing_results])
        return BatchStatus(state=f"JOB_STATE_{step}", done=step in BATCH_DONE)

    def _received(self, audio_path: Path) -> None:
        """記下收到的音檔、它的長度，以及設定了 examine 時的檢查結果。"""
        self.calls.append(audio_path)
        self.durations.append(get_audio_duration(audio_path))
        if self.examine is not None:
            self.examined.append(self.examine(audio_path))

    def _listened(self, audio_path: Path, listen: Listen) -> TranscriptionTaskResult:
        """照收到的音檔回答（見 :class:`Listen`）。"""
        heard = _heard(audio_path)
        said = [span for span in heard
                if listen.stops_after is None or span[1] <= listen.stops_after]
        speakers: Dict[int, int] = {}
        lines: List[Line] = [(start, end, speakers.setdefault(tone, len(speakers)), f"{tone}Hz")
                             for start, end, tone in said]
        result = self._result(lines, self.service_tier)
        if len(said) < len(heard) and listen.reports:
            covered = max((end for _, end, _ in said), default=0.0)
            result = result.model_copy(update={"covered_until": covered})
        return result

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


HEARING_FRAME_SECONDS = 0.01


def _heard(audio_path: Path) -> List[Tuple[float, float, int]]:
    """音檔裡的有聲段（起, 迄, 頻率），依時間先後：音量（每 10 毫秒的 RMS）超過 0.01 的連續一段算一個，
    頻率從過零的次數估計，取到 100 Hz。"""
    samples, rate = sf.read(str(audio_path), dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    frame = int(rate * HEARING_FRAME_SECONDS)
    count = len(samples) // frame
    loud = np.sqrt((samples[:count * frame].reshape(count, frame) ** 2).mean(axis=1)) > 0.01
    spans: List[Tuple[float, float, int]] = []
    i = 0
    while i < count:
        if not loud[i]:
            i += 1
            continue
        j = i
        while j < count and loud[j]:
            j += 1
        piece = samples[i * frame:j * frame]
        crossings = int(np.count_nonzero(np.signbit(piece[1:]) != np.signbit(piece[:-1])))
        frequency = crossings / 2 / ((j - i) * HEARING_FRAME_SECONDS)
        spans.append((round(i * HEARING_FRAME_SECONDS, 2), round(j * HEARING_FRAME_SECONDS, 2),
                      int(round(frequency / 100)) * 100))
        i = j
    return spans
