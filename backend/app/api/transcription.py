from app.services.calculator.models import CalculationItem
from app.services.calculator.service import CalculatorService
from app.services.vad_process import VADService
from app.services.subtitle_converter import convert_to_all_formats, _parse_lrc
from app.db.repository.model_manager_repository import ModelSettingsRepository
from app.models.gemini import (
    upload_file_to_gemini,
    transcribe_with_uploaded_file,
    cleanup_gemini_file,
    GeminiClient,
    count_tokens_with_uploaded_file
)
import shutil
import json
import uuid
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import soundfile as sf
import yt_dlp
from pydantic import BaseModel, HttpUrl

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body
from google import genai

# 使用統一的 logger 設定
from app.utils.logger import setup_logger
logger = setup_logger(__name__)

# 導入新的服務和函式

# 建立一個新的 API 路由器
router = APIRouter()

# 定義暫存檔案的儲存目錄
TEMP_DIR = Path(__file__).resolve().parents[2] / "temp_uploads"
TEMP_DIR.mkdir(exist_ok=True)

# 建立 VAD 服務的單例
try:
    vad_service = VADService()
except Exception as e:
    logger.error(f"CRITICAL: VADService failed to initialize. Error: {e}")
    vad_service = None

# 支援的檔案類型
SUPPORTED_MIME_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp3",
    "audio/flac", "audio/opus", "audio/m4a", "audio/x-m4a", "audio/mp4",
    "audio/aac", "audio/webm", "video/mp4", "video/mpeg", "video/webm",
    "video/quicktime", "video/x-flv", "video/x-ms-wmv", "video/3gpp",
}

# --- Pydantic 模型 ---


class YouTubeTranscribeRequest(BaseModel):
    youtube_url: HttpUrl
    source_lang: str
    model: str
    enable_vad: bool = True  # 新增 VAD 開關


# --- 核心邏輯函式 ---

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


def _recursive_transcribe_task(
    local_path: Path, client: genai.Client, model_name: str, prompt: str,
    local_cleanup_list: list, gemini_cleanup_list: list
) -> dict:
    """遞歸地轉錄一個音訊檔案。如果失敗，則檢查長度，若大於3分鐘則嘗試VAD切割並遞歸。"""
    try:
        with sf.SoundFile(str(local_path)) as f:
            duration_seconds = f.frames / f.samplerate
    except Exception as e:
        logger.error(f"Error getting duration for {local_path.name}: {e}")
        return {"success": False, "text": f"[[無法讀取檔案 {local_path.name}]]", "total_tokens_used": 0}

    gemini_file = upload_file_to_gemini(local_path, client)
    gemini_cleanup_list.append(gemini_file)
    result = transcribe_with_uploaded_file(
        client, gemini_file, model_name, prompt)

    if result["success"] or duration_seconds < 180:
        if not result["success"]:
            logger.info(
                f"File {local_path.name} is shorter than 3 minutes, accepting failure without splitting.")
        return result
    elif not result["success"] and vad_service:
        logger.info(
            f"Transcription blocked. File > 3 mins. Attempting VAD fallback for {local_path.name}...")
        part1_path_str, part2_path_str, split_point = vad_service.split_audio_on_silence(
            audio_path=str(local_path), output_dir=str(TEMP_DIR)
        )

        if part1_path_str and part2_path_str and split_point is not None:
            part1_path, part2_path = Path(part1_path_str), Path(part2_path_str)
            local_cleanup_list.extend([part1_path, part2_path])
            res1 = _recursive_transcribe_task(
                part1_path, client, model_name, prompt, local_cleanup_list, gemini_cleanup_list)
            if res1["success"]:
                res2 = _recursive_transcribe_task(
                    part2_path, client, model_name, prompt, local_cleanup_list, gemini_cleanup_list)
                if res2["success"]:
                    lrc1 = res1.get("text", "")
                    lrc2_adjusted = _adjust_lrc_timestamps(
                        res2.get("text", ""), split_point)
                    return {
                        "success": True,
                        "text": lrc1 + "\n" + lrc2_adjusted,
                        "total_tokens_used": res1.get("total_tokens_used", 0) + res2.get("total_tokens_used", 0)
                    }
    return result


