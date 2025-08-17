import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import soundfile as sf
from sqlalchemy.orm import Session
import traceback

from app.utils.logger import setup_logger
from app.provider.google.gemini import (
    upload_file_to_gemini,
    transcribe_with_uploaded_file,
    cleanup_gemini_file,
    GeminiClient
)
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.services.converter.service import convert_from_lrc
from app.services.converter.service import _parse_lrc
from app.services.vad.service import get_vad_service
from app.services.calculator.service import CalculatorService
from app.services.calculator.models import CalculationItem

from .models import (
    TranscriptionRequest,
    TranscriptionTaskResult,
    TranscriptionResponse,
    # ModelConfiguration
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

    def __init__(self, client, model_name: str, prompt: str, temp_dir: Path):
        self.client = client
        self.model_name = model_name
        self.prompt = prompt
        self.temp_dir = temp_dir
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
                total_tokens_used=0
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
            gemini_file = upload_file_to_gemini(audio_path, self.client)
            self.gemini_cleanup_list.append(gemini_file)

            # 執行轉錄
            result = transcribe_with_uploaded_file(
                self.client, gemini_file, self.model_name, self.prompt
            )

            return TranscriptionTaskResult(
                success=result["success"],
                text=result.get("text", ""),
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                total_tokens_used=result.get("total_tokens", 0)
            )
        except Exception as e:
            logger.error(f"轉錄過程發生錯誤: {e}")
            return TranscriptionTaskResult(
                success=False,
                text=f"[[轉錄錯誤: {str(e)}]]",
                total_tokens_used=0
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
                total_tokens_used=0
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
                    total_tokens_used=total_tokens
                )

            # 調整時間戳並收集結果
            adjusted_text = self._adjust_timestamps(
                segment_result.text,
                segment.start_time
            )
            results.append(adjusted_text)
            total_input_tokens += segment_result.input_tokens
            total_output_tokens += segment_result.output_tokens
            total_tokens += segment_result.total_tokens_used

        # 合併所有結果
        combined_text = "\n".join(results)

        return TranscriptionTaskResult(
            success=True,
            text=combined_text,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            total_tokens_used=total_tokens
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
        """清理所有暫存檔案，但保留原始檔案"""
        # 清理 Gemini 檔案
        for gemini_file in self.gemini_cleanup_list:
            try:
                cleanup_gemini_file(self.client, gemini_file)
            except Exception as e:
                logger.warning(f"清理 Gemini 檔案失敗: {e}")

        # 清理本地檔案（跳過原始檔案）
        for local_file in self.local_cleanup_list:
            if local_file != self.original_file and local_file.exists():
                try:
                    local_file.unlink()
                    logger.info(f"已清理暫存檔案: {local_file.name}")
                except Exception as e:
                    logger.warning(f"清理本地檔案失敗: {e}")


def transcription_flow(db: Session, request: TranscriptionRequest) -> TranscriptionResponse:
    """
    完整的轉錄流程：接收任務後呼叫 Gemini API 並取得結果，同時記錄日誌。
    """
    start_time = time.time()
    local_path = Path(request.file_path)
    log_repo = TranscriptionLogRepository()

    # 1. 建立初始日誌
    initial_log_data = {
        "status": "PROCESSING",
        "original_filename": request.original_filename,
        "model_used": request.model,
        "source_language": request.source_lang,
    }
    new_log = log_repo.create_log(db, initial_log_data)
    task_uuid = new_log.task_uuid
    logger.info(f"建立轉錄日誌，ID: {task_uuid}")

    try:
        # 2. 獲取音訊時長
        try:
            with sf.SoundFile(str(local_path)) as f:
                audio_duration_seconds = f.frames / f.samplerate
            logger.info(f"音訊檔案資訊:")
            logger.info(f"  - 檔案名稱: {local_path.name}")
            logger.info(f"  - 音訊時長: {audio_duration_seconds:>10.2f} 秒")
        except Exception as e:
            logger.warning(f"無法讀取音訊檔案時長 {local_path.name}。錯誤：{e}")
            audio_duration_seconds = 0.0

        # 3. 直接使用前端傳來的參數初始化 Client
        if request.provider.lower() != 'google':
            raise ValueError(
                f"目前僅支援 'google' provider，但收到 '{request.provider}'")

        logger.info(f"正在初始化 Gemini Client，模型: {request.model}")
        client = GeminiClient(request.api_key).client
        if not client:
            raise ValueError("無法初始化 Gemini Client，請檢查 API 金鑰")

        # 4. 準備 prompt，如果前端沒給，就用一個通用的預設值
        final_prompt = request.prompt or "You are an expert audio transcriptionist. Please transcribe the audio file into a detailed, accurate, and well-formatted LRC file."

        # 5. 建立轉錄任務管理器
        task_manager = TranscriptionTask(
            client=client,
            model_name=request.model,
            prompt=final_prompt,
            temp_dir=local_path.parent
        )

        # 6. 執行轉錄
        logger.info("開始執行轉錄任務")
        transcription_result = task_manager.transcribe_audio(local_path)

        raw_lrc_text = transcription_result.text
        input_tokens = transcription_result.input_tokens
        output_tokens = transcription_result.output_tokens
        total_tokens_used = transcription_result.total_tokens_used
        logger.info(
            f"轉錄完成，輸入 tokens: {input_tokens:,}, 輸出 tokens: {output_tokens:,}, 總計: {total_tokens_used:,}")

        # 7. 時間戳重對應（如果需要）
        if request.segments_for_remapping and raw_lrc_text:
            logger.info("開始重新對應時間戳")
            final_lrc_text = _remap_lrc_timestamps(
                raw_lrc_text, request.segments_for_remapping)
        else:
            final_lrc_text = raw_lrc_text

        # 8. 轉換為各種格式
        transcripts_model = convert_from_lrc(final_lrc_text)
        final_transcripts = transcripts_model.model_dump() if transcripts_model else {}

        # 9. 計算費用和指標
        items = []
        if total_tokens_used > 0:
            items.append(CalculationItem(
                task_name="total_transcription",
                input_tokens=input_tokens,
                output_tokens=output_tokens
            ))

        processing_time_seconds = time.time() - start_time
        logger.info(f"轉錄任務統計:")
        logger.info(f"  - 總處理時間: {processing_time_seconds:>10.2f} 秒")

        calculator = CalculatorService()
        metrics_response = calculator.calculate_metrics(
            items=items,
            model_name=request.model,
            processing_time_seconds=processing_time_seconds,
            audio_duration_seconds=audio_duration_seconds
        )
        logger.info(f"轉錄任務完成:")
        logger.info(f"  - 總費用:     ${metrics_response.cost:>10.6f}")

        # 10. 更新日誌為 COMPLETED
        update_data = {
            "status": "COMPLETED",
            "audio_duration_seconds": metrics_response.audio_duration_seconds,
            "processing_time_seconds": metrics_response.processing_time_seconds,
            "total_tokens": metrics_response.total_tokens,
            "cost": metrics_response.cost,
        }
        log_repo.update_log(db, task_uuid, update_data)
        logger.info(f"更新日誌為 COMPLETED, ID: {task_uuid}")

        # 清理檔案
        task_manager.cleanup()

        return TranscriptionResponse(
            task_uuid=task_uuid,
            transcripts=final_transcripts,
            tokens_used=metrics_response.total_tokens,
            cost=metrics_response.cost,
            model=request.model,
            source_language=request.source_lang,
            processing_time_seconds=metrics_response.processing_time_seconds,
            audio_duration_seconds=metrics_response.audio_duration_seconds,
            cost_breakdown=metrics_response.breakdown
        )

    except Exception as e:
        processing_time_seconds = time.time() - start_time
        error_message = traceback.format_exc()
        logger.error(f"轉錄流程發生錯誤, ID: {task_uuid}\n{error_message}")

        # 更新日誌為 FAILED
        failure_update_data = {
            "status": "FAILED",
            "error_message": str(e),  # 儲存簡潔的錯誤訊息
            "processing_time_seconds": processing_time_seconds
        }
        log_repo.update_log(db, task_uuid, failure_update_data)
        logger.info(f"更新日誌為 FAILED, ID: {task_uuid}")
        raise e
