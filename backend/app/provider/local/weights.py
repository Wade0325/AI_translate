"""Local ASR 模型權重的單一事實來源：repo 清單、就緒檢查、CUDA 偵測。

asr.py（推論）與 api/local_models.py（下載管理）都從此模組取常數與檢查，
避免兩處清單漂移。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, TypeVar

from app.core.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
T = TypeVar("T")

os.environ.setdefault("HF_HOME", get_settings().hf_home)

MOSS_MODEL_ID = "OpenMOSS-Team/MOSS-Transcribe-Diarize"
DIARIZATION_MODEL_ID = "microsoft/VibeVoice-ASR-HF"
ASR_MODEL_ID = "Qwen/Qwen3-ASR-1.7B-hf"
ALIGNER_MODEL_ID = "Qwen/Qwen3-ForcedAligner-0.6B-hf"

# 全部釘住 revision：上游更新不會在使用者端悄悄換掉行為，首次核對也不會在任務中途
# 觸發大型下載。MOSS 要與固定 commit 的 moss-transcribe-diarize 套件對齊；其餘釘在
# 2026-10 實測使用中的版本
REPO_REVISIONS = {
    MOSS_MODEL_ID: "704aa4a9c304e8520be88901e0d1960158ef5b15",
    ALIGNER_MODEL_ID: "c07281df297b9905d24a508279258cccf987a064",
    ASR_MODEL_ID: "bcd2b5b7f32b480ab5790554cfa8347f246a14f3",
    DIARIZATION_MODEL_ID: "f22241c2062b3b25272bf117397e03d73381037a",
}

# 前端 Local provider 的模型選項（frontend/src/constants/modelConfig.js）→ 需要的權重
MOSS_ALIGN = "moss-align"
MOSS_QWEN = "moss-qwen3-asr"
VIBEVOICE_QWEN = "vibevoice-qwen3-asr"
DEFAULT_LOCAL_MODEL = MOSS_ALIGN

MODEL_REPOS = {
    MOSS_ALIGN: (MOSS_MODEL_ID, ALIGNER_MODEL_ID),
    MOSS_QWEN: (MOSS_MODEL_ID, ASR_MODEL_ID, ALIGNER_MODEL_ID),
    VIBEVOICE_QWEN: (DIARIZATION_MODEL_ID, ASR_MODEL_ID, ALIGNER_MODEL_ID),
}

# 預設模型所需：Settings 頁「下載」預設只抓這些
REQUIRED_REPOS = MODEL_REPOS[DEFAULT_LOCAL_MODEL]
# 所有 Local 模型用得到的 repo（去重、保持順序），供狀態頁列出選用權重
ALL_REPOS = tuple(dict.fromkeys(r for repos in MODEL_REPOS.values() for r in repos))

# 各 repo 的約略大小（GB）：下載前的磁碟空間檢查與 Settings 頁按鈕標示
REPO_SIZE_GB = {  # 各釘住版本快照的實測大小
    MOSS_MODEL_ID: 1.8,
    ALIGNER_MODEL_ID: 1.9,
    ASR_MODEL_ID: 4.1,
    DIARIZATION_MODEL_ID: 16.7,
}


def size_gb(repos) -> float:
    return round(sum(REPO_SIZE_GB.get(r, 2.0) for r in repos), 1)


def normalize_model(model: str | None) -> str:
    """未知或未指定的模型名稱一律視為預設模型——分流、切段門檻、權重檢查都經過這裡。"""
    return model if model in MODEL_REPOS else DEFAULT_LOCAL_MODEL


def is_moss_model(model: str | None) -> bool:
    return normalize_model(model) in (MOSS_ALIGN, MOSS_QWEN)


def repos_for_model(model: str | None) -> tuple[str, ...]:
    return MODEL_REPOS[normalize_model(model)]


def _weights_complete(folder: Path) -> bool:
    """快照內 config 與每個權重分片是否都在。

    huggingface_hub 的離線檢查只在快取過檔案清單時才有效（本程式一律經
    snapshot_download 下載，會先寫入清單）；舊版程式以 from_pretrained 逐檔下載中斷
    留下的快照沒有清單，至少確認最大、最可能缺的權重檔齊全。
    """
    if not (folder / "config.json").is_file():
        return False
    index = folder / "model.safetensors.index.json"
    if index.is_file():
        try:
            shards = set(json.loads(index.read_text(encoding="utf-8"))["weight_map"].values())
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return bool(shards) and all((folder / name).is_file() for name in shards)
    return any(folder.glob("*.safetensors"))


def _local_snapshot(repo_id: str) -> str | None:
    """本機快取中完整快照的路徑；沒有或不完整時回傳 None（不觸發網路請求）。"""
    from huggingface_hub import snapshot_download
    try:
        path = snapshot_download(repo_id, revision=REPO_REVISIONS.get(repo_id),
                                 local_files_only=True)
    except Exception:
        return None
    return path if _weights_complete(Path(path)) else None


def repo_is_ready(repo_id: str) -> bool:
    """權重是否已完整存在本機快取（不觸發任何網路請求）。"""
    return _local_snapshot(repo_id) is not None


def download_snapshot(repo_id: str, **kwargs) -> str:
    """線上 snapshot_download 釘住的版本：補齊缺檔、已有的跳過，並先快取檔案清單，
    之後就算中斷，離線檢查也認得出不完整。"""
    from huggingface_hub import snapshot_download
    return snapshot_download(repo_id, revision=REPO_REVISIONS.get(repo_id), **kwargs)


def resolve_repo(repo_id: str) -> str:
    """供 from_pretrained 使用的本機快照路徑，缺檔時先補齊。

    以 repo id 載入時 transformers 每次都會向 Hub 探查設定檔（實測曾卡 90 秒以上），
    逐檔下載中斷還會留下半套快照，所以一律改給快照路徑：本機完整就完全離線；
    否則整包下載釘住的版本。下載失敗直接拋出——不退回 from_pretrained(repo_id)，
    那會載入未釘住的最新版。
    """
    local = _local_snapshot(repo_id)
    if local:
        return local
    logger.info(f"本機沒有完整的 {repo_id} 權重，開始下載")
    return download_snapshot(repo_id)


def load_pretrained(repo_id: str, loader: Callable[[str], T]) -> T:
    """resolve_repo + loader(路徑)。本機快照缺小檔（tokenizer、處理器設定等，
    權重檢查看不到）導致載入失敗時，向 Hub 補齊缺檔後重試一次。

    補不了的情況（離線、檔案存在但損毀、與缺檔無關的錯誤）一律拋出原本的錯誤，
    不讓網路錯誤蓋掉真正的原因。
    """
    path = resolve_repo(repo_id)
    try:
        return loader(path)
    except (OSError, ValueError) as first:
        logger.warning(f"{repo_id} 載入失敗，嘗試向 Hub 補齊缺檔後重試一次: {first}")
        try:
            repaired = download_snapshot(repo_id)
        except Exception as e:
            logger.warning(f"{repo_id} 補齊失敗: {e}")
            raise first from e
        return loader(repaired)


def notice_if_missing(repo_id: str, label: str, status_callback=None) -> None:
    """首次使用時權重下載在任務內進行（無法取消），先告知使用者不是卡住。"""
    if status_callback and not repo_is_ready(repo_id):
        status_callback(f"本地模型：首次使用，下載 {label} 權重（約 {size_gb([repo_id])} GB）...")


def missing_repos(model: str | None = None) -> list[str]:
    return [r for r in repos_for_model(model) if not repo_is_ready(r)]


def cuda_status() -> tuple[bool, str | None]:
    """回傳 (CUDA 可用, GPU 名稱)；torch 缺失或無 GPU 時 (False, None)。"""
    try:
        import torch
        if torch.cuda.is_available():
            return True, torch.cuda.get_device_name(0)
    except Exception:
        pass
    return False, None


def ensure_local_ready(model: str | None = None) -> None:
    """本機轉錄前的前置檢查（由本機轉接器呼叫）；不符合直接拋明確錯誤。"""
    cuda_ok, _ = cuda_status()
    if not cuda_ok:
        raise ValueError("Local 轉錄需要 NVIDIA GPU，未偵測到可用的 CUDA 裝置")
    missing = missing_repos(model)
    if missing:
        raise ValueError(
            "Local 模型權重尚未下載完成，請至 Settings 頁面下載（缺少: "
            + ", ".join(missing) + "）")
