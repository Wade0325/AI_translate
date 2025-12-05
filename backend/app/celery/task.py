import time
import traceback
from pathlib import Path
from typing import Generator
import json
import redis

import soundfile as sf
from sqlalchemy.orm import Session
from langdetect import detect, LangDetectException

from app.celery.celery import celery_app
from app.celery.models import TranscriptionTaskParams
from app.database.session import SessionLocal
from app.provider.google.gemini import GeminiClient
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.services.calculator.service import CalculatorService
from app.services.calculator.models import CalculationItem
from app.services.converter.service import convert_from_lrc, _parse_lrc
from app.services.transcription.flows import (
    TranscriptionTask,
    _remap_lrc_timestamps
)
from app.services.transcription.models import TranscriptionResponse
from app.services.translator.flows import _perform_translation
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# 使用與 FastAPI 完全相同的 Redis 設定。
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
                             json.dumps(message, default=str, ensure_ascii=False))
    except Exception as e:
        logger.error(f"發布狀態更新至 Redis 時失敗: {e}")


def get_db_session() -> Generator[Session, None, None]:
    """Provide a database session for the Celery task."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def cleanup_original_file(file_path: str):
    """清理原始上傳檔案"""
    try:
        original_file = Path(file_path)
        if original_file.exists() and "temp_uploads" in str(original_file):
            original_file.unlink()
            logger.info(f"已刪除原始上傳檔案: {original_file.name}")
    except Exception as e:
        logger.warning(f"刪除原始檔案失敗: {e}")


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

    # 更新任務狀態
    def update_status(status_text: str, status_code: str = "PROCESSING", result_data: dict = None):
        publish_status(client_id, file_uid, task_uuid, status_text,
                       result_data=result_data, status_code=status_code)

    db_generator = get_db_session()
    db = next(db_generator)

    start_time = time.time()
    local_path = Path(task_params.file_path)
    log_repo = TranscriptionLogRepository()
    task_manager = None

    try:
        # 1. 新增一筆任務
        initial_log_data = {
            "status": "PROCESSING",
            "original_filename": task_params.original_filename,
            "model_used": task_params.model,
            "source_language": task_params.source_lang,
            "task_uuid": task_uuid,
        }
        log_repo.insert_log(db, initial_log_data)
        logger.info(
            f"Celery task started. Task ID: {task_uuid}")

        update_status("檔案處理與分析...")

        # 2. 獲取音訊時長
        try:
            with sf.SoundFile(str(local_path)) as f:
                audio_duration_seconds = f.frames / f.samplerate
            logger.info(f"Audio file info for task {task_uuid}:")
            logger.info(f" - Filename: {local_path.name}")
            logger.info(
                f" - Duration: {audio_duration_seconds:>10.2f} seconds")
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

        # 4. 初始化轉錄任務管理器
        # 根據是否提供 original_text 來決定 prompt
        if task_params.original_text:
            # 如果有提供文本，我們就建立一個對齊用的 prompt
            user_prompt = f"""
請你扮演一位專業的逐字稿專家。你的任務是將提供的音檔與以下的完整逐字稿內容進行對齊，並生成一個帶有時間戳的LRC格式檔案。

這是完整的逐字稿：
---
{task_params.original_text}
---