async def _process_file_for_transcription(
    local_path: Path, model: str, source_lang: str,
    segments_for_remapping: Optional[List[Dict[str, float]]] = None
):
    """
    核心轉錄邏輯，現在可選擇性地接收分段資訊以進行時間重對應。
    """
    start_time = time.time()
    logger.info(
        f"開始處理轉錄任務: 檔案={local_path.name}, 模型={model}, 語言={source_lang}")

    local_files_to_cleanup = [local_path]
    gemini_files_to_cleanup = []
    final_lrc_text = ""
    total_tokens_used = 0

    try:
        # 獲取音訊時長
        try:
            with sf.SoundFile(str(local_path)) as f:
                audio_duration_seconds = f.frames / f.samplerate
            logger.info(f"音訊時長: {audio_duration_seconds:.2f} 秒")
        except Exception as e:
            logger.warning(f"無法讀取音訊檔案時長 {local_path.name}。錯誤：{e}")
            audio_duration_seconds = 0.0

        repo = ModelSettingsRepository()
        gemini_config = repo.get_by_model_name(model)
        if not gemini_config or not gemini_config.api_keys_json:
            logger.error(f"在資料庫中找不到 '{model}' 的設定或 API 金鑰")
            raise HTTPException(
                status_code=404, detail=f"在資料庫中找不到 '{model}' 的設定或 API 金鑰。")

        api_keys = json.loads(gemini_config.api_keys_json)
        api_key = api_keys[0] if api_keys else None
        model_name = gemini_config.model_name
        prompt = gemini_config.prompt or """# Role
You are an expert audio transcription AI specializing in speaker diarization (identifying different speakers).
# Task
Transcribe the audio I provide into timestamped text, line by line. You must also identify which speaker uttered each line.
# Output Format
You must strictly adhere to the LRC format with speaker labels. Prepend each line with a label like "Speaker A:", "Speaker B:", etc., to differentiate the speakers.
Example Format:
[00:01.23] Speaker A: This is the first transcribed sentence.
[00:04.56] Speaker B: This is the second sentence, spoken by another person.
[00:08.79] Speaker A: Now the first speaker is talking again.
# Constraints
- **Do not** include any form of introduction, greeting, notes, explanations, or summaries.
- Your response must **only** be the complete LRC content with speaker labels.
- Start directly with the first line of the output."""

        if not all([api_key, model_name]):
            logger.error(f"'{model}' 的設定不完整，缺少 API 金鑰或模型名稱")
            raise HTTPException(
                status_code=404, detail=f"'{model}' 的設定不完整，缺少 API 金鑰或模型名稱。")

        logger.info(f"正在初始化 Gemini Client，模型: {model_name}")
        client = GeminiClient(api_key).client
        if not client:
            logger.error("無法初始化 Gemini Client")
            raise HTTPException(
                status_code=500, detail="無法初始化 Gemini Client，請檢查 API 金鑰。")

        logger.info("開始執行轉錄任務")
        final_result = _recursive_transcribe_task(
            local_path=local_path, client=client, model_name=model_name, prompt=prompt,
            local_cleanup_list=local_files_to_cleanup, gemini_cleanup_list=gemini_files_to_cleanup
        )

        raw_lrc_text = final_result.get("text", "")
        total_tokens_used = final_result.get("total_tokens_used", 0)
        logger.info(f"轉錄完成，使用 tokens: {total_tokens_used}")

        # *** 時間戳重對應的關鍵邏輯 ***
        if segments_for_remapping and raw_lrc_text:
            logger.info("開始重新對應時間戳")
            final_lrc_text = _remap_lrc_timestamps(
                raw_lrc_text, segments_for_remapping)
        else:
            final_lrc_text = raw_lrc_text

    except Exception as e:
        logger.error(f"轉錄過程中發生錯誤: {e}")
        raise e
    finally:
        if gemini_files_to_cleanup and api_key:
            cleanup_client = GeminiClient(api_key).client
            if cleanup_client:
                for gf in gemini_files_to_cleanup:
                    try:
                        cleanup_gemini_file(cleanup_client, gf)
                        logger.info(f"已清理 Gemini 檔案: {gf.name}")
                    except Exception as e:
                        logger.warning(f"清理 Gemini 檔案 {gf.name} 失敗。錯誤: {e}")
        for local_file in local_files_to_cleanup:
            if local_file.exists():
                local_file.unlink()
                logger.info(f"已清理本地暫存檔案: {local_file.name}")

    final_transcripts = convert_to_all_formats(final_lrc_text)

    # 建立計費項目
    items = []
    if total_tokens_used > 0:
        # 目前，我們將所有 token 視為一個整體項目。
        # 未來若 `_recursive_transcribe_task` 能返回細分，可在此處擴展。
        items.append(CalculationItem(
            task_name="total_transcription", tokens=total_tokens_used))

    # 計算處理時間
    processing_time_seconds = time.time() - start_time
    logger.info(f"轉錄任務總處理時間: {processing_time_seconds:.2f} 秒")

    # 使用新的 CalculatorService 計算所有指標
    calculator = CalculatorService()
    metrics_response = calculator.calculate_metrics(
        items=items,
        model_name=model,
        processing_time_seconds=processing_time_seconds,
        audio_duration_seconds=audio_duration_seconds
    )

    logger.info(f"轉錄任務完成，總費用: {metrics_response.cost:.6f}")

    return {
        "transcripts": final_transcripts,
        "tokens_used": metrics_response.total_tokens,
        "cost": metrics_response.cost,
        "model": model,
        "source_language": source_lang,
        "processing_time_seconds": metrics_response.processing_time_seconds,
        "audio_duration_seconds": metrics_response.audio_duration_seconds,
        "cost_breakdown": metrics_response.breakdown
    }

