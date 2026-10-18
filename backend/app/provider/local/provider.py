"""本機轉接器：在使用者自己的 NVIDIA 顯卡上轉錄。

推論本體在 :mod:`app.provider.local.asr`，第一次轉錄時才 import：Docker 模式的
容器 worker 與 API 不裝 transformers／CUDA，也要能列出模型能力與驗證模型。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from app.core.config import get_settings
from app.exceptions import ProviderNotReadyError
from app.provider.base import LOCAL_QUEUE, ModelCapabilities, TranscribeRequest
from app.provider.local import weights
from app.services.transcription.models import TranscriptionTaskResult


def _single_pass_seconds(model: str) -> float:
    """MOSS 依顯卡容量估算（整檔一次分離說話者編號才會一致）；
    VibeVoice 是依全域切段設定設計的。"""
    if weights.is_moss_model(model):
        from app.provider.local import moss
        return moss.max_single_pass_seconds()
    return get_settings().long_audio_split_threshold_seconds


def _capabilities(model: str) -> ModelCapabilities:
    return ModelCapabilities(
        single_pass_seconds=_single_pass_seconds(model),
        queue=LOCAL_QUEUE,
        # Docker 模式的 GPU worker 是 solo pool，送 terminate 會在 worker 端拋
        # NotImplementedError；執行中的任務靠取消旗標在數秒內自行停下
        can_terminate=False,
        # 各段說話者分離互相獨立，拼接後 [S0]/[S1] 會指向不同人
        split_retry_on_failure=False,
        accepts_prompt=False,
        accepts_user_text=False,
        supports_batch=False,
        pricing="free",
        remove_silence=True,
    )


class LocalProvider:
    def __init__(self):
        self._ready = False

    def capabilities(self) -> Dict[str, ModelCapabilities]:
        return {model: _capabilities(model) for model in weights.MODEL_REPOS}

    def transcribe(self, audio_path: Path, request: TranscribeRequest) -> TranscriptionTaskResult:
        self._ensure_ready(request.model)
        # 延遲 import：見模組說明
        from app.provider.local.asr import transcribe_with_local_models

        result = transcribe_with_local_models(
            audio_path, request.source_lang, request.status_callback,
            cancel_check=request.cancel_check, model=request.model)
        return TranscriptionTaskResult(
            success=result["success"],
            text=result.get("text", ""),
            service_tier_used=result.get("service_tier_used"),
            segments=result.get("segments") or [],
        )

    def release(self) -> None:
        # 模型與暫存 wav 在每次轉錄結束時就已釋放
        pass

    def _ensure_ready(self, model: str) -> None:
        """先確認 GPU 與所選模型的權重齊備，缺什麼直接以明確訊息失敗。"""
        if self._ready:
            return
        try:
            weights.ensure_local_ready(model)
        except ValueError as e:
            raise ProviderNotReadyError(str(e)) from e
        self._ready = True