請仔細聆聽音檔，為這份逐字稿加上精確的時間戳，並以LRC格式輸出。
"""
        else:
            # 否則，使用使用者自訂的 prompt 或預設值
            user_prompt = task_params.prompt or "請將以下音檔轉錄成LRC格式的逐字稿。"

        task_manager = TranscriptionTask(
            client=client,
            model=task_params.model,
            prompt=user_prompt,  # 使用上面決定的 prompt
            temp_dir=local_path.parent,
            status_callback=update_status
        )

        # 5. 執行轉錄 (包含VAD失敗重試邏輯)
        logger.info(f"Starting transcription. Task ID : {task_uuid}")
        transcription_result = task_manager.transcribe_audio(local_path)

        raw_lrc_text = transcription_result.text
        input_tokens = transcription_result.input_tokens
        output_tokens = transcription_result.output_tokens
        total_tokens = transcription_result.total_tokens
        logger.info(
            f"Transcription complete. Task ID: {task_uuid}. Tokens used: {total_tokens:,}")

        # 6. 時間戳重對應
        if task_params.segments_for_remapping and raw_lrc_text:
            logger.info(f"Remapping timestamps. Task ID: {task_uuid}")
            update_status("校正時間軸...")
            final_lrc_text = _remap_lrc_timestamps(
                raw_lrc_text, task_params.segments_for_remapping)
        else:
            final_lrc_text = raw_lrc_text

        # 7. 語言偵測與翻譯流程
        translation_input_tokens = 0
        translation_output_tokens = 0
        if task_params.target_lang and final_lrc_text:
            update_status("偵測字幕語言...")
            parsed_lines = _parse_lrc(final_lrc_text)
            if parsed_lines:
                full_text = "\n".join(line.text for line in parsed_lines)

                # 優先使用前端指定的 source_lang 來判斷，如果沒有再偵測
                source_lang_to_check = task_params.source_lang
                if not source_lang_to_check:
                    try:
                        source_lang_to_check = detect(full_text)
                        logger.info(
                            f"前端未指定輸入語言，自動偵測結果: {source_lang_to_check}")
                    except LangDetectException:
                        logger.warning("無法偵測語言，跳過翻譯步驟。")
                        source_lang_to_check = None

                if source_lang_to_check:
                    logger.info(
                        f"輸入語言: {source_lang_to_check}, 輸出語言: {task_params.target_lang}")

                    # 比較基本語言碼，例如 'en' 和 'zh'
                    if source_lang_to_check.split('-')[0] != task_params.target_lang.split('-')[0]:
                        update_status("語言不符，開始整體翻譯字幕...")

                        # 建立一個新的 Prompt，要求模型翻譯文字內容同時保持 LRC 格式
                        translation_prompt = (
                            f"Translate the text portions of the following LRC format content from {source_lang_to_check} to {task_params.target_lang}. "
                            "It is crucial that you DO NOT alter the timestamps (e.g., [00:01.23]). "
                            "Your response should be only the translated LRC content in the exact same format."
                        )

                        # 將完整的轉錄搞全部翻譯
                        trans_result = _perform_translation(
                            client=client,
                            model=task_params.model,
                            prompt=translation_prompt,
                            text_to_translate=final_lrc_text
                        )

                        if trans_result.success:
                            final_lrc_text = trans_result.translated_text
                            translation_input_tokens = trans_result.input_tokens
                            translation_output_tokens = trans_result.output_tokens
                            logger.info(
                                f"字幕整體翻譯成功。翻譯 token 用量: input={translation_input_tokens}, output={translation_output_tokens}")
                        else:
                            logger.warning(
                                f"字幕整體翻譯失敗: {trans_result.translated_text}，將使用原始轉錄結果。")

        # 8. 轉換格式
        update_status("正在轉換字幕格式...")
        transcripts_model = convert_from_lrc(final_lrc_text)
        final_transcripts = transcripts_model.model_dump() if transcripts_model else {}

        # 9. 計算費用
        update_status("正在計算費用...")
        items = []
        if total_tokens > 0:
            items.append(CalculationItem(
                model=task_params.model,
                task_name="total_transcription",
                input_tokens=input_tokens,
                output_tokens=output_tokens
            ))

        # 將翻譯費用加入計算
        if translation_input_tokens > 0 or translation_output_tokens > 0:
            items.append(CalculationItem(
                model=task_params.model,
                task_name="total_translation",
                input_tokens=translation_input_tokens,
                output_tokens=translation_output_tokens
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
            f"Metrics calculated. Task ID: {task_uuid}. Cost: ${metrics_response.cost:.6f}")

        # 10. 更新任務狀態為 COMPLETED
        update_data = {
            "status": "COMPLETED",
            "audio_duration_seconds": metrics_response.audio_duration_seconds,
            "processing_time_seconds": metrics_response.processing_time_seconds,
            "total_tokens": metrics_response.total_tokens,
            "cost": metrics_response.cost,
        }
        log_repo.update_log(db, task_uuid, update_data)
        logger.info(f"Task status updated to COMPLETED. Task ID: {task_uuid}")

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

        # 更新日誌為 FAILED
        failure_update_data = {
            "status": "FAILED",
            "error_message": str(e),
            "processing_time_seconds": processing_time_seconds
        }
        log_repo.update_log(db, task_uuid, failure_update_data)

        update_status(f"任務失敗: {e}", status_code="FAILED")
        raise e
    finally:
        # 刪除轉錄完成的檔案
        if task_manager:
            task_manager.cleanup()
            logger.info(
                f"Temporary files cleaned up for task {task_uuid}.")

        # 確保資料庫 session 被關閉
        next(db_generator, None)
