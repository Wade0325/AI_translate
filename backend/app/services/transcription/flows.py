import re
from pathlib import Path
from typing import List, Dict, Optional

from app.core.config import get_settings
from app.exceptions import TranscriptionCancelledError, TransientError
from app.utils.logger import setup_logger
from app.utils.paths import is_temp_upload
from app.utils.audio import (
    get_audio_duration as _ffprobe_duration,
    convert_to_wav,
    slice_audio,
)
from app.provider.base import ProgressAndCancel, Provider, TranscribeRequest
from app.services.converter.service import _parse_lrc
from app.services.vad.preprocess import run_vad_extraction
from app.services.vad.artifacts import persist_speech_extraction, persist_split
from app.services.vad.service import get_vad_service

from .models import (
    TranscriptionTaskResult
)

logger = setup_logger(__name__)

_settings = get_settings()
# 語音佔比 >= 此閾值時跳過去靜音；低於則使用純語音檔轉錄
VAD_SPEECH_RATIO_SKIP_THRESHOLD = _settings.vad_speech_ratio_skip_threshold


def speech_segment_boundaries(segments: List[Dict[str, float]]) -> List[float]:
    """去靜音找出的有聲區間在「拼接後時間軸」上的交界位置。

    純語音檔是各有聲區間無縫拼接而成，交界正是去靜音前音檔的靜音處，
    也是切割純語音檔時唯一不會切在語句中間的位置。
    """
    boundaries: List[float] = []
    accumulated = 0.0
    for seg in segments[:-1]:
        accumulated += seg['end'] - seg['start']
        boundaries.append(accumulated)
    return boundaries


def pick_halving_split_point(
    boundaries: List[float], duration: float
) -> Optional[float]:
    """從候選靜音點中挑最接近中點者；排除距頭尾 1 秒內的退化切點。"""
    candidates = [b for b in boundaries if 1.0 < b < duration - 1.0]
    if not candidates:
        return None
    return min(candidates, key=lambda b: abs(b - duration / 2))


def speech_time_remapper(segments: List[Dict[str, float]]):
    """回傳「純語音檔時間 → 去靜音前時間」的轉換函式。

    LRC 與結構化片段共用同一套轉換，兩者的時間軸才不會分岔。
    """
    durations = [seg['end'] - seg['start'] for seg in segments]
    cumulative = [sum(durations[:i]) for i in range(len(durations))]

    def remap(t: float) -> Optional[float]:
        for i, cum in enumerate(cumulative):
            if t < cum + durations[i]:
                return segments[i]['start'] + (t - cum)
        # 落在總長之後（浮點誤差或模型給出超界時間）→ 夾到最後片段結尾，
        # 避免整行被丟棄
        return segments[-1]['end'] if segments else None

    return remap


