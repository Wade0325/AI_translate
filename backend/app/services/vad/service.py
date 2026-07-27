from typing import Optional, Tuple

from app.utils.logger import setup_logger
from .models import AudioSplitRequest
from .flows import split_audio_on_silence

logger = setup_logger(__name__)

_vad_model = None
_vad_utils = None


class VADService:
    """Silero VAD 模型的管理與靜音分割入口；模型於首次使用時才載入。"""

    def _load_model_if_needed(self):
        global _vad_model, _vad_utils

        if _vad_model is None:
            logger.info("正在載入 Silero VAD 模型...")
            try:
                # 以 pip 套件內建的模型檔載入（權重與 torch.hub 版相同），
                # 完全離線 — 不再於執行期從 GitHub 下載 snakers4/silero-vad repo
                from silero_vad import (
                    VADIterator,
                    collect_chunks,
                    get_speech_timestamps,
                    load_silero_vad,
                    read_audio,
                    save_audio,
                )
                _vad_model = load_silero_vad()
                # 維持與 torch.hub 版相同的 utils tuple 順序，呼叫端解包方式不變
                _vad_utils = (
                    get_speech_timestamps,
                    save_audio,
                    read_audio,
                    VADIterator,
                    collect_chunks,
                )
                logger.info("VAD 模型載入成功")
            except Exception as e:
                logger.error(f"載入 VAD 模型失敗: {e}")
                raise

    def get_model_and_utils(self):
        self._load_model_if_needed()
        return _vad_model, _vad_utils

    def split_audio_on_silence(
        self,
        audio_path: str,
        output_dir: str,
        min_silence_duration: float = 1.0
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """在靜音處將音訊分割為兩部分，回傳 (part1, part2, 分割點秒數)；失敗回傳 (None, None, None)。"""
        logger.info(f"VADService: 開始分割音訊 - {audio_path}")

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


_vad_service_instance = None


def get_vad_service() -> VADService:
    global _vad_service_instance

    if _vad_service_instance is None:
        _vad_service_instance = VADService()

    return _vad_service_instance


def initialize_vad_service() -> Optional[VADService]:
    """應用啟動時預熱：建立服務並主動載入模型，失敗回傳 None 改為延遲載入。"""
    try:
        service = get_vad_service()
        service._load_model_if_needed()
        return service
    except Exception as e:
        logger.error(f"無法初始化 VAD 服務: {e}")
        return None
