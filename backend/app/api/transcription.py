from app.services.vad.service import get_vad_service
from app.services.transcription.service import TranscriptionService
import shutil
import uuid
from pathlib import Path
import yt_dlp
from pydantic import BaseModel, HttpUrl

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body
from google import genai

# 使用統一的 logger 設定
from app.utils.logger import setup_logger
logger = setup_logger(__name__)

# 導入新的轉錄服務

# 建立一個新的 API 路由器
router = APIRouter()

# 定義暫存檔案的儲存目錄
TEMP_DIR = Path(__file__).resolve().parents[2] / "temp_uploads"
TEMP_DIR.mkdir(exist_ok=True)

# 建立服務實例
transcription_service = TranscriptionService()

# 建立 VAD 服務的單例（用於 YouTube 預處理）
try:
    vad_service = get_vad_service()
    logger.info("使用 VAD 服務單例實例")
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

    # 使用新的 TranscriptionService 進行轉錄
    try:
        response = transcription_service.transcribe_file(
            file_path=str(save_path),
            model=model,
            source_lang=source_lang
        )

        # 轉換為 API 回應格式
        return {
            "transcripts": response.transcripts,
            "tokens_used": response.tokens_used,
            "cost": response.cost,
            "model": response.model,
            "source_language": response.source_language,
            "processing_time_seconds": response.processing_time_seconds,
            "audio_duration_seconds": response.audio_duration_seconds,
            "cost_breakdown": response.cost_breakdown
        }
    finally:
        # 清理原始上傳檔案
        if save_path.exists():
            save_path.unlink()
            logger.info(f"已清理原始上傳檔案: {save_path}")


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

    try:
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
                response = transcription_service.transcribe_file(
                    file_path=speech_only_path_str,
                    model=request.model,
                    source_lang=request.source_lang,
                    segments_for_remapping=segments
                )

                # 清理純人聲檔案
                Path(speech_only_path_str).unlink()
                logger.info("已清理純人聲檔案")

                return {
                    "transcripts": response.transcripts,
                    "tokens_used": response.tokens_used,
                    "cost": response.cost,
                    "model": response.model,
                    "source_language": response.source_language,
                    "processing_time_seconds": response.processing_time_seconds,
                    "audio_duration_seconds": response.audio_duration_seconds,
                    "cost_breakdown": response.cost_breakdown
                }
            else:
                logger.warning("VAD 未在音訊中偵測到任何人聲")
                raise HTTPException(
                    status_code=400, detail="VAD 未在音訊中偵測到任何人聲。")
        else:
            logger.info("VAD 未啟用或不可用，直接處理原始檔案")
            # VAD 未啟用或不可用，直接處理原始檔案
            response = transcription_service.transcribe_file(
                file_path=str(original_audio_path),
                model=request.model,
                source_lang=request.source_lang
            )

            return {
                "transcripts": response.transcripts,
                "tokens_used": response.tokens_used,
                "cost": response.cost,
                "model": response.model,
                "source_language": response.source_language,
                "processing_time_seconds": response.processing_time_seconds,
                "audio_duration_seconds": response.audio_duration_seconds,
                "cost_breakdown": response.cost_breakdown
            }
    finally:
        # 確保清理檔案
        if original_audio_path.exists():
            original_audio_path.unlink()
            logger.info("已清理原始音訊檔案")
