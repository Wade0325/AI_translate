"""轉錄環境的描述：同一段音檔換了環境可能轉出不同的結果，比較轉錄結果之前要先知道環境一不一樣。

記下主要套件的版本、這次看得到的顯卡、本機模型權重釘住的 revision，以及去靜音與分段轉錄的設定。
評測指令（``python -m tools.eval transcribe``，#37）把它寫進 manifest；之後要記錄轉錄環境的地方
也用這裡，不另外寫一份。

只讀已安裝套件的中繼資料與設定，不建立供應商轉接器、不載入模型；有 torch 時才問顯卡。
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

LOCAL_PROVIDER = "local"


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
        "model_revisions": model_revisions(provider, model),
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
    """這次看得到的第一張顯卡（本機轉錄只用它）：名稱、顯存（GB）與 ``CUDA_VISIBLE_DEVICES``；
    沒有 torch 或沒有 CUDA 時是 None。"""
    try:
        import torch
    except ImportError:
        return None
    try:
        # is True：測試環境裡 torch 可能是 mock，回傳的不是 bool
        if torch.cuda.is_available() is not True:
            return None
        card = torch.cuda.get_device_properties(0)
        return {"name": str(card.name), "vram_gb": round(card.total_memory / 1024 ** 3, 1),
                "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES")}
    except Exception:
        return None


def model_revisions(provider: str, model: str) -> Dict[str, str]:
    """模型權重釘住的 revision（Hugging Face 的 repo → commit）；只有本機的模型有，雲端模型的
    版本由供應商決定，這裡記不到。"""
    if provider.lower() != LOCAL_PROVIDER:
        return {}
    from app.provider.local import weights

    return {repo: weights.REPO_REVISIONS[repo] for repo in weights.repos_for_model(model)}
