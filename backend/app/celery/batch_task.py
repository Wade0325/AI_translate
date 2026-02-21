import time
import uuid
import traceback
from pathlib import Path
import json
import redis

from langdetect import detect, LangDetectException

from app.celery.celery import celery_app
from app.celery.models import BatchTranscriptionTaskParams
from app.database.session import SessionLocal
from app.provider.google.gemini import (
    GeminiClient,
    upload_file_to_gemini,
    cleanup_gemini_file,
    create_batch_transcription_job,
    poll_batch_job_status,
    get_batch_job_state_name,
    BATCH_COMPLETED_STATES,
)
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.repositories.batch_job_repository import BatchJobRepository
from app.services.calculator.service import CalculatorService
from app.services.calculator.models import CalculationItem
from app.services.converter.service import convert_from_lrc, _parse_lrc
from app.services.transcription.models import TranscriptionResponse
from app.services.translator.flows import _perform_translation
from app.utils.audio import get_audio_duration
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

redis_client = redis.from_url(celery_app.conf.broker_url)

BATCH_COST_DISCOUNT = 0.5


def _publish_batch_status(
    batch_id: str,
    task_uuid: str,
    status_text: str,
    status_code: str = "PROCESSING",
    result_data: dict = None,
    file_uid: str = None,
):
    """向 Redis 發布批次任務的狀態更新"""
    message = {
        "client_id": batch_id,
        "batch_id": batch_id,
        "task_uuid": task_uuid,
        "status_code": status_code,
        "status_text": status_text,
    }
    if file_uid:
        message["file_uid"] = file_uid
    if result_data:
        message["result"] = result_data

    try:
        redis_client.publish(
            "transcription_updates",
            json.dumps(message, default=str, ensure_ascii=False),
        )
    except Exception as e:
        logger.error(f"發布批次狀態更新至 Redis 時失敗: {e}")


def _cleanup_local_file(file_path: str):
    """清理本地暫存檔案"""
    try:
        path = Path(file_path)
        if path.exists() and "temp_uploads" in str(path):
            path.unlink()
            logger.info(f"已刪除暫存檔案: {path.name}")
    except Exception as e:
        logger.warning(f"刪除暫存檔案失敗: {e}")


