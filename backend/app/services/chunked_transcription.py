"""分段轉錄模組：單檔任務的轉錄只有一個入口 :func:`transcribe`，回傳在原音檔時間軸上的轉錄結果。

呼叫端給語音視圖、供應商轉接器、轉錄設定與進度與取消物件；單次長度與能不能切段重試，讀轉接器回報的
模型能力。送什麼、切在哪裡、時間怎麼還原都在語音視圖裡，分段轉錄不必知道去靜音。內部依序：

1. 切段：語音視圖超過單次長度時切成兩段，遞迴到每一段都不超過單次長度；單次長度是 0 時不分段。
   切點依序來自語音視圖在這一段之內的靜音邊界（挑最接近中點的，離頭尾 1 秒內的不算）、Silero、
   正中間。Silero 切出的兩段往下改用 Silero 找：交界不在已知的靜音邊界上。某個切點切不出音檔時改用
   下一個來源；連正中間都切不開，就以失敗回報，不整段送出。
2. 逐段轉錄：依時間先後一段一段送進轉接器（Gemini 的說話者編號依送進來的先後編號），每一段送出之前
   都查一次取消。
3. 轉一段（:meth:`_ChunkedTranscription._transcribe_chunk`）是單一的步驟，#94 的接續之後接在它的最後：
   - 暫時錯誤（429、503 之類）：等一段時間再轉這一段，已完成的段不重送。回應建議了等待秒數就照它，
     沒有時從起始等待開始每次加倍，都不超過上限；等待前廣播，期間取消就停。重試用完，整個分段轉錄以
     失敗結束。暫時錯誤不切段重試：把段切小，對配額用完與超載都沒有幫助。
   - 其他失敗：模型能力允許切段重試、這一段又不短於下限（``TRANSCRIPTION_MAX_DURATION_SECONDS``）時，
     只把這一段用同一套切點來源切成兩段，依序轉錄，兩段各自又失敗時照同一條規則；不允許或太短，整個
     分段轉錄以失敗結束。
4. 合併：每一段的片段平移到它在語音視圖上的起點，片段 key 加上這一段的前綴。#93 的跨段說話者編號
   之後接在這裡：拿得到所有轉完的段，每一段帶著音檔、位置與段內片段。
5. 時間還原回原音檔，依開始時間排好、重編序號。

片段 key：依單次長度切出的兩段前綴是 ``a``、``b``，切段重試切出的兩段是 ``s0``、``s1``，由外往內接，
例如 ``a.b.0003``、``b.s1.0002``；沒有分段時就是轉接器給的 key。

用量是這個任務每一次呼叫供應商的總和，包括失敗後被切段重試取代的那次：供應商照樣收費。拋出例外的
那次沒有回應，不算用量。處理模式每一次都相同才照記，不然算標準。失敗時回傳失敗的轉錄結果，取消時
把到目前為止的用量附在取消上。

自己產生的暫存檔（切出的段、為了 Silero 轉成的 wav）不論完成、失敗或取消都清掉，段的音檔等合併做完
才刪；語音視圖的暫存檔與轉接器由呼叫端清理與釋放。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.config import get_settings
from app.exceptions import TranscriptionCancelledError, TransientError
from app.provider.base import ProgressAndCancel, Provider, TranscribeRequest
from app.services.silence_removal import SpeechView
from app.services.transcription.models import TranscriptionTaskResult
from app.services.vad.artifacts import persist_split
from app.services.vad.service import get_vad_service
from app.utils.audio import convert_to_wav, slice_audio
from app.utils.logger import setup_logger
from app.utils.paths import delete_temp_files

logger = setup_logger(__name__)

EDGE_SECONDS = 1.0
"""離一段的頭尾這麼近的靜音不當切點：切出來的一邊幾乎是空的。"""


def transcribe(
    view: SpeechView,
    provider: Provider,
    request: TranscribeRequest,
    progress: ProgressAndCancel,
    *,
    temp_dir: Path,
    task_id: str,
    original_filename: str,
) -> TranscriptionTaskResult:
    """轉錄語音視圖：回傳在原音檔時間軸上的轉錄結果，片段依開始時間排好、序號連續，用量是每一次
    呼叫供應商的總和。失敗時回傳失敗的轉錄結果，``text`` 是給使用者看的原因。

    切出的段放在 ``temp_dir``；``task_id`` 與 ``original_filename`` 只用來替 vad_artifacts/ 底下的
    資料夾命名（見 :func:`persist_split`）。

    Raises:
        TranscriptionCancelledError: 使用者取消；到目前為止的用量附在 ``billed_usage``。
    """
    return _ChunkedTranscription(
        view, provider, request, progress,
        temp_dir=temp_dir, task_id=task_id, original_filename=original_filename,
    ).run()


@dataclass(frozen=True)
class _Chunk:
    """段：分段轉錄切出、一次送進供應商的一段音檔；沒有分段時就是整個語音視圖。"""

    audio: Path
    duration: float
    silences: Optional[Tuple[float, ...]]
    """這一段之內已知的靜音位置（秒，以這一段的開頭為 0），切點優先選在這裡；None 代表要改用 Silero
    找（Silero 切出的段：交界不在已知的靜音上）。"""
    key_prefix: str = ""
    """片段 key 的前綴，例如 ``a.b``；沒有分段時是空的。"""
    offsets: Tuple[float, ...] = ()
    """從語音視圖一路切到這一段，每一層相對上一層的起點，外層在前。"""

    @property
    def start(self) -> float:
        """在語音視圖上的起點。"""
        return self.to_view(0.0)

    def to_view(self, seconds: float) -> float:
        """這一段裡的時間 → 語音視圖上的時間。

        由內往外一層一層平移：和以前一層一層合併兩段時的浮點運算順序相同，時間和以前逐位元相同。
        """
        for offset in reversed(self.offsets):
            seconds = seconds + offset
        return seconds

    def part(self, name: str, audio: Path, offset: float, duration: float,
             silences: Optional[Tuple[float, ...]]) -> _Chunk:
        """從這一段切出的一段：``offset`` 是它在這一段裡的起點。"""
        return _Chunk(
            audio=audio, duration=duration, silences=silences,
            key_prefix=f"{self.key_prefix}.{name}" if self.key_prefix else name,
            offsets=self.offsets + (offset,),
        )


@dataclass(frozen=True)
class _Halves:
    """一段切成的兩段。"""

    first: _Chunk
    second: _Chunk
    at_silence: bool
    """切在靜音處（已知的靜音邊界或 Silero 給的切點）；False 是找不到靜音，切在正中間。Silero 在有語音
    卻沒有夠長的靜音時，自己也會給正中間。"""


@dataclass(frozen=True)
class _TranscribedChunk:
    """轉完的段：段本身（音檔、片段 key 前綴、在語音視圖上的位置）與轉接器回傳的轉錄結果，片段的
    時間軸是這一段的音檔。"""

    chunk: _Chunk
    result: TranscriptionTaskResult


class _Failed(Exception):
    """分段轉錄以失敗結束；``text`` 是給使用者看的原因。"""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


class _ChunkedTranscription:
    """一個任務的分段轉錄：轉完的段、到目前為止的用量與自己產生的暫存檔都記在這裡。"""

    def __init__(
        self,
        view: SpeechView,
        provider: Provider,
        request: TranscribeRequest,
        progress: ProgressAndCancel,
        *,
        temp_dir: Path,
        task_id: str,
        original_filename: str,
    ):
        capabilities = provider.capabilities()[request.model]
        self._view = view
        self._provider = provider
        self._request = request
        self._progress = progress
        self._temp_dir = temp_dir
        self._task_id = task_id
        self._original_filename = original_filename
        self._single_pass = capabilities.single_pass_seconds
        self._split_retry = capabilities.split_retry_on_failure
        self._transcribed: List[_TranscribedChunk] = []
        """轉完的段，依時間先後。"""
        self._usage: Optional[TranscriptionTaskResult] = None
        """到目前為止每一次呼叫供應商的用量（見 :func:`_add_usage`）；還沒有任何回應時是 None。"""
        self._temp_files: List[Path] = []

    def run(self) -> TranscriptionTaskResult:
        whole = _Chunk(self._view.audio, self._view.duration, self._view.silence_boundaries)
        try:
            self._transcribe_in_order(whole)
            return self._merged()
        except _Failed as failure:
            return self._result(success=False, text=failure.text)
        except TranscriptionCancelledError as cancelled:
            # 取消前已經轉完的段，供應商照樣收費：用量交給任務生命週期記在已取消的紀錄上
            cancelled.billed_usage = self._usage
            raise
        finally:
            # 段的音檔在合併之後才刪
            delete_temp_files(self._temp_files)

    # ── 切段與逐段轉錄 ────────────────────────────────────────────
    def _transcribe_in_order(self, chunk: _Chunk) -> None:
        """依時間先後轉錄這一段：超過單次長度時切成兩段，前一段轉完才轉後一段。"""
        if self._single_pass <= 0 or chunk.duration <= self._single_pass:
            self._transcribe_chunk(chunk)
            return
        self._progress.raise_if_cancelled()
        halves = self._split(chunk, "a", "b")
        if halves is None:
            raise _Failed("[[音檔較長，卻切不開，無法分段轉錄]]")
        where = "於靜音處" if halves.at_silence else "找不到靜音，於正中間"
        self._progress.report(f"音檔較長（{chunk.duration / 60:.1f} 分鐘），{where}分段轉錄...")
        self._transcribe_in_order(halves.first)
        self._transcribe_in_order(halves.second)

    def _transcribe_chunk(self, chunk: _Chunk) -> None:
        """轉一段：送進轉接器（暫時錯誤在 :meth:`_attempt` 裡重試）；失敗時模型能力允許、這一段又夠長，
        只把這一段切成兩段重試。"""
        result = self._attempt(chunk)
        if result.success:
            self._transcribed.append(_TranscribedChunk(chunk, result))
            return
        if not self._may_split_retry(chunk):
            raise _Failed(self._failure(chunk, result.text))
        self._progress.raise_if_cancelled()
        halves = self._split(chunk, "s0", "s1")
        if halves is None:
            raise _Failed(self._failure(chunk, result.text))
        logger.info(f"轉錄失敗，把 {chunk.duration:.1f} 秒的段切成兩段重試")
        self._transcribe_chunk(halves.first)
        self._transcribe_chunk(halves.second)

    def _failure(self, chunk: _Chunk, reason: str) -> str:
        """給使用者看的失敗原因：分段轉錄時寫明是第幾段、在原音檔的哪裡。"""
        reason = reason.strip().removeprefix("[[").removesuffix("]]")
        if not chunk.key_prefix:
            return f"[[{reason}]]"
        return f"[[{self._which(chunk)}：{reason}]]"

    def _which(self, chunk: _Chunk) -> str:
        """「分段轉錄的第幾段（在原音檔的起訖）」：依時間先後，前面的段都已經轉完。"""
        timeline = self._view.timeline
        start = timeline.to_original(chunk.start)
        end = timeline.to_original(chunk.start + chunk.duration, end=True)
        return f"分段轉錄的第 {len(self._transcribed) + 1} 段（{_clock(start)}–{_clock(end)}）"

    def _may_split_retry(self, chunk: _Chunk) -> bool:
        if not self._split_retry:
            # 各段說話者編號互相獨立的模型（例如本機）：拼起來的說話者編號會錯亂，直接回報失敗
            return False
        minimum = get_settings().transcription_max_duration_seconds
        if chunk.duration < minimum:
            logger.info(f"失敗的段只有 {chunk.duration:.1f} 秒，短於 {minimum} 秒，不切段重試")
            return False
        return True

    def _attempt(self, chunk: _Chunk) -> TranscriptionTaskResult:
        """把這一段送進轉接器：暫時錯誤等一段時間再送一次，已經轉完的段不重送。

        暫時錯誤不切段重試：把段切小，對配額用完與超載都沒有幫助。重試用完，整個分段轉錄以失敗結束。
        """
        retries = 0
        while True:
            try:
                return self._call(chunk)
            except TransientError as error:
                if retries >= get_settings().transient_error_retries:
                    raise _Failed(self._failure(
                        chunk, f"暫時錯誤重試 {retries} 次仍失敗（{error}）")) from error
                retries += 1
                self._wait_before_retrying(chunk, error, retries)

    def _wait_before_retrying(self, chunk: _Chunk, error: TransientError, retry: int) -> None:
        """第 ``retry`` 次重試之前：先廣播要等多久、為什麼，再等；期間取消就停。

        供應商建議了等待秒數時照它，沒有時從起始等待開始每次加倍；都不超過上限。
        """
        settings = get_settings()
        suggested = error.retry_after
        if suggested is None:
            suggested = settings.transient_error_initial_wait_seconds * 2 ** (retry - 1)
        seconds = max(0.0, min(suggested, settings.transient_error_max_wait_seconds))
        # 使用者已經取消（例如 503 剛好在取消之後回來）：不再宣告要重試
        self._progress.raise_if_cancelled()
        which = self._which(chunk) if chunk.key_prefix else ""
        notice = (f"{which}遇到暫時錯誤（{error}），{seconds:g} 秒後第 {retry} 次重試"
                  f"（最多 {settings.transient_error_retries} 次）...")
        logger.warning(notice)
        self._progress.report(notice)
        self._progress.wait(seconds)

    def _call(self, chunk: _Chunk) -> TranscriptionTaskResult:
        """把這一段送進轉接器一次；一般例外轉成失敗結果，交給上層決定要不要切段重試。

        每次呼叫供應商之前都查一次取消：供應商不理會取消、照樣轉完手上這一段時，下一段也不會再送出去。
        """
        self._progress.raise_if_cancelled()
        try:
            result = self._provider.transcribe(chunk.audio, self._request, self._progress)
        except (TranscriptionCancelledError, TransientError):
            # 取消與暫時錯誤都不是這一段失敗：往上拋給任務生命週期
            raise
        except Exception as e:
            logger.error(f"轉錄過程發生錯誤: {e}")
            return TranscriptionTaskResult(success=False, text=f"[[轉錄錯誤: {e}]]")
        self._usage = _add_usage(self._usage, result)
        return result

    # ── 切點 ─────────────────────────────────────────────────────
    def _split(self, chunk: _Chunk, first: str, second: str) -> Optional[_Halves]:
        """把這一段切成兩段，前綴是 ``first``、``second``。

        切點依序來自已知的靜音、Silero、正中間；某個切點切不出音檔時改用下一個，連正中間都切不開時
        回 None。
        """
        point = _nearest_to_middle(chunk.silences or (), chunk.duration)
        if point is not None:
            halves = self._slice(chunk, first, second, point, at_silence=True)
            if halves is not None:
                return halves
        halves = self._split_with_silero(chunk, first, second)
        if halves is not None:
            return halves
        logger.warning(f"{chunk.audio.name} 找不到靜音當切點，切在正中間")
        return self._slice(chunk, first, second, chunk.duration / 2, at_silence=False)

    def _slice(self, chunk: _Chunk, first: str, second: str, point: float, *,
               at_silence: bool) -> Optional[_Halves]:
        """用 ffmpeg 在 ``point`` 秒把這一段切成兩個 wav；已知的靜音跟著分到兩段。"""
        audios = (self._temp_dir / f"{chunk.audio.stem}.half1.wav",
                  self._temp_dir / f"{chunk.audio.stem}.half2.wav")
        self._temp_files.extend(audios)
        if not (slice_audio(chunk.audio, audios[0], end=point)
                and slice_audio(chunk.audio, audios[1], start=point)):
            return None
        left = right = None
        if chunk.silences is not None:
            left = tuple(b for b in chunk.silences if 0 < b < point)
            right = tuple(b - point for b in chunk.silences if point < b < chunk.duration)
        logger.info(f"分段轉錄: {chunk.audio.name} ({chunk.duration:.0f}s) 於 {point:.2f}s 切開")
        return _Halves(chunk.part(first, audios[0], 0.0, point, left),
                       chunk.part(second, audios[1], point, chunk.duration - point, right),
                       at_silence)

    def _split_with_silero(self, chunk: _Chunk, first: str, second: str) -> Optional[_Halves]:
        """用 Silero 在這一段的音檔上找切點；Silero 無法使用（沒安裝、載入失敗、出錯、找不到語音）時
        回 None。開了保留去靜音產物時，切出的兩段存進去靜音產物。"""
        # Silero（soundfile/libsndfile）讀不了 m4a 之類的壓縮格式，先轉成 wav
        wav = convert_to_wav(chunk.audio, self._temp_dir)
        if wav is None:
            logger.warning(f"無法把 {chunk.audio.name} 轉成 wav 給 Silero 找切點")
            return None
        if wav != chunk.audio:
            self._temp_files.append(wav)
        try:
            part1, part2, point = get_vad_service().split_audio_on_silence(
                audio_path=str(wav), output_dir=str(self._temp_dir))
        except Exception as e:
            logger.warning(f"Silero 找切點失敗: {e}")
            return None
        if not (part1 and part2 and point is not None):
            return None
        audios = (Path(part1), Path(part2))
        self._temp_files.extend(audios)
        persist_split(task_id=self._task_id, original_filename=self._original_filename,
                      part1_path=audios[0], part2_path=audios[1], split_point=point)
        logger.info(f"分段轉錄: {chunk.audio.name} ({chunk.duration:.0f}s) 由 Silero 於 {point:.2f}s 切開")
        return _Halves(chunk.part(first, audios[0], 0.0, point, None),
                       chunk.part(second, audios[1], point, chunk.duration - point, None),
                       at_silence=True)

    # ── 合併與結果 ───────────────────────────────────────────────
    def _merged(self) -> TranscriptionTaskResult:
        """合併轉完的段、時間還原回原音檔，回傳成功的轉錄結果。"""
        segments = _merge(self._transcribed)
        if self._view.removed_silence:
            self._progress.report("校正時間軸...")
            segments = self._view.restore(segments)
            logger.info("時間已還原回原音檔的時間軸")
        return self._result(success=True, text=_why_no_segments(segments, self._transcribed),
                            segments=_in_time_order(segments))

    def _result(self, *, success: bool, text: str,
                segments: Sequence[Dict[str, Any]] = ()) -> TranscriptionTaskResult:
        """帶著到目前為止的用量的轉錄結果。"""
        usage = self._usage or TranscriptionTaskResult(success=False)
        return TranscriptionTaskResult(
            success=success,
            text=text,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            service_tier_used=usage.service_tier_used,
            segments=list(segments),
        )


def _clock(seconds: float) -> str:
    """原音檔上的時間寫成 MM:SS，一小時以上寫成 H:MM:SS；秒以下捨去。"""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _nearest_to_middle(silences: Sequence[float], duration: float) -> Optional[float]:
    """已知的靜音裡最接近中點的；離頭尾 :data:`EDGE_SECONDS` 內的不算，都不算時是 None。"""
    candidates = [b for b in silences if EDGE_SECONDS < b < duration - EDGE_SECONDS]
    if not candidates:
        return None
    return min(candidates, key=lambda b: abs(b - duration / 2))


def _merge(transcribed: Sequence[_TranscribedChunk]) -> List[Dict[str, Any]]:
    """合併：每一段的片段平移到它在語音視圖上的起點，片段 key 加上這一段的前綴。

    拿到的是所有轉完的段，依時間先後。
    """
    return [_placed(segment, piece.chunk)
            for piece in transcribed for segment in piece.result.segments]


def _placed(segment: Mapping[str, Any], chunk: _Chunk) -> Dict[str, Any]:
    """一段裡的片段（連同逐字時間）平移到語音視圖的時間軸，回傳新的片段。"""
    placed = _shifted(segment, chunk)
    if segment.get("words"):
        placed["words"] = [_shifted(word, chunk) for word in segment["words"]]
    if chunk.key_prefix:
        placed["seg_key"] = f"{chunk.key_prefix}.{segment.get('seg_key', '')}"
    return placed


def _shifted(span: Mapping[str, Any], chunk: _Chunk) -> Dict[str, Any]:
    """一段時間（片段或詞）的開始與結束平移到語音視圖的時間軸；沒有時間的維持沒有。"""
    shifted = dict(span)
    for key in ("start", "end"):
        if shifted.get(key) is not None:
            shifted[key] = chunk.to_view(shifted[key])
    return shifted


def _in_time_order(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """依開始時間排好、重編序號：各段合併之後序號才會連續。"""
    ordered = sorted(segments, key=lambda s: s.get("start", 0.0))
    for i, segment in enumerate(ordered):
        segment["seq"] = i
    return ordered


def _why_no_segments(segments: Sequence[Mapping[str, Any]],
                     transcribed: Sequence[_TranscribedChunk]) -> str:
    """合併之後的 text：有片段時是空的；一段都沒有時，取第一個寫了原因的段的說明，整個任務都沒有
    片段時由任務生命週期拿它回報失敗。"""
    if segments:
        return ""
    return next((piece.result.text for piece in transcribed if piece.result.text), "")


def _add_usage(
    usage: Optional[TranscriptionTaskResult], part: TranscriptionTaskResult
) -> TranscriptionTaskResult:
    """到目前為止的用量加上這一次的，回傳只帶 token 數與處理模式的轉錄結果（不是可以採用的結果，
    所以 success 是 False）；處理模式每一次都一樣才照記，不然算標準。"""
    if usage is None:
        usage = TranscriptionTaskResult(success=False, service_tier_used=part.service_tier_used)
    return TranscriptionTaskResult(
        success=False,
        input_tokens=usage.input_tokens + part.input_tokens,
        output_tokens=usage.output_tokens + part.output_tokens,
        total_tokens=usage.total_tokens + part.total_tokens,
        service_tier_used=(usage.service_tier_used
                           if usage.service_tier_used == part.service_tier_used else "standard"),
    )
