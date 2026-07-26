import time
import traceback
from pathlib import Path
from datetime import datetime

from app.celery.celery import celery_app
from app.celery.cancellation import clear_cancel_flag, is_cancel_requested
from app.celery.models import TranscriptionTaskParams
from app.celery.notifier import publish_status
from app.core.config import get_settings
from app.core.default_prompt import build_prompt
from app.database.session import SessionLocal
from app.exceptions import GeminiTransientError, TranscriptionCancelledError
from app.provider.google.gemini import GeminiClient
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.services.calculator.service import CalculatorService
from app.services.calculator.models import CalculationItem
from app.services.converter.service import convert_from_lrc
from app.services.transcription.flows import TranscriptionTask
from app.utils.audio import get_audio_duration
from app.services.transcription.models import TranscriptionResponse
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

FLEX_COST_DISCOUNT = get_settings().flex_cost_discount


@celery_app.task(
    bind=True,
    autoretry_for=(GeminiTransientError,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
)
def transcribe_media_task(self, task_params_dict: dict):
    """單檔轉錄 Celery 任務：VAD 前處理 → 轉錄 → 格式轉換 → 計費 → 寫 DB。"""
    task_params = TranscriptionTaskParams.model_validate(task_params_dict)
    task_uuid = self.request.id
    client_id = task_params.client_id
    file_uid = task_params.file_uid

    def update_status(status_text: str, status_code: str = "PROCESSING", result_data: dict = None):
        publish_status(
            client_id,
            task_uuid,
            status_text,
            status_code=status_code,
            file_uid=file_uid,
            result_data=result_data,
        )

    # 任務在佇列等待期間可能已被取消；revoke 廣播可能沒送達（worker 當時離線），
    # 靠旗標做最後攔截
    if is_cancel_requested(file_uid):
        clear_cancel_flag(file_uid)
        logger.info(f"任務 {task_uuid} 在啟動前已被取消 (file_uid={file_uid})")
        update_status("任務已取消", status_code="CANCELLED")
        return {"cancelled": True}

    db = SessionLocal()

    start_time = time.time()
    local_path = Path(task_params.file_path)
    log_repo = TranscriptionLogRepository()
    task_manager = None

    try:
        initial_log_data = {
            "status": "PROCESSING",
            "original_filename": task_params.original_filename,
            "model_used": task_params.model,
            "source_language": task_params.source_lang,
            "task_uuid": task_uuid,
            "provider": task_params.provider,
            "target_language": task_params.target_lang,
            "is_batch": False,
            "session_id": task_params.session_id,
            "file_uid": task_params.file_uid,
        }
        log_repo.insert_log(db, initial_log_data)
        if task_params.session_id:
            logger.info(
                f"TranscriptionLog created session_id={task_params.session_id} "
                f"file_uid={task_params.file_uid}")
        else:
            logger.warning(
                f"TranscriptionLog missing session_id file_uid={task_params.file_uid}")
        logger.info(
            f"Celery task started. Task ID: {task_uuid}")

        update_status("檔案處理與分析...")

        audio_duration_seconds = get_audio_duration(local_path) or 0.0
        if audio_duration_seconds > 0:
            logger.info(f"Audio file info for task {task_uuid}:")
            logger.info(f" - Filename: {local_path.name}")
            logger.info(
                f" - Duration: {audio_duration_seconds:>10.2f} seconds")
        else:
            logger.warning(
                f"Could not read audio duration for {local_path.name}.")

        # 初始化 provider client（local 為本地模型，不需 API key）
        provider = task_params.provider.lower()
        if provider not in ('google', 'local'):
            raise ValueError(
                f"Provider '{task_params.provider}' is not supported. Only 'google' or 'local' is allowed.")

        client = None
        if provider == 'google':
            logger.info(
                f"Initializing Gemini Client for model: {task_params.model}")
            client = GeminiClient(task_params.api_keys).client
            if not client:
                raise ValueError(
                    "Failed to initialize Gemini Client. Check API key.")

        update_status("正在初始化模型...")

        # 有提供逐字稿時改走「對齊」prompt，只補時間戳不重新轉錄
        if task_params.original_text:
            user_prompt = f"""
請你扮演一位專業的逐字稿專家。你的任務是將提供的音檔與以下的完整逐字稿內容進行對齊，並生成一個帶有時間戳的LRC格式檔案。

這是完整的逐字稿：
---
{task_params.original_text}
---

請仔細聆聽音檔，為這份逐字稿加上精確的時間戳，並以LRC格式輸出。
"""
        else:
            user_prompt = build_prompt(
                source_lang=task_params.source_lang,
                target_lang=task_params.target_lang,
                multi_speaker=task_params.multi_speaker,
                template=task_params.prompt or None,
            )

        task_manager = TranscriptionTask(
            client=client,
            model=task_params.model,
            prompt=user_prompt,
            temp_dir=local_path.parent,
            status_callback=update_status,
            service_tier=task_params.service_tier,
            artifact_task_id=str(task_uuid),
            original_filename=task_params.original_filename,
            provider=provider,
            source_lang=task_params.source_lang,
            cancel_check=lambda: is_cancel_requested(file_uid),
        )

        logger.info(f"Starting transcription. Task ID : {task_uuid}")
        transcription_result = task_manager.transcribe_audio(local_path)

        if not transcription_result.success:
            # 失敗結果的 text 是錯誤描述而非 LRC，直接走 FAILED 路徑，
            # 避免被標成 COMPLETED 並產出空字幕
            raise ValueError(f"轉錄失敗: {transcription_result.text}")

        final_lrc_text = transcription_result.text
        input_tokens = transcription_result.input_tokens
        output_tokens = transcription_result.output_tokens
        total_tokens = transcription_result.total_tokens
        logger.info(
            f"Transcription complete. Task ID: {task_uuid}. Tokens used: {total_tokens:,}")

        update_status("正在轉換字幕格式...")
        transcripts_model = convert_from_lrc(final_lrc_text)
        final_transcripts = transcripts_model.model_dump() if transcripts_model else {}

        update_status("正在計算費用...")
        items = []
        if total_tokens > 0:
            items.append(CalculationItem(
                task_name="total_transcription",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                content_type="audio",
            ))

        processing_time_seconds = time.time() - start_time
        calculator = CalculatorService()
        metrics_response = calculator.calculate_metrics(
            items=items,
            model=task_params.model,
            processing_time_seconds=processing_time_seconds,
            audio_duration_seconds=audio_duration_seconds
        )

        # 若實際以 Flex 層級完成（非 fallback 回 Standard），套用 50% 費用折扣
        flex_applied = transcription_result.service_tier_used == "flex"
        if flex_applied:
            final_cost = metrics_response.cost * FLEX_COST_DISCOUNT
            final_input_cost = metrics_response.input_cost * FLEX_COST_DISCOUNT
            final_output_cost = metrics_response.output_cost * FLEX_COST_DISCOUNT
            logger.info(
                f"Flex 層級生效，費用套用 {int(FLEX_COST_DISCOUNT * 100)}% 折扣")
        else:
            final_cost = metrics_response.cost
            final_input_cost = metrics_response.input_cost
            final_output_cost = metrics_response.output_cost

        logger.info(
            f"Metrics calculated. Task ID: {task_uuid}. Cost: ${final_cost:.6f}")

        update_data = {
            "status": "COMPLETED",
            "audio_duration_seconds": metrics_response.audio_duration_seconds,
            "processing_time_seconds": metrics_response.processing_time_seconds,
            "total_tokens": metrics_response.total_tokens,
            "cost": final_cost,
            "completed_at": datetime.now(),
            "lrc_content": final_lrc_text or None,
            "service_tier_used": transcription_result.service_tier_used or "standard",
        }
        if not log_repo.update_log(db, task_uuid, update_data):
            logger.warning(
                f"無法更新 transcription_log（可能 task_uuid 不符）: {task_uuid}")
        else:
            logger.info(f"Task status updated to COMPLETED. Task ID: {task_uuid}")

        final_response = TranscriptionResponse(
            task_uuid=task_uuid,
            transcripts=final_transcripts,
            tokens_used=metrics_response.total_tokens,
            cost=final_cost,
            input_cost=final_input_cost,
            output_cost=final_output_cost,
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

        return {"raw_lrc_text": final_lrc_text}

    except TranscriptionCancelledError:
        # 使用者取消：標記 CANCELLED（非 FAILED），不重試也不往上拋
        processing_time_seconds = time.time() - start_time
        logger.info(f"Transcription task {task_uuid} cancelled by user.")
        log_repo.update_log(db, task_uuid, {
            "status": "CANCELLED",
            "error_message": "使用者取消任務",
            "processing_time_seconds": processing_time_seconds,
            "completed_at": datetime.now(),
        })
        update_status("任務已取消", status_code="CANCELLED")
        return {"cancelled": True}
    except GeminiTransientError as e:
        # 暫時性錯誤：交給 Celery autoretry 處理，不寫入 FAILED log
        logger.warning(
            f"Transcription task {task_uuid} hit transient Gemini error, will retry: {e}"
        )
        update_status(f"暫時性錯誤，將重試: {e}", status_code="PROCESSING")
        raise
    except Exception as e:
        processing_time_seconds = time.time() - start_time
        error_message = traceback.format_exc()
        logger.error(
            f"Transcription task failed for log ID: {task_uuid}\n{error_message}")

        # session 可能因失敗的 commit 處於 pending rollback 狀態，先復原才能寫 FAILED
        db.rollback()
        failure_update_data = {
            "status": "FAILED",
            "error_message": str(e),
            "processing_time_seconds": processing_time_seconds
        }
        log_repo.update_log(db, task_uuid, failure_update_data)

        update_status(f"任務失敗: {e}", status_code="FAILED")
        raise e
    finally:
        # 任務結束後旗標已無作用，清掉以免影響同一檔案的重跑
        clear_cancel_flag(file_uid)

        if task_manager:
            task_manager.cleanup()
            logger.info(
                f"Temporary files cleaned up for task {task_uuid}.")

        db.close()
