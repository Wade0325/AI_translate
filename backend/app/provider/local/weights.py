"""Local ASR 模型權重的單一事實來源：repo 清單、就緒檢查、顯卡偵測。

asr.py（推論）與 api/local_models.py（下載管理）都從此模組取常數與檢查，
避免兩處清單漂移。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
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

# 本機的模型（畫面照這裡的順序列出，第一個是預設；見 GET /providers）→ 需要的權重
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
# 所有本機模型用得到的 repo（去重、保持順序），供狀態頁列出選用權重
ALL_REPOS = tuple(dict.fromkeys(r for repos in MODEL_REPOS.values() for r in repos))

# 在主機下載權重的指令（app/provider/local/download_weights.py），從 backend 資料夾執行
DOWNLOAD_COMMAND = r".venv\Scripts\python.exe -m app.provider.local.download_weights"

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
        status_callback(f"本機模型：首次使用，下載 {label} 權重（約 {size_gb([repo_id])} GB）...")


def missing_repos(model: str | None = None) -> list[str]:
    return [r for r in repos_for_model(model) if not repo_is_ready(r)]


def download_targets(model: str | None) -> tuple[str, ...]:
    """要下載的權重：省略＝預設模型所需；``all``＝所有本機模型；或指定模型用到的。
    設定頁的權重卡與下載指令共用。"""
    if model is None:
        return REQUIRED_REPOS
    if model == "all":
        return ALL_REPOS
    if model in MODEL_REPOS:
        return MODEL_REPOS[model]
    raise ValueError(f"不支援的本機模型: {model}")


# 顯卡記憶體的門檻（ADR 0003：12 GB 以上，建議 16 GB）。低於最低需求只提示、不擋（#11 Q2）：
# 8–12 GB 沒有測過；8 GB 以下另外警告可能很慢
VRAM_MINIMUM_GB = 12
VRAM_UNVERIFIED_GB = 8


@dataclass(frozen=True)
class Gpu:
    """這個行程看得到的第一張顯卡（本機轉錄只用它）。"""
    name: str
    vram_gb: float
    """顯卡記憶體（GiB，取到小數一位）：標示 16 GB 的卡約 16.0，12 GB 的卡約 12.0。"""
    supported: bool
    """這版 torch 跑得動這張卡；它的架構不在 torch 支援的清單裡時是 False（#11 Q4）。"""


class LocalNotReady(ValueError):
    """本機現在不能轉錄；訊息可直接顯示給使用者。``reason`` 讓轉錄頁決定下一步（#11 Q1）：
    ``no_gpu``、``unsupported_gpu`` 是這台電腦跑不了，建議改用別的供應商；``missing_weights``
    到設定頁下載模型權重就能用。"""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def detect_gpu() -> Gpu | None:
    """這個行程看得到的第一張顯卡；沒有 torch、沒有可用的 CUDA 裝置時是 None。"""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        card = torch.cuda.get_device_properties(0)
        return Gpu(name=str(card.name), vram_gb=round(card.total_memory / 2**30, 1),
                   supported=arch_supported(torch.cuda.get_device_capability(0),
                                            torch.cuda.get_arch_list()))
    except Exception:
        return None


def arch_supported(capability: tuple[int, int], arch_list: list[str]) -> bool:
    """torch 帶的 CUDA 程式碼（``arch_list``，例如 ``sm_86``、``compute_120``）跑不跑得動這個
    運算能力（``capability``，例如 RTX 3060 是 (8, 6)）的顯卡。

    同一代（主版號相同）、次版號不高於它的 ``sm_XY`` 可以直接跑；版號不高於它的 ``compute_XY``
    （PTX）可以在較新的卡上即時編譯。免安裝版的 torch 2.8.0+cu128（Windows）列出 ``sm_61`` 到
    ``sm_120``、沒有 PTX：GTX 900 系列（Maxwell）以前的卡、比 ``sm_120`` 新一代的卡都對不上。
    各版 torch 的清單不同（Docker 模式用的是另一版），所以照清單判斷，不寫死型號。清單是空的時
    看不出來，當成跑得動，交給轉錄時的錯誤。
    """
    if not arch_list:
        return True
    major, minor = capability
    for arch in arch_list:
        kind, _, digits = arch.partition("_")
        if not digits.isdigit():
            continue  # sm_90a 之類只給特定一代的變體，同一代的 sm_90 也會在清單裡
        arch_major, arch_minor = divmod(int(digits), 10)
        if kind == "sm" and arch_major == major and arch_minor <= minor:
            return True
        if kind == "compute" and (arch_major, arch_minor) <= (major, minor):
            return True
    return False