def remap_lrc_timestamps(lrc_text: str, segments: List[Dict[str, float]]) -> str:
    """將 LRC 時間戳從拼接後的時間軸重對應回原始時間軸"""
    parsed_lines = _parse_lrc(lrc_text)
    if not parsed_lines:
        return ""

    remap = speech_time_remapper(segments)
    remapped_lrc_lines = []
    for line in parsed_lines:
        remapped_time = remap(line.time)
        if remapped_time is None:
            continue
        minutes = int(remapped_time // 60)
        seconds = int(remapped_time % 60)
        centiseconds = int((remapped_time - int(remapped_time)) * 100)  # 保持2位數
        remapped_lrc_lines.append(
            f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]{line.text}")

    return "\n".join(remapped_lrc_lines)


def remap_segments(
    segments: List[Dict], speech_segments: List[Dict[str, float]]
) -> List[Dict]:
    """結構化片段的時間軸重對應，與 remap_lrc_timestamps 同一套轉換。"""
    remap = speech_time_remapper(speech_segments)
    out: List[Dict] = []
    for seg in segments:
        start = remap(seg.get("start", 0.0))
        if start is None:
            continue
        new = dict(seg)
        new["start"] = start
        if seg.get("end") is not None:
            new["end"] = remap(seg["end"])
        if seg.get("words"):
            words = []
            for w in seg["words"]:
                ws, we = remap(w["start"]), remap(w["end"])
                if ws is None:
                    continue
                words.append({**w, "start": ws, "end": we})
            new["words"] = words or None
        out.append(new)
    return out


def shift_segments(
    segments: List[Dict], offset: float, prefix: Optional[str] = None
) -> List[Dict]:
    """片段時間整體平移 offset 秒；prefix 讓不同切段的 seg_key 不相撞。"""
    out: List[Dict] = []
    for seg in segments:
        new = dict(seg)
        new["start"] = seg.get("start", 0.0) + offset
        if seg.get("end") is not None:
            new["end"] = seg["end"] + offset
        if seg.get("words"):
            new["words"] = [
                {**w, "start": w["start"] + offset, "end": w["end"] + offset}
                for w in seg["words"]
            ]
        if prefix:
            new["seg_key"] = f"{prefix}.{seg.get('seg_key', '')}"
        out.append(new)
    return out


def order_segments(segments: List[Dict]) -> List[Dict]:
    """依時間排序並重編 seq；跨切段合併之後 seq 才會連續。"""
    ordered = sorted(segments, key=lambda s: s.get("start", 0.0))
    for i, seg in enumerate(ordered):
        seg["seq"] = i
    return ordered


def _adjust_lrc_timestamps(lrc_text: str, offset_seconds: float) -> str:
    """將 LRC 每行時間戳整體平移 offset_seconds 秒。"""
    if offset_seconds == 0:
        return lrc_text
    adjusted_lines = []
    for line in lrc_text.strip().split('\n'):
        match = re.match(r'\[(\d{2,3}):(\d{2})\.(\d{2,3})\](.*)', line)
        if match:
            minutes, seconds, ms_str, text_content = match.groups()
            original_time = int(minutes) * 60 + \
                int(seconds) + float(f"0.{ms_str}")
            new_time = original_time + offset_seconds
            new_minutes = int(new_time / 60)
            new_seconds = new_time % 60
            adjusted_lines.append(
                f"[{new_minutes:02d}:{new_seconds:05.2f}]{text_content}")
        else:
            adjusted_lines.append(line)
    return "\n".join(adjusted_lines)


class AudioSegment:
    """音訊片段資訊"""

    def __init__(self, path: Path, start_time: float = 0.0, duration: float = 0.0):
        self.path = path
        self.start_time = start_time
        self.duration = duration

    def __repr__(self):
        return f"AudioSegment(path={self.path.name}, start={self.start_time:.2f}s, duration={self.duration:.2f}s)"


class TranscriptionTask:
    """轉錄任務管理器，處理音訊分割和轉錄流程"""

    def __init__(
        self,
        provider: Provider,
        request: TranscribeRequest,
        progress: ProgressAndCancel,
        temp_dir: Path,
        artifact_task_id: Optional[str] = None,
        original_filename: Optional[str] = None,
    ):
        self.provider = provider
        self.request = request
        self.progress = progress
        self.capabilities = provider.capabilities()[request.model]
        self.temp_dir = temp_dir
        self.artifact_task_id = artifact_task_id
        self.original_filename = original_filename
        self.local_cleanup_list = []
        self.max_duration_seconds = get_settings().transcription_max_duration_seconds
        self.original_file = None
        self.split_threshold_seconds = self.capabilities.single_pass_seconds

        try:
            self.vad_service = get_vad_service()
            logger.info("使用 VAD 服務單例實例")
        except Exception as e:
            logger.warning(f"無法取得 VAD 服務: {e}")
            self.vad_service = None

    def transcribe_audio(self, audio_path: Path) -> TranscriptionTaskResult:
        """
        轉錄音訊檔案的主要方法

        流程：
        1. 去靜音 → 建立純語音檔案
        2. 轉錄純語音檔案
        3. 時間戳重映射回原始時間軸
        4. 如果轉錄失敗且檔案夠長，嘗試分割重試
        """
        logger.info(f"開始轉錄音訊: {audio_path.name}")

        if self.original_file is None:
            # 輸入音檔歸任務生命週期處理（先保留，再清理），這裡不登記清理
            self.original_file = audio_path
        elif audio_path not in self.local_cleanup_list:
            self.local_cleanup_list.append(audio_path)

        duration = self._get_audio_duration(audio_path)
        if duration is None:
            return TranscriptionTaskResult(
                success=False,
                text=f"[[無法讀取檔案 {audio_path.name}]]",
                total_tokens=0
            )

        # --- 去靜音前處理 ---
        speech_segments = None
        transcription_path = audio_path  # 預設直接使用原始檔案

        if self.capabilities.remove_silence and self.vad_service:
            vad_result = self._extract_speech_only(audio_path)
            if vad_result and vad_result.get("speech_only_path"):
                speech_ratio = vad_result.get("speech_ratio", 1.0)
                if speech_ratio < VAD_SPEECH_RATIO_SKIP_THRESHOLD:
                    transcription_path = Path(vad_result["speech_only_path"])
                    speech_segments = vad_result["segments"]
                    logger.info(
                        f"VAD 前處理完成: 語音佔比 {speech_ratio*100:.1f}%, "
                        f"使用純語音檔 ({vad_result['speech_duration']:.1f}s / {duration:.1f}s)"
                    )
                else:
                    logger.info(
                        f"語音佔比 {speech_ratio*100:.1f}% "
                        f"(>={VAD_SPEECH_RATIO_SKIP_THRESHOLD*100:.0f}%), 跳過 VAD 前處理"
                    )

        # --- 轉錄（去靜音之後仍超過閾值的長檔，先分段轉錄） ---
        if speech_segments:
            transcription_duration = sum(
                seg['end'] - seg['start'] for seg in speech_segments)
            silence_boundaries = speech_segment_boundaries(speech_segments)
        else:
            transcription_duration = duration
            silence_boundaries = None
        result = self._transcribe_halved(
            transcription_path, transcription_duration, silence_boundaries)

        # --- 時間戳重映射 ---
        if result.success and speech_segments:
            self.progress.report("校正時間軸...")
            result = TranscriptionTaskResult(
                success=True,
                text=remap_lrc_timestamps(result.text, speech_segments),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
                service_tier_used=result.service_tier_used,
                segments=remap_segments(result.segments, speech_segments),
            )
            logger.info("時間戳已重映射回原始時間軸")

        # 如果成功或檔案很短，直接返回結果
        if result.success or duration < self.max_duration_seconds:
            if not result.success and duration < self.max_duration_seconds:
                logger.info(
                    f"檔案 {audio_path.name} 短於 {self.max_duration_seconds/60:.1f} 分鐘，接受失敗結果")
            return result

        # 如果失敗且檔案夠長，模型能力允許時切段重試；不允許的（例如各段說話者
        # 編號互相獨立）直接回報失敗，讓使用者拿到明確錯誤
        if (not result.success and self.vad_service
                and self.capabilities.split_retry_on_failure):
            logger.info(f"轉錄失敗，檔案長度 {duration:.1f} 秒，嘗試 VAD 分割")
            return self._transcribe_with_splitting(audio_path)

        return result

    def _extract_speech_only(self, audio_path: Path) -> Optional[dict]:
        """去靜音：提取純語音檔案。

        實際的去靜音流程由 :mod:`app.services.vad.preprocess` 共用實作，
        此處只負責呼叫 callback、把產生的暫存檔登記進 cleanup 列表。
        """
        self.progress.report("分析語音活動...")

        result = run_vad_extraction(audio_path, self.temp_dir, self.vad_service)

        # 不論成功與否，cleanup 都要登記，避免暫存檔殘留
        for cf in result.cleanup_files:
            if cf not in self.local_cleanup_list:
                self.local_cleanup_list.append(cf)

        if not result.success:
            return None

        speech_ratio = result.speech_ratio
        used_for_transcription = speech_ratio < VAD_SPEECH_RATIO_SKIP_THRESHOLD
        artifact_id = self.artifact_task_id or audio_path.stem
        artifact_name = self.original_filename or audio_path.name
        if result.speech_only_path:
            persist_speech_extraction(
                task_id=artifact_id,
                original_filename=artifact_name,
                speech_only_path=result.speech_only_path,
                segments=result.segments,
                speech_ratio=speech_ratio,
                speech_duration=result.speech_duration,
                used_for_transcription=used_for_transcription,
            )

        return {
            "speech_only_path": str(result.speech_only_path),
            "segments": result.segments,
            "speech_ratio": result.speech_ratio,
            "speech_duration": result.speech_duration,
        }

    def _get_audio_duration(self, audio_path: Path) -> Optional[float]:
        """取得音訊檔案時長"""
        duration = _ffprobe_duration(audio_path)
        if duration is None:
            logger.error(f"無法取得音訊時長 {audio_path.name}")
        return duration

    def _attempt_transcription(self, audio_path: Path) -> TranscriptionTaskResult:
        """透過供應商轉錄一段音檔；一般錯誤轉成失敗結果，交給上層決定要不要切段重試。"""
        try:
            return self.provider.transcribe(audio_path, self.request, self.progress)
        except (TranscriptionCancelledError, TransientError):
            # 取消與暫時錯誤都不是這一段失敗：往上拋給任務生命週期
            raise
        except Exception as e:
            logger.error(f"轉錄過程發生錯誤: {e}")
            return TranscriptionTaskResult(
                success=False,
                text=f"[[轉錄錯誤: {str(e)}]]",
                total_tokens=0
            )

    def _transcribe_halved(
        self,
        audio_path: Path,
        duration: float,
        silence_boundaries: Optional[List[float]],
    ) -> TranscriptionTaskResult:
        """時長超過閾值時在最接近中點的靜音處切成兩段，分別轉錄後合併。

        遞迴呼叫自身，直到每段低於 ``self.split_threshold_seconds``。
        silence_boundaries 是音檔內已知的靜音位置（秒）——去靜音後的純語音檔
        以有聲區間的交界為準；無資訊（跳過去靜音）時改用 VAD 服務在檔案上找。
        注意：local provider 兩半的說話者編號各自獨立（前半的 S0 未必是
        後半的 S0），多人對話的長檔請自行斟酌（MOSS 的門檻較長，多數檔案不會切）。
        """
        threshold = self.split_threshold_seconds
        if threshold <= 0 or duration <= threshold:
            return self._attempt_transcription(audio_path)

        self.progress.raise_if_cancelled()

        part1 = part2 = None
        split_point = None
        if silence_boundaries:
            split_point = pick_halving_split_point(silence_boundaries, duration)
        if split_point is not None:
            part1 = self.temp_dir / f"{audio_path.stem}.half1.wav"
            part2 = self.temp_dir / f"{audio_path.stem}.half2.wav"
            if not (slice_audio(audio_path, part1, end=split_point)
                    and slice_audio(audio_path, part2, start=split_point)):
                part1 = part2 = None
                split_point = None

        if split_point is None:
            # 沒有可用的已知靜音點：交給 VAD 服務找（找不到會切在正中間）
            if not self.vad_service:
                logger.warning("無 VAD 服務可尋找切割點，長檔不切割直接轉錄")
                return self._attempt_transcription(audio_path)
            # VAD (soundfile/libsndfile) 不支援 m4a 等壓縮格式，先轉為 wav
            wav_for_split = convert_to_wav(audio_path, self.temp_dir)
            if wav_for_split is None:
                logger.warning("無法轉換 WAV 供切割使用，長檔不切割直接轉錄")
                return self._attempt_transcription(audio_path)
            if wav_for_split != audio_path and wav_for_split not in self.local_cleanup_list:
                self.local_cleanup_list.append(wav_for_split)
            segments = self._split_audio_file(wav_for_split)
            if len(segments) < 2:
                logger.warning("長檔切割失敗，不切割直接轉錄")
                return self._attempt_transcription(audio_path)
            part1, part2 = segments[0].path, segments[1].path
            split_point = segments[1].start_time
            # 交界不在已知靜音清單內，後續遞迴改用 VAD 服務重找
            silence_boundaries = None

        for p in (part1, part2):
            if p not in self.local_cleanup_list:
                self.local_cleanup_list.append(p)

        logger.info(
            f"長檔切半: {audio_path.name} ({duration:.0f}s) 於 {split_point:.2f}s 切割")
        self.progress.report(
            f"音檔較長（{duration / 60:.1f} 分鐘），於靜音處切半分段處理...")

        left = right = None
        if silence_boundaries is not None:
            left = [b for b in silence_boundaries if 0 < b < split_point]
            right = [b - split_point for b in silence_boundaries
                     if split_point < b < duration]

        first = self._transcribe_halved(part1, split_point, left)
        if not first.success:
            return first
        second = self._transcribe_halved(part2, duration - split_point, right)
        if not second.success:
            return second

        combined_text = "\n".join(
            [first.text, _adjust_lrc_timestamps(second.text, split_point)])
        tier = (first.service_tier_used
                if first.service_tier_used == second.service_tier_used
                else "standard")
        # 片段與 LRC 走同樣的平移；前後半各自加前綴，避免 seg_key 相撞
        combined_segments = (shift_segments(first.segments, 0.0, prefix="a")
                             + shift_segments(second.segments, split_point, prefix="b"))
        return TranscriptionTaskResult(
            success=True,
            text=combined_text,
            input_tokens=first.input_tokens + second.input_tokens,
            output_tokens=first.output_tokens + second.output_tokens,
            total_tokens=first.total_tokens + second.total_tokens,
            service_tier_used=tier,
            segments=combined_segments,
        )

    def _transcribe_with_splitting(self, audio_path: Path) -> TranscriptionTaskResult:
        """使用 VAD 分割音訊並分別轉錄"""
        # VAD (soundfile/libsndfile) 不支援 m4a 等壓縮格式，先轉為 wav
        wav_path = convert_to_wav(audio_path, self.temp_dir)
        if wav_path is None:
            logger.error(f"無法將 {audio_path.name} 轉換為 WAV 格式")
            return TranscriptionTaskResult(
                success=False,
                text="[[音訊格式轉換失敗]]",
                total_tokens=0
            )
        if wav_path != audio_path:
            self.local_cleanup_list.append(wav_path)

        segments = self._split_audio_file(wav_path)

        if not segments or len(segments) < 2:
            logger.error("無法分割音訊檔案")
            return TranscriptionTaskResult(
                success=False,
                text="[[無法分割音訊檔案]]",
                total_tokens=0
            )

        results = []
        all_segments: List[Dict] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0
        all_flex = True  # 所有片段皆用 flex 才回報 "flex"，只要有一段 fallback 就視為 standard

        for i, segment in enumerate(segments):
            logger.info(f"轉錄片段 {i+1}/{len(segments)}: {segment}")

            # 遞迴轉錄每個片段（如果片段仍然太長，會再次分割）
            segment_result = self.transcribe_audio(segment.path)

            if not segment_result.success:
                logger.error(f"片段 {i+1} 轉錄失敗")
                return TranscriptionTaskResult(
                    success=False,
                    text=f"[[片段 {i+1} 轉錄失敗]]",
                    total_tokens=total_tokens
                )

            adjusted_text = _adjust_lrc_timestamps(
                segment_result.text, segment.start_time)
            results.append(adjusted_text)
            all_segments.extend(shift_segments(
                segment_result.segments, segment.start_time, prefix=f"s{i}"))
            total_input_tokens += segment_result.input_tokens
            total_output_tokens += segment_result.output_tokens
            total_tokens += segment_result.total_tokens
            if segment_result.service_tier_used != "flex":
                all_flex = False

        combined_text = "\n".join(results)

        final_tier = "flex" if (self.request.service_tier == "flex" and all_flex) else "standard"

        return TranscriptionTaskResult(
            success=True,
            text=combined_text,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            total_tokens=total_tokens,
            service_tier_used=final_tier,
            segments=all_segments,
        )

    def _split_audio_file(self, audio_path: Path) -> List[AudioSegment]:
        """使用 VAD 分割音訊檔案"""
        try:
            part1_path, part2_path, split_point = self.vad_service.split_audio_on_silence(
                audio_path=str(audio_path),
                output_dir=str(self.temp_dir)
            )

            if not (part1_path and part2_path and split_point is not None):
                return []

            segments = [
                AudioSegment(
                    path=Path(part1_path),
                    start_time=0.0,
                    duration=split_point
                ),
                AudioSegment(
                    path=Path(part2_path),
                    start_time=split_point,
                    duration=self._get_audio_duration(Path(part2_path)) or 0.0
                )
            ]

            for segment in segments:
                self.local_cleanup_list.append(segment.path)

            artifact_id = self.artifact_task_id or audio_path.stem
            artifact_name = self.original_filename or audio_path.name
            persist_split(
                task_id=artifact_id,
                original_filename=artifact_name,
                part1_path=Path(part1_path),
                part2_path=Path(part2_path),
                split_point=split_point,
            )

            return segments

        except Exception as e:
            logger.error(f"分割音訊檔案失敗: {e}")
            return []

    def cleanup(self):
        """清理供應商的遠端與暫存資源，以及自己產生的暫存檔；不動輸入音檔。"""
        try:
            self.provider.release()
        except Exception as e:
            logger.warning(f"釋放供應商資源失敗: {e}")

        for local_file in set(self.local_cleanup_list):
            try:
                if local_file and local_file.exists():
                    # 只刪 temp_uploads 目錄下的檔案，防止路徑異常時誤刪其他位置
                    if is_temp_upload(local_file):
                        local_file.unlink()
                        logger.info(f"已清理暫存檔案: {local_file.name}")
                    else:
                        logger.warning(
                            f"已跳過清理不在 temp_uploads 目錄中的檔案: {local_file}")
            except Exception as e:
                logger.warning(f"清理本地檔案 {local_file} 失敗: {e}")
