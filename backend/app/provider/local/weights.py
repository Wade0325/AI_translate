"""Local ASR 模型權重的單一事實來源：repo 清單、就緒檢查、CUDA 偵測。

asr.py（推論）與 api/local_models.py（下載管理）都從此模組取常數與檢查，
避免兩處清單漂移。
"""

from __future__ import annotations

import os

from app.core.config import get_settings

os.environ.setdefault("HF_HOME", get_settings().hf_home)

DIARIZATION_MODEL_ID = "microsoft/VibeVoice-ASR-HF"
ASR_MODEL_ID = "Qwen/Qwen3-ASR-1.7B-hf"
ALIGNER_MODEL_ID = "Qwen/Qwen3-ForcedAligner-0.6B-hf"

REQUIRED_REPOS = (DIARIZATION_MODEL_ID, ASR_MODEL_ID, ALIGNER_MODEL_ID)


def repo_is_ready(repo_id: str) -> bool:
    """權重是否已完整存在本機快取（不觸發任何網路請求）。"""
    from huggingface_hub import snapshot_download
    try:
        snapshot_download(repo_id, local_files_only=True)
        return True
    except Exception:
        return False


def missing_repos() -> list[str]:
    return [r for r in REQUIRED_REPOS if not repo_is_ready(r)]


def cuda_status() -> tuple[bool, str | None]:
    """回傳 (CUDA 可用, GPU 名稱)；torch 缺失或無 GPU 時 (False, None)。"""
    try:
        import torch
        if torch.cuda.is_available():
            return True, torch.cuda.get_device_name(0)
    except Exception:
        pass
    return False, None


def ensure_local_ready() -> None:
    """standalone 模式派發 local 轉錄前的前置檢查；不符合直接拋明確錯誤。"""
    cuda_ok, _ = cuda_status()
    if not cuda_ok:
        raise ValueError("Local 轉錄需要 NVIDIA GPU，未偵測到可用的 CUDA 裝置")
    missing = missing_repos()
    if missing:
        raise ValueError(
            "Local 模型權重尚未下載完成，請至 Settings 頁面下載（缺少: "
            + ", ".join(missing) + "）")
