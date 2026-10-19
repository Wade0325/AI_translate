"""本機轉接器：在使用者自己的 NVIDIA 顯卡上轉錄。

推論本體在 :mod:`app.provider.local.asr`，第一次轉錄時才 import：Docker 模式的
容器 worker 與 API 不裝 transformers／CUDA，也要能列出模型能力與驗證模型。

registry 認得的是 :data:`local_provider`：列模型能力不建立轉接器、不碰顯卡。
轉接器（:class:`LocalProvider`）只在真的要轉錄的行程建立（Docker 模式的 GPU worker、
免安裝模式），單次長度在那裡才依顯卡容量收斂。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Dict

from app.core.config import get_settings
from app.provider.base import LOCAL_QUEUE, ModelCapabilities, ProgressAndCancel, TranscribeRequest
from app.provider.local import weights
from app.services.transcription.models import TranscriptionTaskResult


def _single_pass_limit_seconds(model: str) -> float:
    """不查顯卡就知道的單次長度上限。MOSS 整檔一次分離說話者，編號才會一致，上限取
    設定值與上下文上限；VibeVoice 是依全域切段設定設計的。"""
    if weights.is_moss_model(model):
        from app.provider.local import moss
        return moss.single_pass_limit_seconds()
    return get_settings().long_audio_split_threshold_seconds


def _single_pass_seconds_on_this_gpu(model: str) -> float:
    """這張顯卡上的單次長度：MOSS 再依顯存收斂（會 import torch）。"""
    if weights.is_moss_model(model):
        from app.provider.local import moss
        return moss.max_single_pass_seconds()
    return _single_pass_limit_seconds(model)


def _capabilities(model: str) -> ModelCapabilities:
    return ModelCapabilities(
        single_pass_seconds=_single_pass_limit_seconds(model),
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


def _declared_capabilities() -> Dict[str, ModelCapabilities]:
    """每個本機模型不碰顯卡就知道的模型能力；單次長度是上限。"""
    return {model: _capabilities(model) for model in weights.MODEL_REPOS}


class LocalProvider:
    def __init__(self, model: str, api_key: str = ""):
        # 先確認 GPU 與所選模型的權重齊備，缺什麼直接以明確訊息失敗（ValueError），
        # 不在任務裡默默下載好幾 GB
        weights.ensure_local_ready(model)

    def capabilities(self) -> Dict[str, ModelCapabilities]:
        """這台機器上的模型能力：分段轉錄照這裡的單次長度切，MOSS 依顯存收斂過。"""
        return {model: replace(capabilities,
                               single_pass_seconds=_single_pass_seconds_on_this_gpu(model))
                for model, capabilities in _declared_capabilities().items()}

    def transcribe(
        self, audio_path: Path, request: TranscribeRequest, progress: ProgressAndCancel,
    ) -> TranscriptionTaskResult:
        # 延遲 import：見模組說明
        from app.provider.local.asr import transcribe_with_local_models

        return TranscriptionTaskResult.model_validate(transcribe_with_local_models(
            audio_path, request.source_lang, progress, model=request.model))

    def release(self) -> None:
        # 模型與暫存 wav 在每次轉錄結束時就已釋放
        pass


class _LocalProviderFactory:
    """registry 認得的本機供應商：列模型能力不建立轉接器、不碰顯卡（API 行程與模型能力
    端點都會列，Docker 模式的 API 容器沒有顯卡）；呼叫它建立一個任務專用的轉接器。"""

    @staticmethod
    def capabilities() -> Dict[str, ModelCapabilities]:
        return _declared_capabilities()

    def __call__(self, model: str, api_key: str = "") -> LocalProvider:
        return LocalProvider(model, api_key)


local_provider = _LocalProviderFactory()
