import torch
from typing import List, Optional, Tuple

from app.utils.logger import setup_logger
from .models import (
    VADProcessRequest,
    AudioSplitRequest,
    SpeechExtractionResult,
    AudioSplitResult
)
from .flows import extract_speech_segments, split_audio_on_silence

logger = setup_logger(__name__)

# 簡單的全域變數
_vad_model = None
_vad_utils = None
SAMPLING_RATE = 16000


class VADService:
    """
    VAD (Voice Activity Detection) 服務的統一對外接口
    負責模型管理、語音檢測、提取和分割等功能
    """

    def __init__(self):
        """
        初始化 VAD 服務，延遲載入模型
        """
        logger.info("初始化 VADService...")
        # 不在初始化時載入模型
        logger.info("VADService 初始化完成（模型將在首次使用時載入）")

    def _load_model_if_needed(self):
        """需要時才載入模型（最簡單版本）"""
        global _vad_model, _vad_utils

        if _vad_model is None:
            logger.info("正在載入 Silero VAD 模型...")
            try:
                _vad_model, _vad_utils = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    force_reload=False,
                    trust_repo=True
                )
                logger.info("VAD 模型載入成功")
            except Exception as e:
                logger.error(f"載入 VAD 模型失敗: {e}")
                raise

    def get_model_and_utils(self):
        """
        取得 VAD 模型和工具函數
        供 flows.py 使用
        """
        self._load_model_if_needed()
        return _vad_model, _vad_utils

    def create_speech_only_audio(
        self,
        audio_path: str,
        output_dir: str
    ) -> Tuple[Optional[str], Optional[List[dict]]]:
        """
        提取音訊中的語音部分，建立純語音檔案
        """
        logger.info(f"VADService: 開始提取語音 - {audio_path}")

        # 確保模型已載入
        self._load_model_if_needed()

        request = VADProcessRequest(
            audio_path=audio_path,
            output_dir=output_dir
        )

        result = extract_speech_segments(request, self)

        if result.success:
            segments = [{"start": seg.start, "end": seg.end}
                        for seg in result.segments]
            logger.info(f"VADService: 語音提取成功 - 片段數: {len(segments)}")
            return result.speech_only_path, segments
        else:
            logger.warning("VADService: 語音提取失敗")
            return None, None

    def split_audio_on_silence(
        self,
        audio_path: str,
        output_dir: str,
        min_silence_duration: float = 1.0
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """
        在靜音處分割音訊檔案為兩部分
        """
        logger.info(f"VADService: 開始分割音訊 - {audio_path}")

        # 確保模型已載入
        self._load_model_if_needed()

        request = AudioSplitRequest(
            audio_path=audio_path,
            output_dir=output_dir,
            min_silence_duration=min_silence_duration
        )

        result = split_audio_on_silence(request, self)

        if result.success:
            logger.info(f"VADService: 音訊分割成功 - 分割點: {result.split_point:.2f}秒")
            return result.part1_path, result.part2_path, result.split_point
        else:
            logger.warning(f"VADService: 音訊分割失敗 - {result.error_message}")
            return None, None, None

    def get_speech_statistics(self, audio_path: str) -> dict:
        """
        獲取音訊的語音統計資訊
        """
        # 確保模型已載入
        self._load_model_if_needed()

        request = VADProcessRequest(
            audio_path=audio_path,
            output_dir=""
        )

        result = extract_speech_segments(request, self)

        return {
            "total_duration": result.total_duration,
            "speech_duration": result.total_speech_duration,
            "speech_ratio": result.speech_ratio,
            "segment_count": len(result.segments),
            "segments": [{"start": seg.start, "end": seg.end} for seg in result.segments]
        }


# 簡單的全域實例
_vad_service_instance = None


def get_vad_service() -> VADService:
    """
    取得 VAD 服務實例（最簡單版本）
    """
    global _vad_service_instance

    if _vad_service_instance is None:
        logger.info("建立 VADService 實例")
        _vad_service_instance = VADService()
        logger.info("VAD 服務已準備就緒")

    return _vad_service_instance


def initialize_vad_service() -> Optional[VADService]:
    """
    在應用程式啟動時初始化 VAD 服務
    """
    try:
        service = get_vad_service()
        return service
    except Exception as e:
        logger.error(f"無法初始化 VAD 服務: {e}")
        return None
