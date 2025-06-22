import shutil
import json
import uuid
import re
from pathlib import Path
from typing import List, Dict, Any
import soundfile as sf

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from google import genai

# 導入新的服務和函式
from app.models.gemini import (
    upload_file_to_gemini,
    transcribe_with_uploaded_file,
    cleanup_gemini_file,
    GeminiClient,
    count_tokens_with_uploaded_file
)
from app.db.repository.model_manager_repository import ModelSettingsRepository
from app.services.subtitle_converter import convert_to_all_formats
from app.services.vad_process import VADService

# 建立一個新的 API 路由器
router = APIRouter()

# 定義暫存檔案的儲存目錄
TEMP_DIR = Path(__file__).resolve().parents[2] / "temp_uploads"
TEMP_DIR.mkdir(exist_ok=True)

# 建立 VAD 服務的單例
try:
    vad_service = VADService()
except Exception as e:
    print(f"CRITICAL: VADService failed to initialize. Error: {e}")
    vad_service = None

# 支援的檔案類型（保持不變，因為 Gemini 同時支援音訊和影片）
SUPPORTED_MIME_TYPES = {
    # Audio
    "audio/wav", "audio/x-wav", "audio/wave",
    "audio/mpeg", "audio/mp3",
    "audio/flac",
    "audio/opus",
    "audio/m4a", "audio/x-m4a",
    "audio/mp4",
    "audio/aac",
    "audio/webm",
    # Video
    "video/mp4",
    "video/mpeg",
    "video/webm",
    "video/quicktime",
    "video/x-flv",
    "video/x-ms-wmv",
    "video/3gpp",
}


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
    local_path: Path,
    client: genai.Client,
    model_name: str,
    prompt: str,
    local_cleanup_list: list,
    gemini_cleanup_list: list
) -> dict:
    """
    遞歸地轉錄一個音訊檔案。如果失敗，則檢查長度，若大於3分鐘則嘗試VAD切割並遞歸。
    """
    try:
        f = sf.SoundFile(str(local_path))
        duration_seconds = f.frames / f.samplerate
    except Exception as e:
        print(f"Error getting duration for {local_path.name}: {e}")
        return {"success": False, "text": f"[[無法讀取檔案 {local_path.name}]]", "total_tokens_used": 0}

    # 上傳並轉錄當前片段
    gemini_file = upload_file_to_gemini(local_path, client)
    gemini_cleanup_list.append(gemini_file)
    result = transcribe_with_uploaded_file(
        client, gemini_file, model_name, prompt)

    # 如果成功，或檔案長度已小於3分鐘，則直接返回結果（不再嘗試切割）
    if result["success"] or duration_seconds < 180:
        if not result["success"]:
            print(
                f"File {local_path.name} is shorter than 3 minutes, accepting failure without splitting.")
        return result

    # 如果失敗，檔案長度仍大於3分鐘，且VAD可用，則嘗試切割和遞歸
    elif not result["success"] and vad_service:
        print(
            f"Transcription blocked. File > 3 mins. Attempting VAD fallback for {local_path.name}...")
        part1_path_str, part2_path_str, split_point = vad_service.split_audio_on_silence(
            audio_path=str(local_path), output_dir=TEMP_DIR
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
                    print("Recursive fallback successful. Merging results.")
                    lrc1 = res1.get("text", "")
                    lrc2_adjusted = _adjust_lrc_timestamps(
                        res2.get("text", ""), split_point)

                    return {
                        "success": True,
                        "text": lrc1 + "\n" + lrc2_adjusted,
                        "total_tokens_used": res1.get("total_tokens_used", 0) + res2.get("total_tokens_used", 0)
                    }

    # 如果所有備用方案都失敗，則返回原始的失敗結果
    return result


@router.post("/", tags=["Transcription"])
async def transcribe_media(
    file: UploadFile = File(..., description="要轉錄的音訊或視訊檔案"),
    source_lang: str = Form(..., description="來源語言代碼 (例如：zh-TW)"),
    model: str = Form(..., description="使用的模型名稱"),
):
    """
    接收音訊或視訊檔案，直接從資料庫讀取設定進行轉錄。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="沒有提供檔案名稱。")

    if file.content_type not in SUPPORTED_MIME_TYPES:
        raise HTTPException(
            status_code=400, detail=f"不支援的檔案格式: {file.content_type}。")

    # --- 讀取資料庫設定 ---
    try:
        repo = ModelSettingsRepository()
        # 使用前端傳來的 model 名稱來讀取設定
        gemini_config = repo.get_by_name(model)
        if not gemini_config or not gemini_config.api_keys_json:
            raise HTTPException(
                status_code=404, detail=f"在資料庫中找不到 '{model}' 的設定或 API 金鑰。請先在模型設定頁面設定。")

        api_keys = json.loads(gemini_config.api_keys_json)
        api_key = api_keys[0] if api_keys else None
        model_name = gemini_config.model_name
        prompt = gemini_config.prompt

        if not all([api_key, model_name, prompt]):
            raise HTTPException(
                status_code=404, detail=f"'{model}' 的設定不完整，缺少 API 金鑰、模型名稱或提示詞。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"從資料庫讀取設定時出錯: {e}")

    # --- 檔案處理與上傳 ---
    save_path = TEMP_DIR / f"{uuid.uuid4()}{Path(file.filename).suffix}"

    local_files_to_cleanup = [save_path]
    gemini_files_to_cleanup = []

    final_lrc_text = ""
    total_tokens_used = 0

    try:
        # 1. 儲存原始檔案
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. 上傳到 Gemini API（只上傳一次）
        client = GeminiClient(api_key).client
        if not client:
            raise HTTPException(
                status_code=500, detail="無法初始化 Gemini Client，請檢查 API 金鑰。")

        # --- 主流程簡化為單次呼叫 ---
        final_result = _recursive_transcribe_task(
            local_path=save_path,
            client=client,
            model_name=model_name,
            prompt=prompt,
            local_cleanup_list=local_files_to_cleanup,
            gemini_cleanup_list=gemini_files_to_cleanup
        )

        final_lrc_text = final_result.get("text", "")
        total_tokens_used = final_result.get("total_tokens_used", 0)

    finally:
        # 8. 清理本地暫存檔案
        await file.close()
        if gemini_files_to_cleanup and api_key:
            cleanup_client = GeminiClient(api_key).client
            if cleanup_client:
                for gf in gemini_files_to_cleanup:
                    try:
                        cleanup_gemini_file(cleanup_client, gf)
                    except Exception as e:
                        print(
                            f"Warning: Failed to cleanup Gemini file {gf.name}. Error: {e}")
        for local_file in local_files_to_cleanup:
            if local_file.exists():
                local_file.unlink()
                print(f"Cleaned up local temp file: {local_file.name}")

    # **統一的最終轉換**
    final_transcripts = convert_to_all_formats(final_lrc_text)
    cost = total_tokens_used * 0.00015
    return {
        "transcripts": final_transcripts,
        "tokens_used": total_tokens_used,
        "cost": cost,
        "model": model,
        "source_language": source_lang,
    }
