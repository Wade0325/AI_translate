import shutil
import json
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

# 導入新的函式
from app.models.gemini import (
    upload_file_to_gemini,
    count_tokens_with_uploaded_file,
    transcribe_with_uploaded_file,
    cleanup_gemini_file
)
from app.db.repository.model_manager_repository import ModelSettingsRepository
from app.services.subtitle_converter import convert_to_all_formats

# 建立一個新的 API 路由器
router = APIRouter()

# 定義暫存檔案的儲存目錄
TEMP_DIR = Path(__file__).resolve().parents[2] / "temp_uploads"
TEMP_DIR.mkdir(exist_ok=True)

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
    save_path = TEMP_DIR / Path(file.filename).name

    try:
        # 1. 儲存原始檔案
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. 上傳到 Gemini API（只上傳一次）
        client, gemini_file = upload_file_to_gemini(save_path, api_key)

        try:
            # 3. 計算並印出輸入 token
            try:
                input_tokens = count_tokens_with_uploaded_file(
                    client, gemini_file, model_name)
                print(f"--- Token 預估 ---")
                print(
                    f"轉錄前，檔案 '{save_path.name}' 需要的輸入 tokens: {input_tokens}")
                print(f"--------------------")
            except Exception as e:
                print(f"警告：無法計算輸入 token。錯誤: {e}")
                input_tokens = 0

            # 4. 執行轉錄
            transcription_result = transcribe_with_uploaded_file(
                client, gemini_file, model_name, prompt
            )

            lrc_text = transcription_result.get("text")
            total_tokens_used = transcription_result.get(
                "total_tokens_used", 0)

            # 5. 將 LRC 格式轉換為所有其他格式
            all_transcripts = convert_to_all_formats(lrc_text)

            # 6. 印出花費的 token
            print(f"--- Token 花費 ---")
            print(f"轉錄完成後，總共花費的 tokens: {total_tokens_used}")
            print(f"--------------------")

            # 假設一個簡單的計價模型 (例如: $0.00015 / token)
            cost = total_tokens_used * 0.00015

        finally:
            # 7. 清理 Gemini API 上的檔案
            cleanup_gemini_file(client, gemini_file)

    finally:
        # 8. 清理本地暫存檔案
        await file.close()
        if save_path.exists():
            save_path.unlink()
            print(f"已刪除本地暫存檔案: {save_path.name}")

    return {
        "transcripts": all_transcripts,
        "tokens_used": total_tokens_used,
        "cost": cost,
        "model": model,
        "source_language": source_lang,
    }
