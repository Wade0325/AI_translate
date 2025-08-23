import time
import traceback
from pathlib import Path
from typing import Generator, Optional, List, Dict
import json
import redis

import soundfile as sf
from sqlalchemy.orm import Session

from app.celery.celery import celery_app
from app.celery.models import TranscriptionTaskParams
from app.database.session import SessionLocal
from app.provider.google.gemini import GeminiClient
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.services.calculator.service import CalculatorService
from app.services.calculator.models import CalculationItem
from app.services.converter.service import convert_from_lrc
from app.services.transcription.flows import (
    TranscriptionTask,
    _remap_lrc_timestamps
)
from app.services.transcription.models import TranscriptionResponse
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# 這確保了 Worker 使用與 FastAPI 主應用完全相同的 Redis 設定。
redis_client = redis.from_url(celery_app.conf.broker_url)
logger.info("Celery task: Redis client initialized from Celery broker URL.")


def publish_status(client_id: str, file_uid: str, task_uuid: str, status_text: str, result_data: dict = None, status_code: str = "PROCESSING"):
    """向 Redis 發布狀態更新"""
    message = {
        "client_id": client_id,
        "file_uid": file_uid,
        "task_uuid": task_uuid,
        "status_code": status_code,
        "status_text": status_text,
    }
    if result_data:
        message["result"] = result_data

    try:
        redis_client.publish("transcription_updates",
                             json.dumps(message, default=str))
    except Exception as e:
        logger.error(f"發布狀態更新至 Redis 時失敗: {e}")