# --- API 端點 ---


@router.post("/transcribe", tags=["Transcription"])
async def transcribe_media(
    file: UploadFile = File(..., description="要轉錄的音訊或視訊檔案"),
    source_lang: str = Form(..., description="來源語言代碼 (例如：zh-TW)"),
    model: str = Form(..., description="使用的模型名稱"),
):
    """接收音訊或視訊檔案，進行轉錄。"""
    logger.info(
        f"接收到轉錄請求: FileName='{file.filename}', Lang='{source_lang}', Model='{model}'")

    if not file.filename:
        logger.error("轉錄請求失敗: 沒有提供檔案名稱")
        raise HTTPException(status_code=400, detail="沒有提供檔案名稱。")

    if file.content_type not in SUPPORTED_MIME_TYPES:
        logger.error(f"轉錄請求失敗: 不支援的檔案格式 {file.content_type}")
        raise HTTPException(
            status_code=400, detail=f"不支援的檔案格式: {file.content_type}。")

    save_path = TEMP_DIR / f"{uuid.uuid4()}{Path(file.filename).suffix}"
    logger.info(f"正在儲存上傳檔案至: {save_path}")

    try:
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"檔案成功儲存: {save_path}")
    except Exception as e:
        logger.error(f"無法儲存檔案: {e}")
        raise HTTPException(status_code=500, detail=f"無法儲存檔案: {e}")
    finally:
        await file.close()

    return await _process_file_for_transcription(save_path, model, source_lang)


@router.post("/youtube", tags=["Transcription"])
async def transcribe_youtube(request: YouTubeTranscribeRequest = Body(...)):
    """接收 YouTube 連結，下載音訊並進行轉錄。"""
    logger.info(
        f"接收到 YouTube 轉錄請求: URL='{request.youtube_url}', VAD: {'Enabled' if request.enable_vad else 'Disabled'}")

    # 下載原始音訊
    original_audio_path_base = TEMP_DIR / f"{uuid.uuid4()}"
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        'outtmpl': str(original_audio_path_base), 'quiet': True,
    }

    logger.info(f"開始下載 YouTube 音訊: {request.youtube_url}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([str(request.youtube_url)])
        logger.info("YouTube 音訊下載完成")
    except Exception as e:
        logger.error(f"下載 YouTube 音訊時出錯: {e}")
        raise HTTPException(status_code=500, detail=f"下載 YouTube 音訊時出錯: {e}")

    original_audio_path = original_audio_path_base.with_suffix('.mp3')
    if not original_audio_path.exists():
        logger.error("下載後的原始檔案不存在")
        raise HTTPException(status_code=500, detail="下載後的原始檔案不存在。")

    # 如果 VAD 啟用，則處理；否則直接轉錄原始檔
    if request.enable_vad and vad_service:
        logger.info("VAD 已啟用，正在建立純人聲檔案")
        # 建立純人聲檔案
        speech_only_path_str, segments = vad_service.create_speech_only_audio(
            audio_path=str(original_audio_path),
            output_dir=str(TEMP_DIR)
        )

        # 清理原始下載的檔案
        original_audio_path.unlink()
        logger.info("已清理原始下載檔案")

        if speech_only_path_str:
            logger.info(f"準備轉錄純人聲檔案: {speech_only_path_str}")
            # 轉錄純人聲檔案，並傳入分段資訊以供重對應
            return await _process_file_for_transcription(
                Path(speech_only_path_str), request.model, request.source_lang,
                segments_for_remapping=segments
            )
        else:
            logger.warning("VAD 未在音訊中偵測到任何人聲")
            # 如果 VAD 沒檢測到人聲，返回錯誤或空結果
            raise HTTPException(status_code=400, detail="VAD 未在音訊中偵測到任何人聲。")
    else:
        logger.info("VAD 未啟用或不可用，直接處理原始檔案")
        # VAD 未啟用或不可用，直接處理原始檔案
        return await _process_file_for_transcription(original_audio_path, request.model, request.source_lang)
