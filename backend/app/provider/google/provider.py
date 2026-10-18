"""Gemini 轉接器：上傳音檔、轉錄、任務結束時刪除遠端檔。

Gemini 的細節（Flex 重試、service tier 判讀）仍在 :mod:`app.provider.google.gemini`；
這裡只把它包在供應商接縫後面。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app.core.config import get_settings
from app.exceptions import ProviderNotReadyError
from app.provider.base import DEFAULT_QUEUE, ModelCapabilities, TranscribeRequest
from app.provider.google.gemini import (
    GeminiClient,
    cleanup_gemini_file,
    transcribe_with_uploaded_file,
    upload_file_to_gemini,
)
from app.services.transcription.models import TranscriptionTaskResult
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# 與前端 frontend/src/constants/modelConfig.js 的 Google 選項一致
MODELS = (
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
)


def _capabilities() -> ModelCapabilities:
    return ModelCapabilities(
        single_pass_seconds=get_settings().long_audio_split_threshold_seconds,
        queue=DEFAULT_QUEUE,
        # 容器 worker 是 gevent pool，支援 terminate
        can_terminate=True,
        split_retry_on_failure=True,
        accepts_prompt=True,
        accepts_user_text=True,
        supports_batch=True,
        pricing="per_token",
        remove_silence=True,
    )


class GeminiProvider:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None
        self._uploaded: List = []

    def capabilities(self) -> Dict[str, ModelCapabilities]:
        return {model: _capabilities() for model in MODELS}

    def transcribe(self, audio_path: Path, request: TranscribeRequest) -> TranscriptionTaskResult:
        client = self._get_client()
        gemini_file = upload_file_to_gemini(audio_path, client, request.status_callback)
        self._uploaded.append(gemini_file)

        request.notify("AI模型處理中...")
        result = transcribe_with_uploaded_file(
            client, gemini_file, request.model, request.prompt,
            service_tier=request.service_tier,
        )
        return TranscriptionTaskResult(
            success=result["success"],
            text=result.get("text", ""),
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            total_tokens=result.get("total_tokens", 0),
            service_tier_used=result.get("service_tier_used"),
        )

    def release(self) -> None:
        for gemini_file in self._uploaded:
            try:
                cleanup_gemini_file(self._client, gemini_file)
            except Exception as e:
                logger.warning(f"清理 Gemini 檔案失敗: {e}")
        self._uploaded.clear()

    def _get_client(self):
        if self._client is None:
            client = GeminiClient(self._api_key).client
            if not client:
                raise ProviderNotReadyError(
                    "Failed to initialize Gemini Client. Check API key.")
            self._client = client
        return self._client