def get_db_session() -> Generator[Session, None, None]:
    """Provide a database session for the Celery task."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@celery_app.task(bind=True)
def transcribe_media_task(self, task_params_dict: dict):
    """
    Celery background task for transcription.
    This function contains the core logic migrated from the original transcription_flow.
    """
    task_params = TranscriptionTaskParams.model_validate(task_params_dict)
    task_uuid = self.request.id
    client_id = task_params.client_id
    file_uid = task_params.file_uid

    # 建立一個輔助函式，自動傳入必要的 ID
    def update_status(status_text: str, status_code: str = "PROCESSING", result_data: dict = None):
        publish_status(client_id, file_uid, task_uuid, status_text,
                       result_data=result_data, status_code=status_code)

    db_generator = get_db_session()
    db = next(db_generator)

    start_time = time.time()
    local_path = Path(task_params.file_path)
    log_repo = TranscriptionLogRepository()

    # 1. 建立初始日誌
    initial_log_data = {
        "status": "PROCESSING",
        "original_filename": task_params.original_filename,
        "model_used": task_params.model,
        "source_language": task_params.source_lang,
        "task_uuid": self.request.id,
    }
    new_log = log_repo.create_log(db, initial_log_data)
    task_uuid = new_log.task_uuid
    logger.info(
        f"Celery task started. Log ID: {task_uuid}, Celery ID: {self.request.id}")

    update_status("檔案處理與分析...")

    try:
        # 2. 獲取音訊時長
        try:
            with sf.SoundFile(str(local_path)) as f:
                audio_duration_seconds = f.frames / f.samplerate
            logger.info(f"Audio file info for task {task_uuid}:")
            logger.info(f"  - Filename: {local_path.name}")
            logger.info(
                f"  - Duration: {audio_duration_seconds:>10.2f} seconds")
        except Exception as e:
            logger.warning(
                f"Could not read audio duration for {local_path.name}. Error: {e}")
            audio_duration_seconds = 0.0

        # 3. 初始化 Gemini Client
        if task_params.provider.lower() != 'google':
            raise ValueError(
                f"Provider '{task_params.provider}' is not supported. Only 'google' is allowed.")

        logger.info(
            f"Initializing Gemini Client for model: {task_params.model}")
        client = GeminiClient(task_params.api_keys).client
        if not client:
            raise ValueError(
                "Failed to initialize Gemini Client. Check API key.")

        update_status("正在初始化模型...")

        # 4. 準備 Prompt
        final_prompt = task_params.prompt or "You are an expert audio transcriptionist. Please transcribe the audio file into a detailed, accurate, and well-formatted LRC file."

        # 5. 建立轉錄任務管理器
        task_manager = TranscriptionTask(
            client=client,
            model=task_params.model,
            prompt=final_prompt,
            temp_dir=local_path.parent,
            status_callback=update_status  # 傳入回呼函式
        )

        # 6. 執行轉錄 (包含VAD失敗重試邏輯)
        logger.info(f"Starting transcription task for log ID: {task_uuid}")
        transcription_result = task_manager.transcribe_audio(local_path)

        raw_lrc_text = transcription_result.text
        input_tokens = transcription_result.input_tokens
        output_tokens = transcription_result.output_tokens
        total_tokens_used = transcription_result.total_tokens_used
        logger.info(
            f"Transcription complete for log ID: {task_uuid}. Tokens used: {total_tokens_used:,}")

        # 7. 時間戳重對應
        if task_params.segments_for_remapping and raw_lrc_text:
            logger.info(f"Remapping timestamps for log ID: {task_uuid}")
            update_status("校正時間軸...")
            final_lrc_text = _remap_lrc_timestamps(
                raw_lrc_text, task_params.segments_for_remapping)
        else:
            final_lrc_text = raw_lrc_text

        # 8. 轉換格式
        update_status("正在轉換字幕格式...")
        transcripts_model = convert_from_lrc(final_lrc_text)
        final_transcripts = transcripts_model.model_dump() if transcripts_model else {}

        # 9. 計算費用
        update_status("正在計算費用...")
        items = []
        if total_tokens_used > 0:
            items.append(CalculationItem(
                task_name="total_transcription",
                input_tokens=input_tokens,
                output_tokens=output_tokens
            ))

        processing_time_seconds = time.time() - start_time
        calculator = CalculatorService()
        metrics_response = calculator.calculate_metrics(
            items=items,
            model=task_params.model,
            processing_time_seconds=processing_time_seconds,
            audio_duration_seconds=audio_duration_seconds
        )
        logger.info(
            f"Metrics calculated for log ID: {task_uuid}. Cost: ${metrics_response.cost:.6f}")

        # 10. 更新日誌為 COMPLETED
        update_data = {
            "status": "COMPLETED",
            "audio_duration_seconds": metrics_response.audio_duration_seconds,
            "processing_time_seconds": metrics_response.processing_time_seconds,
            "total_tokens": metrics_response.total_tokens,
            "cost": metrics_response.cost,
        }
        log_repo.update_log(db, task_uuid, update_data)
        logger.info(f"Log status updated to COMPLETED for ID: {task_uuid}")

        # 清理暫存檔案
        task_manager.cleanup()
        logger.info(f"Temporary files cleaned up for task {task_uuid}.")

        # 準備回傳結果
        final_response = TranscriptionResponse(
            task_uuid=task_uuid,
            transcripts=final_transcripts,
            tokens_used=metrics_response.total_tokens,
            cost=metrics_response.cost,
            model=task_params.model,
            source_language=task_params.source_lang,
            processing_time_seconds=metrics_response.processing_time_seconds,
            audio_duration_seconds=metrics_response.audio_duration_seconds,
            cost_breakdown=metrics_response.breakdown
        )

        final_response_dict = final_response.model_dump()

        # Pydantic v2 a little bit different
        if 'task_uuid' in final_response_dict and hasattr(final_response_dict['task_uuid'], 'hex'):
            final_response_dict['task_uuid'] = final_response_dict['task_uuid'].hex

        update_status("任務完成", status_code="COMPLETED",
                      result_data=final_response_dict)

        return final_response_dict

    except Exception as e:
        processing_time_seconds = time.time() - start_time
        error_message = traceback.format_exc()
        logger.error(
            f"Transcription task failed for log ID: {task_uuid}\n{error_message}")

        # 清理暫存檔案
        task_manager.cleanup()
        logger.info(
            f"Temporary files cleaned up after failure for task {task_uuid}.")

        # 更新日誌為 FAILED
        failure_update_data = {
            "status": "FAILED",
            "error_message": str(e),
            "processing_time_seconds": processing_time_seconds
        }
        log_repo.update_log(db, task_uuid, failure_update_data)

        update_status(f"任務失敗: {e}", status_code="FAILED")

        # 這裡可以選擇性地 re-raise 異常，讓 Celery 知道任務失敗了
        raise e
    finally:
        # 確保資料庫 session 被關閉
        next(db_generator, None)
