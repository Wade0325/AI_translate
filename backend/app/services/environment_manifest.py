"""轉錄環境的描述：同一段音檔換了環境可能轉出不同的結果，比較轉錄結果之前要先知道環境一不一樣。

記下主要套件的版本、這次看得到的顯卡與 NVIDIA 驅動、本機模型權重釘住的 revision，以及去靜音與
分段轉錄的設定。評測指令（``python -m tools.eval transcribe``，#37）把它寫進 manifest，``summary``
拿基準與 PR 兩邊的 manifest 逐項比對（#276）；之後要記錄轉錄環境的地方也用這裡，不另外寫一份。

只讀已安裝套件的中繼資料與設定，不建立供應商轉接器、不載入模型；有 torch 時才問顯卡與驅動（nvidia-smi）。
"""

from __future__ import annotations

import json
import os
from importlib import metadata
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.provider.registry import model_capabilities

PACKAGES = ("torch", "transformers", "moss-transcribe-diarize")
"""轉錄結果會隨版本改變的套件（以安裝時的名稱）。"""


def describe(provider: str, model: str) -> Dict[str, Any]:
    """這個供應商的這個模型在目前環境裡的描述，可以直接寫成 JSON。

    Raises:
        UnsupportedModelError: 供應商不存在，或模型不屬於它。
    """
    capabilities = model_capabilities(provider, model)
    settings = get_settings()
    return {
        "packages": {name: package(name) for name in PACKAGES},
        "gpu": gpu(),
        "model_revisions": model_revisions(model),
        "settings": {
            "remove_silence": capabilities.remove_silence,
            "speech_ratio_skip_threshold": settings.vad_speech_ratio_skip_threshold,
            # 模型能力列出的上限；本機轉接器實際轉錄時可能依顯卡容量切得更短
            "single_pass_seconds": capabilities.single_pass_seconds,
            "long_audio_split_threshold_seconds": settings.long_audio_split_threshold_seconds,
            "local_moss_single_pass_max_seconds": settings.local_moss_single_pass_max_seconds,
            "split_retry_min_seconds": settings.transcription_max_duration_seconds,
        },
    }


def package(name: str) -> Dict[str, Optional[str]]:
    """已安裝套件的版本，沒安裝時是 None；``source`` 是從網址（例如固定 commit 的壓縮檔）安裝時的
    網址（pip 記在 direct_url.json，PEP 610），從 PyPI 安裝時是 None。"""
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return {"version": None, "source": None}
    source = None
    direct_url = distribution.read_text("direct_url.json")
    if direct_url:
        try:
            source = json.loads(direct_url).get("url")
        except ValueError:
            pass
    return {"version": distribution.version, "source": source}


def gpu() -> Optional[Dict[str, Any]]:
    """這次看得到的第一張顯卡（本機轉錄只用它）：名稱、顯存（GB）、NVIDIA 驅動的版本與
    ``CUDA_VISIBLE_DEVICES``；沒有 torch 或沒有 CUDA 時是 None。

    驅動是 nvidia-smi 回報的版本（例如 ``576.02``），問不到時是 None。換了驅動，同一段音檔可能轉出
    不同的結果（docs/adr/0009），所以和顯卡一起記。"""
    try:
        import torch
    except ImportError:
        return None
    try:
        # is True：測試環境裡 torch 可能是 mock，回傳的不是 bool
        if torch.cuda.is_available() is not True:
            return None
        card = torch.cuda.get_device_properties(0)
        name, vram_gb = str(card.name), round(card.total_memory / 1024 ** 3, 1)
    except Exception:
        return None
    from app.provider.local import weights

    return {"name": name, "vram_gb": vram_gb, "driver": weights.nvidia_driver_version(),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES")}


def model_revisions(model: str) -> Dict[str, str]:
    """模型權重釘住的 revision（Hugging Face 的 repo → commit）；只有本機的模型有（權重的清單
    在 :mod:`app.provider.local.weights`），雲端模型的版本由供應商決定，這裡記不到。"""
    from app.provider.local import weights

    # 不經 repos_for_model：它把不認得的模型當成預設模型
    return {repo: weights.REPO_REVISIONS[repo] for repo in weights.MODEL_REPOS.get(model, ())}
