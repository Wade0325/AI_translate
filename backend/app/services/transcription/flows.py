from pathlib import Path
from typing import List, Dict, Optional
import soundfile as sf

from app.utils.logger import setup_logger
from app.provider.google.gemini import (
    upload_file_to_gemini,
    transcribe_with_uploaded_file,
    cleanup_gemini_file
)
from app.services.converter.service import _parse_lrc
from app.services.vad.service import get_vad_service

from .models import (
    TranscriptionTaskResult
)

logger = setup_logger(__name__)


def _remap_lrc_timestamps(lrc_text: str, segments: List[Dict[str, float]]) -> str:
    """將 LRC 時間戳從拼接後的時間軸重對應回原始時間軸"""
    parsed_lines = _parse_lrc(lrc_text)
    if not parsed_lines:
        return ""

    segment_durations = [seg['end'] - seg['start'] for seg in segments]
    cumulative_durations = [sum(segment_durations[:i])
                            for i in range(len(segment_durations))]

    remapped_lrc_lines = []
    for line in parsed_lines:
        lrc_time = line['time']
        text = line['text']

        # 找到 lrc_time 所在的原始片段
        segment_index = -1
        for i, cum_dur in enumerate(cumulative_durations):
            if lrc_time < cum_dur + segment_durations[i]:
                segment_index = i
                break

        if segment_index != -1:
            time_in_segment = lrc_time - cumulative_durations[segment_index]
            original_start_time = segments[segment_index]['start']
            remapped_time = original_start_time + time_in_segment

            # 格式化回 LRC 時間戳
            minutes = int(remapped_time // 60)
            seconds = int(remapped_time % 60)
            milliseconds = int(
                (remapped_time - int(remapped_time)) * 100)  # 保持2位數
            remapped_lrc_lines.append(
                f"[{minutes:02d}:{seconds:02d}.{milliseconds:02d}]{text}")

    return "\n".join(remapped_lrc_lines)


def _adjust_lrc_timestamps(lrc_text: str, offset_seconds: float) -> str:
    """一個本地輔助函式，用於校正 LRC 時間戳。"""
    import re
    if offset_seconds == 0:
        return lrc_text
    adjusted_lines = []
    for line in lrc_text.strip().split('\n'):
        match = re.match(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)', line)
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


# 刪除整個 _get_model_configuration 函數
# def _get_model_configuration(db: Session, model: str, prompt_override: Optional[str] = None) -> ModelConfiguration:
#    ...


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

    def __init__(self, client, model: str, prompt: str, temp_dir: Path, status_callback=None):
        self.client = client
        self.model = model
        self.prompt = prompt
        self.temp_dir = temp_dir
        self.status_callback = status_callback
        self.local_cleanup_list = []
        self.gemini_cleanup_list = []
        self.max_duration_seconds = 180  # 3 分鐘
        self.original_file = None  # 明確標記原始檔案

        # 使用單例 VAD 服務
        try:
            self.vad_service = get_vad_service()
            logger.info("使用 VAD 服務單例實例")
        except Exception as e:
            logger.warning(f"無法取得 VAD 服務: {e}")
            self.vad_service = None

    def transcribe_audio(self, audio_path: Path) -> TranscriptionTaskResult:
        """
        轉錄音訊檔案的主要方法
        如果檔案太長且轉錄失敗，會自動分割並分別轉錄
        """
        logger.info(f"開始轉錄音訊: {audio_path.name}")

        # 記錄原始檔案
        if self.original_file is None:
            self.original_file = audio_path

        # 將檔案加入清理列表
        if audio_path not in self.local_cleanup_list:
            self.local_cleanup_list.append(audio_path)

        # 取得音訊時長
        duration = self._get_audio_duration(audio_path)
        if duration is None:
            return TranscriptionTaskResult(
                success=False,
                text=f"[[無法讀取檔案 {audio_path.name}]]",
                total_tokens=0
            )

        # 嘗試直接轉錄
        result = self._attempt_transcription(audio_path)

        # 如果成功或檔案很短，直接返回結果
        if result.success or duration < self.max_duration_seconds:
            if not result.success and duration < self.max_duration_seconds:
                logger.info(
                    f"檔案 {audio_path.name} 短於 {self.max_duration_seconds/60:.1f} 分鐘，接受失敗結果")
            return result

        # 如果失敗且檔案夠長，嘗試分割
        if not result.success and self.vad_service:
            logger.info(f"轉錄失敗，檔案長度 {duration:.1f} 秒，嘗試 VAD 分割")
            return self._transcribe_with_splitting(audio_path)

        return result

    def _get_audio_duration(self, audio_path: Path) -> Optional[float]:
        """取得音訊檔案時長"""
        try:
            with sf.SoundFile(str(audio_path)) as f:
                return f.frames / f.samplerate
        except Exception as e:
            logger.error(f"無法取得音訊時長 {audio_path.name}: {e}")
            return None

    def _attempt_transcription(self, audio_path: Path) -> TranscriptionTaskResult:
        """嘗試轉錄單一音訊檔案"""
        try:
            # 上傳檔案到 Gemini
            gemini_file = upload_file_to_gemini(
                audio_path, self.client, self.status_callback)
            self.gemini_cleanup_list.append(gemini_file)

            # 執行轉錄
            if self.status_callback:
                self.status_callback("AI模型處理中...")

            result = transcribe_with_uploaded_file(
                self.client, gemini_file, self.model, self.prompt
            )

            return TranscriptionTaskResult(
                success=result["success"],
                text=result.get("text", ""),
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                total_tokens=result.get("total_tokens", 0)
            )
        except Exception as e:
            logger.error(f"轉錄過程發生錯誤: {e}")
            return TranscriptionTaskResult(
                success=False,
                text=f"[[轉錄錯誤: {str(e)}]]",
                total_tokens=0
            )

    def _transcribe_with_splitting(self, audio_path: Path) -> TranscriptionTaskResult:
        """使用 VAD 分割音訊並分別轉錄"""
        # 使用 VAD 尋找靜音點並分割
        segments = self._split_audio_file(audio_path)

        if not segments or len(segments) < 2:
            logger.error("無法分割音訊檔案")
            return TranscriptionTaskResult(
                success=False,
                text="[[無法分割音訊檔案]]",
                total_tokens=0
            )

        # 轉錄所有片段
        results = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0

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

            # 調整時間戳並收集結果
            adjusted_text = self._adjust_timestamps(
                segment_result.text,
                segment.start_time
            )
            results.append(adjusted_text)
            total_input_tokens += segment_result.input_tokens
            total_output_tokens += segment_result.output_tokens
            total_tokens += segment_result.total_tokens

        # 合併所有結果
        combined_text = "\n".join(results)

        return TranscriptionTaskResult(
            success=True,
            text=combined_text,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            total_tokens=total_tokens
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

            # 建立片段資訊
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

            # 加入清理列表
            for segment in segments:
                self.local_cleanup_list.append(segment.path)

            return segments

        except Exception as e:
            logger.error(f"分割音訊檔案失敗: {e}")
            return []

    def _adjust_timestamps(self, lrc_text: str, offset_seconds: float) -> str:
        """調整 LRC 時間戳"""
        if offset_seconds == 0:
            return lrc_text
        return _adjust_lrc_timestamps(lrc_text, offset_seconds)

    def cleanup(self):
        """清理所有相關的暫存檔案，包括 Gemini 檔案、本地暫存檔和原始上傳檔案。"""
        # 清理 Gemini 檔案
        for gemini_file in self.gemini_cleanup_list:
            try:
                cleanup_gemini_file(self.client, gemini_file)
            except Exception as e:
                logger.warning(f"清理 Gemini 檔案失敗: {e}")

        # 清理本地檔案 (包含原始檔案)
        # 將原始檔案加入清理列表，確保它也被處理
        all_local_files_to_clean = self.local_cleanup_list
        if self.original_file:
            all_local_files_to_clean.append(self.original_file)

        # 使用 set 去除重複路徑
        for local_file in set(all_local_files_to_clean):
            try:
                if local_file and local_file.exists():
                    # 增加檢查，確保只刪除 temp_uploads 目錄下的檔案，防止意外刪除
                    if "temp_uploads" in str(local_file.parent):
                        local_file.unlink()
                        logger.info(f"已清理暫存檔案: {local_file.name}")
                    else:
                        logger.warning(
                            f"已跳過清理不在 temp_uploads 目錄中的檔案: {local_file}")
            except Exception as e:
                logger.warning(f"清理本地檔案 {local_file} 失敗: {e}")