def _process_single_result(
    inline_response,
    file_item,
    task_params,
    client,
    file_task_uuid: str,
    audio_duration: float,
    start_time: float,
    db,
    log_repo,
    update_fn,
):
    """處理批次中單一檔案的結果：轉換格式、翻譯、計算費用"""
    file_uid = file_item.file_uid

    if not inline_response.response:
        error_msg = str(getattr(inline_response, "error", "未知錯誤"))
        logger.error(f"檔案 {file_item.original_filename} 批次轉錄失敗: {error_msg}")
        update_fn(f"轉錄失敗: {error_msg}", status_code="FAILED", file_uid=file_uid)
        log_repo.update_log(db, file_task_uuid, {
            "status": "FAILED",
            "error_message": error_msg,
            "processing_time_seconds": time.time() - start_time,
        })
        return

    response = inline_response.response

    if not response.candidates:
        error_text = "轉錄失敗：Gemini 回應被阻擋"
        try:
            error_text = f"轉錄失敗：請求被 Gemini 以 '{response.prompt_feedback.block_reason}' 原因阻擋"
        except Exception:
            pass
        update_fn(error_text, status_code="FAILED", file_uid=file_uid)
        log_repo.update_log(db, file_task_uuid, {
            "status": "FAILED",
            "error_message": error_text,
            "processing_time_seconds": time.time() - start_time,
        })
        return

    raw_lrc_text = response.text
    input_tokens = response.usage_metadata.prompt_token_count or 0
    output_tokens = response.usage_metadata.candidates_token_count or 0
    total_tokens = response.usage_metadata.total_token_count or 0

    logger.info(
        f"檔案 {file_item.original_filename} 轉錄完成, "
        f"Tokens: input={input_tokens}, output={output_tokens}, total={total_tokens}"
    )

    final_lrc_text = raw_lrc_text

    # --- 翻譯 ---
    translation_input_tokens = 0
    translation_output_tokens = 0
    if task_params.target_lang and final_lrc_text:
        parsed_lines = _parse_lrc(final_lrc_text)
        if parsed_lines:
            full_text = "\n".join(line.text for line in parsed_lines)

            source_lang_to_check = task_params.source_lang
            if not source_lang_to_check:
                try:
                    source_lang_to_check = detect(full_text)
                except LangDetectException:
                    source_lang_to_check = None

            if (
                source_lang_to_check
                and source_lang_to_check.split("-")[0]
                != task_params.target_lang.split("-")[0]
            ):
                update_fn(
                    f"翻譯字幕中 ({file_item.original_filename})...",
                    file_uid=file_uid,
                )
                translation_prompt = (
                    f"Translate the text portions of the following LRC format content "
                    f"from {source_lang_to_check} to {task_params.target_lang}. "
                    "It is crucial that you DO NOT alter the timestamps (e.g., [00:01.23]). "
                    "Your response should be only the translated LRC content in the exact same format."
                )
                trans_result = _perform_translation(
                    client=client,
                    model=task_params.model,
                    prompt=translation_prompt,
                    text_to_translate=final_lrc_text,
                )
                if trans_result.success:
                    final_lrc_text = trans_result.translated_text
                    translation_input_tokens = trans_result.input_tokens
                    translation_output_tokens = trans_result.output_tokens
                    logger.info(f"檔案 {file_item.original_filename} 翻譯成功")
                else:
                    logger.warning(
                        f"檔案 {file_item.original_filename} 翻譯失敗，使用原始轉錄結果"
                    )

    # --- 格式轉換 ---
    transcripts_model = convert_from_lrc(final_lrc_text)
    final_transcripts = transcripts_model.model_dump() if transcripts_model else {}

    # --- 費用計算 (含 Batch 50% 折扣) ---
    processing_time = time.time() - start_time
    items = []
    if total_tokens > 0:
        items.append(
            CalculationItem(
                model=task_params.model,
                task_name="total_transcription",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )
    if translation_input_tokens > 0 or translation_output_tokens > 0:
        items.append(
            CalculationItem(
                model=task_params.model,
                task_name="total_translation",
                input_tokens=translation_input_tokens,
                output_tokens=translation_output_tokens,
            )
        )

    calculator = CalculatorService()
    metrics = calculator.calculate_metrics(
        items=items,
        model=task_params.model,
        processing_time_seconds=processing_time,
        audio_duration_seconds=audio_duration,
    )

    batch_cost = metrics.cost * BATCH_COST_DISCOUNT
    batch_input_cost = metrics.input_cost * BATCH_COST_DISCOUNT
    batch_output_cost = metrics.output_cost * BATCH_COST_DISCOUNT

    # --- 更新資料庫 ---
    log_repo.update_log(db, file_task_uuid, {
        "status": "COMPLETED",
        "audio_duration_seconds": audio_duration,
        "processing_time_seconds": processing_time,
        "total_tokens": metrics.total_tokens,
        "cost": batch_cost,
    })

    # --- 回傳結果 ---
    file_response = TranscriptionResponse(
        task_uuid=file_task_uuid,
        transcripts=final_transcripts,
        tokens_used=metrics.total_tokens,
        cost=batch_cost,
        input_cost=batch_input_cost,
        output_cost=batch_output_cost,
        model=task_params.model,
        source_language=task_params.source_lang,
        processing_time_seconds=processing_time,
        audio_duration_seconds=audio_duration,
        cost_breakdown=metrics.breakdown,
    )

    result_dict = file_response.model_dump()
    if "task_uuid" in result_dict and hasattr(result_dict["task_uuid"], "hex"):
        result_dict["task_uuid"] = str(result_dict["task_uuid"])

    update_fn("任務完成", status_code="COMPLETED", result_data=result_dict, file_uid=file_uid)
    logger.info(f"檔案 {file_item.original_filename} 處理完成, 費用: ${batch_cost:.6f}")


@celery_app.task(bind=True)
def batch_transcribe_task(self, task_params_dict: dict):
    """
    使用 Gemini Batch API 進行批次轉錄的 Celery 任務。

    流程：
    1. 將所有音訊檔案上傳至 Gemini File API
    2. 建立 Batch API 任務 (inline requests)
    3. 輪詢直到任務完成
    4. 逐一處理每個檔案的結果 (格式轉換、翻譯、費用計算)
    5. 透過 Redis Pub/Sub 發布個別檔案與整體批次的狀態更新
    """
    task_params = BatchTranscriptionTaskParams.model_validate(task_params_dict)
    task_uuid = self.request.id
    batch_id = task_params.batch_id

    def update_status(
        status_text, status_code="PROCESSING", result_data=None, file_uid=None
    ):
        _publish_batch_status(
            batch_id, task_uuid, status_text, status_code, result_data, file_uid
        )

    db = SessionLocal()
    log_repo = TranscriptionLogRepository()
    batch_repo = BatchJobRepository()
    gemini_files = []
    client = None
    start_time = time.time()

    try:
        # --- 驗證 Provider ---
        if task_params.provider.lower() != "google":
            raise ValueError(
                f"Provider '{task_params.provider}' is not supported. Only 'google' is allowed."
            )

        # --- 初始化 Gemini Client ---
        client = GeminiClient(task_params.api_keys).client
        if not client:
            raise ValueError("Failed to initialize Gemini Client. Check API key.")

        prompt = task_params.prompt or "請將以下音檔轉錄成LRC格式的逐字稿。"
        total_files = len(task_params.files)
        update_status(f"正在初始化批次任務 ({total_files} 個檔案)...")

        # === 持久化節點 1：任務開始，建立 BatchJob 記錄 ===
        batch_repo.create_job(db, batch_id, json.dumps({
            "model": task_params.model,
            "provider": task_params.provider,
            "source_lang": task_params.source_lang,
            "target_lang": task_params.target_lang,
            "prompt": task_params.prompt,
        }))

        # --- 1. 取得音訊時長 & 建立資料庫日誌 ---
        file_durations = {}
        file_log_uuids = {}

        for file_item in task_params.files:
            local_path = Path(file_item.file_path)
            duration = get_audio_duration(local_path) or 0.0
            file_durations[file_item.file_uid] = duration

            file_task_uuid = str(uuid.uuid4())
            file_log_uuids[file_item.file_uid] = file_task_uuid
            log_repo.insert_log(db, {
                "status": "PROCESSING",
                "original_filename": file_item.original_filename,
                "model_used": task_params.model,
                "source_language": task_params.source_lang,
                "task_uuid": file_task_uuid,
            })

        # --- 2. 上傳所有檔案至 Gemini ---
        file_gemini_mapping = {}
        for i, file_item in enumerate(task_params.files):
            update_status(
                f"上傳檔案至AI模型 ({i + 1}/{total_files}): {file_item.original_filename}",
                file_uid=file_item.file_uid,
            )
            local_path = Path(file_item.file_path)

            try:
                gemini_file = upload_file_to_gemini(local_path, client)
                gemini_files.append(gemini_file)
                file_gemini_mapping[i] = (file_item, gemini_file)
            except Exception as e:
                logger.error(f"上傳檔案失敗 {file_item.original_filename}: {e}")
                update_status(
                    f"檔案上傳失敗: {e}",
                    status_code="FAILED",
                    file_uid=file_item.file_uid,
                )
                log_repo.update_log(db, file_log_uuids[file_item.file_uid], {
                    "status": "FAILED",
                    "error_message": f"檔案上傳失敗: {str(e)}",
                    "processing_time_seconds": time.time() - start_time,
                })

        if not file_gemini_mapping:
            update_status("所有檔案上傳失敗，批次任務終止", status_code="BATCH_COMPLETED")
            return

        # --- 3. 建立 Gemini Batch 任務 ---
        update_status(f"建立 Gemini 批次任務 ({len(file_gemini_mapping)} 個檔案)...")

        ordered_indices = sorted(file_gemini_mapping.keys())
        ordered_gemini_files = [
            file_gemini_mapping[i][1] for i in ordered_indices
        ]

        batch_job = create_batch_transcription_job(
            client=client,
            gemini_files=ordered_gemini_files,
            model=task_params.model,
            prompt=prompt,
            display_name=f"transcription-{batch_id[:8]}",
        )

        job_name = batch_job.name
        logger.info(f"Gemini 批次任務已建立: {job_name}")

        # === 持久化節點 2：Gemini batch job 建立後，存入 job_name 和檔案映射 ===
        file_mapping = {
            str(i): {"file_uid": file_gemini_mapping[i][0].file_uid,
                     "original_filename": file_gemini_mapping[i][0].original_filename}
            for i in ordered_indices
        }
        batch_repo.update_job(db, batch_id, {
            "gemini_job_name": job_name,
            "status": "POLLING",
            "file_mapping_json": json.dumps(file_mapping),
            "file_durations_json": json.dumps(file_durations),
            "file_log_uuids_json": json.dumps(file_log_uuids),
        })

        # --- 4. 輪詢等待完成 ---
        poll_count = 0
        poll_interval = 10

        while True:
            batch_job = poll_batch_job_status(client, job_name)
            state_name = get_batch_job_state_name(batch_job)

            if state_name in BATCH_COMPLETED_STATES:
                break

            poll_count += 1
            elapsed = int(time.time() - start_time)
            update_status(f"Gemini 批次處理中... (已等待 {elapsed} 秒, 狀態: {state_name})")

            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 60)

        state_name = get_batch_job_state_name(batch_job)
        logger.info(f"批次任務結束，狀態: {state_name}")

        # --- 處理非成功狀態 ---
        if state_name != "JOB_STATE_SUCCEEDED":
            error_msg = f"批次任務失敗，狀態: {state_name}"
            logger.error(error_msg)
            for file_item in task_params.files:
                fuid = file_item.file_uid
                if fuid in file_log_uuids:
                    update_status(error_msg, status_code="FAILED", file_uid=fuid)
                    log_repo.update_log(db, file_log_uuids[fuid], {
                        "status": "FAILED",
                        "error_message": error_msg,
                        "processing_time_seconds": time.time() - start_time,
                    })
            update_status(error_msg, status_code="BATCH_COMPLETED")
            return

        # --- 5. 逐一處理結果 ---
        update_status("批次任務完成，正在處理結果...")

        if batch_job.dest and batch_job.dest.inlined_responses:
            for response_idx, inline_response in enumerate(
                batch_job.dest.inlined_responses
            ):
                if response_idx >= len(ordered_indices):
                    break

                original_idx = ordered_indices[response_idx]
                file_item = file_gemini_mapping[original_idx][0]
                file_uid = file_item.file_uid
                file_task_uuid = file_log_uuids[file_uid]
                audio_duration = file_durations.get(file_uid, 0.0)

                update_status(
                    f"處理結果 ({response_idx + 1}/{len(ordered_indices)}): "
                    f"{file_item.original_filename}",
                    file_uid=file_uid,
                )

                try:
                    _process_single_result(
                        inline_response=inline_response,
                        file_item=file_item,
                        task_params=task_params,
                        client=client,
                        file_task_uuid=file_task_uuid,
                        audio_duration=audio_duration,
                        start_time=start_time,
                        db=db,
                        log_repo=log_repo,
                        update_fn=update_status,
                    )
                except Exception as e:
                    logger.error(
                        f"處理檔案 {file_item.original_filename} 結果時發生錯誤: {e}",
                        exc_info=True,
                    )
                    update_status(
                        f"處理結果失敗: {e}", status_code="FAILED", file_uid=file_uid
                    )
                    log_repo.update_log(db, file_task_uuid, {
                        "status": "FAILED",
                        "error_message": str(e),
                        "processing_time_seconds": time.time() - start_time,
                    })
        else:
            logger.warning("批次任務成功但沒有回傳結果")

        # --- 批次完成 ---
        # === 持久化節點 3a：任務完成 ===
        batch_repo.update_job(db, batch_id, {"status": "COMPLETED"})

        elapsed = time.time() - start_time
        update_status(
            f"批次任務全部完成 (耗時 {elapsed:.1f} 秒)", status_code="BATCH_COMPLETED"
        )
        logger.info(f"批次任務完成: {batch_id}, 耗時 {elapsed:.1f} 秒")

    except Exception as e:
        error_message = traceback.format_exc()
        logger.error(f"批次任務發生嚴重錯誤: {error_message}")

        # === 持久化節點 3b：任務失敗 ===
        batch_repo.update_job(db, batch_id, {"status": "FAILED"})

        for file_item in task_params.files:
            fuid = file_item.file_uid
            if fuid in file_log_uuids:
                log_repo.update_log(db, file_log_uuids[fuid], {
                    "status": "FAILED",
                    "error_message": str(e),
                    "processing_time_seconds": time.time() - start_time,
                })
                update_status(f"批次任務失敗: {e}", status_code="FAILED", file_uid=fuid)

        update_status(f"批次任務失敗: {e}", status_code="BATCH_COMPLETED")
        raise e

    finally:
        # 清理 Gemini 上的檔案
        if client:
            for gf in gemini_files:
                try:
                    cleanup_gemini_file(client, gf)
                except Exception as e:
                    logger.warning(f"清理 Gemini 檔案失敗: {e}")

        # 清理本地暫存檔案
        for file_item in task_params.files:
            _cleanup_local_file(file_item.file_path)

        db.close()
