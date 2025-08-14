from pathlib import Path
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from app.utils.logger import setup_logger
from .models import TranscriptionRequest, TranscriptionResponse
from .flows import transcription_flow

logger = setup_logger(__name__)


class TranscriptionService:
    """
    轉錄服務的統一對外接口，負責處理來自前端的轉錄請求
    """

    def transcribe_file(
        self,
        db: Session,
        file_path: str,
        model: str,
        source_lang: str,
        original_filename: str,
        segments_for_remapping: Optional[List[Dict[str, float]]] = None
    ) -> TranscriptionResponse:
        """
        轉錄檔案的主要入口點

        Args:
            db: SQLAlchemy Session.
            file_path: 以上傳至server的音訊檔案路徑
            model: 該次轉錄使用的模型名稱
            source_lang: 來源語言代碼
            original_filename: 原始檔案名稱，用於日誌記錄
            segments_for_remapping: VAD 分段資訊（可選）

        Returns:
            包含轉錄結果、費用、時間等資訊的完整回應
        """
        logger.info(
            f"TranscriptionService 接收到轉錄請求: 檔案={Path(file_path).name}, 模型={model}")

        request = TranscriptionRequest(
            file_path=file_path,
            model=model,
            source_lang=source_lang,
            original_filename=original_filename,
            segments_for_remapping=segments_for_remapping
        )

        try:
            response = transcription_flow(db, request)
            logger.info(
                f"TranscriptionService 轉錄完成: 費用={response.cost:.6f}, tokens={response.tokens_used}")
            return response
        except Exception as e:
            logger.error(f"TranscriptionService 轉錄失敗: {e}")
            raise