def _unusable_gpu(gpu: Gpu | None) -> LocalNotReady:
    if gpu is None:
        return LocalNotReady("no_gpu", "這台電腦沒有可用的 NVIDIA 顯卡，本機轉錄不能用，可以改用 Gemini")
    # 不在清單裡的通常是太舊的卡，也可能是比這版 torch 新一代的卡，所以不說「太舊」
    return LocalNotReady("unsupported_gpu", f"目前的 PyTorch 不支援這張顯卡（{gpu.name}），"
                         "本機轉錄不能用，可以改用 Gemini")


def gpu_problem(gpu: Gpu | None) -> str | None:
    """這張顯卡（:func:`detect_gpu` 的結果）跑不了本機轉錄的原因；跑得了時是 None。"""
    return None if gpu is not None and gpu.supported else str(_unusable_gpu(gpu))


def vram_notice(vram_gb: float, single_pass_seconds: float) -> str | None:
    """顯卡記憶體低於最低需求時給使用者的提示，只提示、不擋（#11 Q2）；夠的時候是 None。

    ``single_pass_seconds`` 是這張顯卡上單次能轉錄的長度（0 是不分段）：記憶體越小切得越短，
    長音檔切成越多段，各段各自分離說話者，說話者編號越容易對不上（跨段對齊是 #93）。
    """
    nominal = round(vram_gb)  # 標示 12 GB 的卡回報約 11.99 GiB
    if nominal >= VRAM_MINIMUM_GB:
        return None
    chunks = (f"長音檔會切成約 {single_pass_seconds / 60:.0f} 分鐘一段，"
              if single_pass_seconds > 0 else "")
    if nominal >= VRAM_UNVERIFIED_GB:
        return (f"顯卡記憶體 {nominal} GB 沒有測過（建議 16 GB、至少 12 GB）。"
                f"{chunks}各段的說話者編號比較容易對不上")
    return (f"顯卡記憶體 {nominal} GB，低於 8 GB，沒有測過，可能很慢。"
            f"{chunks}各段的說話者編號容易對不上；多人或很長的音檔建議改用 Gemini")


def ensure_local_ready(model: str | None = None) -> Gpu:
    """本機轉錄前的前置檢查（由本機轉接器呼叫）；不符合直接拋 :class:`LocalNotReady`，
    符合時回傳要用的顯卡。顯卡記憶體不足不在這裡擋（#11 Q2）。"""
    gpu = detect_gpu()
    if gpu is None or not gpu.supported:
        raise _unusable_gpu(gpu)
    missing = missing_repos(model)
    if missing:
        raise LocalNotReady("missing_weights", _missing_weights_message(model, missing))
    return gpu


def _missing_weights_message(model: str | None, missing: list[str]) -> str:
    listed = ", ".join(missing)
    # 權重卡只在免安裝模式的設定頁（api/local_models.py 回報的 standalone）。Docker 模式在
    # 主機的 GPU worker 轉錄，權重也要下載到主機，改指向在主機執行的下載指令（#123）
    if get_settings().is_standalone:
        return f"本機模型權重尚未下載完成，請至 Settings 頁面下載（缺少: {listed}）"
    return (f"本機模型權重尚未下載完成（缺少: {listed}）。請在主機的 backend 資料夾執行 "
            f"{DOWNLOAD_COMMAND} {normalize_model(model)}")
