"""Local ASR 模型權重的單一事實來源：repo 清單、就緒檢查、顯卡偵測。

asr.py（推論）與 api/local_models.py（下載管理）都從此模組取常數與檢查，
避免兩處清單漂移。
"""

from __future__ import annotations

import json
import os
import platform
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, TypeVar

from app.core.config import get_settings
from app.utils.commands import command_output
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
    ``missing_weights`` 到設定頁下載模型權重就能用；其餘是這台電腦現在跑不了，訊息寫出原因與
    下一步，轉錄頁另外建議改用別的供應商：

    - ``no_gpu``、``driver_too_old``、``cuda_init_failed``、``torch_load_failed``：PyTorch 用不了
      顯卡，見 :class:`GpuUnavailable`（#262）
    - ``unsupported_gpu``：目前的 PyTorch 不支援這張顯卡的架構（#11 Q4）
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class GpuUnavailable:
    """PyTorch 用不了顯卡（:func:`detect_gpu`）：為什麼，以及下一步（#262）。

    ``reason`` 是 :class:`LocalNotReady` 的 ``reason`` 之一：

    - ``no_gpu``：沒有 NVIDIA 顯卡，或沒有裝 NVIDIA 驅動
    - ``driver_too_old``：驅動比 PyTorch 帶的 CUDA 舊
    - ``cuda_init_failed``：驅動在，CUDA 卻初始化失敗
    - ``torch_load_failed``：PyTorch 本身載入失敗，或裝到不支援 CUDA 的版本
    """
    reason: str
    problem: str
    """原因，例如「NVIDIA 顯卡驅動太舊（目前 472.12，需要 572.61 以上）」；診斷資訊也寫這句。"""
    next_step: str
    """下一步，例如「更新驅動後重新開啟 Mimiji，或改用 Gemini」。"""
    detail: str = ""
    """PyTorch 回報的原始錯誤（見 :func:`_error_summary`），寫進診斷資訊與日誌，不上轉錄頁。"""

    @property
    def message(self) -> str:
        """給使用者看的一句話：轉錄頁的就緒提示、設定頁的本機卡片與任務失敗的細節都用它。"""
        return f"{self.problem}，本機轉錄不能用，{self.next_step}"


NO_GPU = GpuUnavailable("no_gpu", "這台電腦沒有可用的 NVIDIA 顯卡", "可以改用 Gemini")
"""驅動在、卻看不到 NVIDIA 顯卡。"""

WINDOWS_DRIVER_FOR_CUDA = {"12.8": "572.61"}
"""PyTorch 帶的 CUDA（``torch.version.cuda``）→ 要裝的 Windows 顯卡驅動版本。

照 NVIDIA CUDA Toolkit Release Notes（https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/）的
Table 3「CUDA Toolkit and Corresponding Driver Versions」，2026-10-31 查：免安裝版的 torch
2.8.0+cu128（Windows）帶的 ``cudart64_12.dll`` 是 12.8.90，也就是 CUDA 12.8 Update 1，要 572.61 以上。

同一頁的 Table 2 寫 CUDA 12.x 在相容模式（minor version compatibility）下最低是 528.33。告訴
使用者的是 Table 3 的版本：NVIDIA 列給 CUDA 12.8 Update 1 的驅動，不必靠相容模式。
"""
DRIVER_TABLE_TORCH = "2.8.0+cu128"
"""上表是照這版 torch 查的。``requirements-standalone.txt`` 換了 torch，測試會要求重查。"""

VC_REDIST_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
"""Microsoft Visual C++ 可轉散發套件（x64）的固定連結，見
https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist 。"""

DETAIL_MAX_CHARS = 500
"""原始錯誤最長幾個字，和任務失敗的細節（``error_codes.MAX_DETAIL_CHARS``）一樣。"""


def detect_gpu() -> Gpu | GpuUnavailable:
    """這個行程看得到的第一張顯卡；PyTorch 用不了顯卡時是原因與下一步。

    看得到顯卡時和 #262 之前走同一段程式：只在用不了時才多問原因。
    """
    try:
        import torch
    except Exception as e:  # DLL 載入失敗是 OSError，套件壞掉時什麼例外都有可能
        return _noted(_torch_load_failed(e))
    cuda = getattr(torch.version, "cuda", None)
    try:
        if torch.cuda.is_available():
            card = torch.cuda.get_device_properties(0)
            return Gpu(name=str(card.name), vram_gb=round(card.total_memory / 2**30, 1),
                       supported=arch_supported(torch.cuda.get_device_capability(0),
                                                torch.cuda.get_arch_list()))
        if cuda is None:
            return _noted(GpuUnavailable(
                "torch_load_failed",
                f"PyTorch 載入失敗：裝的版本（{torch.__version__}）不支援 CUDA",
                "請回報問題並附上診斷資訊，或改用 Gemini"))
        # is_available() 把 CUDA 的錯誤吞掉、只回 False；再初始化一次，拿 PyTorch 的錯誤訊息來分
        torch.cuda.init()
    except Exception as e:
        return _noted(_cuda_failed(e, cuda))
    return _noted(NO_GPU)  # 初始化成功卻沒有顯卡


def _cuda_failed(error: BaseException, cuda: str | None) -> GpuUnavailable:
    """照 PyTorch 初始化 CUDA 的錯誤訊息分原因。訊息是 c10/cuda/CUDAFunctions.cpp 的
    ``device_count_impl`` 與 ``device_count_ensure_non_zero`` 寫的（torch 2.8.0 的 c10_cuda.dll 裡
    逐字相同）；認不得的都算初始化失敗。"""
    detail = _error_summary(error)
    text = str(error)
    if "Found no NVIDIA driver" in text:
        return GpuUnavailable(
            "no_gpu", "這台電腦沒有可用的 NVIDIA 顯卡（找不到 NVIDIA 驅動）",
            "可以改用 Gemini；有 NVIDIA 顯卡的話，裝好驅動後重新開啟 Mimiji", detail)
    if "No CUDA GPUs are available" in text:
        return replace(NO_GPU, detail=detail)
    too_old = re.search(r"driver on your system is too old \(found version (\d+)\)", text)
    if too_old:
        versions = "，".join(filter(None, (_current_driver(too_old.group(1)), _required_driver(cuda))))
        return GpuUnavailable(
            "driver_too_old", f"NVIDIA 顯卡驅動太舊（{versions}）",
            "更新驅動後重新開啟 Mimiji，或改用 Gemini", detail)
    return GpuUnavailable(
        "cuda_init_failed", "顯卡的 CUDA 初始化失敗",
        "重新開機後再試；還是一樣的話，重新安裝最新的 NVIDIA 驅動，或改用 Gemini", detail)


def _current_driver(cuda_driver_version: str) -> str:
    """目前的驅動：nvidia-smi 回報的版本；問不到時寫 PyTorch 訊息裡的版本，那是驅動支援到哪一版
    CUDA（``cuDriverGetVersion``，1000 × 主版號 + 10 × 次版號，例如 11040 是 11.4）。"""
    version = nvidia_driver_version()
    if version:
        return f"目前 {version}"
    number = int(cuda_driver_version)
    return f"目前的驅動支援到 CUDA {number // 1000}.{number % 1000 // 10}"


def _required_driver(cuda: str | None) -> str:
    """要裝的驅動。Windows 上照 :data:`WINDOWS_DRIVER_FOR_CUDA` 寫版本；表上沒有的 CUDA，或不是
    Windows（Docker 模式的 GPU worker），寫要支援哪一版 CUDA。"""
    version = WINDOWS_DRIVER_FOR_CUDA.get(cuda or "") if platform.system() == "Windows" else None
    if version:
        return f"需要 {version} 以上"
    return f"需要支援 CUDA {cuda} 的驅動" if cuda else "需要更新驅動"


def _torch_load_failed(error: BaseException) -> GpuUnavailable:
    detail = _error_summary(error)
    if _missing_vc_runtime():
        return GpuUnavailable(
            "torch_load_failed", "PyTorch 載入失敗：這台電腦沒有 Microsoft Visual C++ 可轉散發套件",
            f"從 {VC_REDIST_URL} 下載安裝後重新開啟 Mimiji，或改用 Gemini", detail)
    return GpuUnavailable(
        "torch_load_failed", "PyTorch 載入失敗",
        "重新開機後再試；還是一樣的話，請回報問題並附上診斷資訊，或改用 Gemini", detail)


def _missing_vc_runtime() -> bool:
    """Windows 上缺 Microsoft Visual C++ 可轉散發套件的 DLL。torch 載入自己的 DLL 前也查這三個
    （torch 2.8.0 的 ``torch/__init__.py``），缺了就載入失敗；免安裝版的 Python 沒有帶 msvcp140.dll。"""
    if platform.system() != "Windows":
        return False
    import ctypes
    try:
        for dll in ("vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"):
            ctypes.CDLL(dll)
    except OSError:
        return True
    return False


def nvidia_driver_version() -> str | None:
    """nvidia-smi 回報的驅動版本（例如 ``576.02``）；沒裝 NVIDIA 驅動或問不到時是 None。"""
    output = command_output("nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader")
    lines = output.strip().splitlines() if output else []
    return (lines[0].strip() or None) if lines else None  # 兩張卡時每張一行，驅動是同一個


# 引號裡有斜線的字串、磁碟機代號或 UNC 開頭的路徑（可能有空白，到引號或行尾為止）、/ 開頭的路徑。
# 網址的 // 與路徑段不算：前面是 : 或 / 或文字
_QUOTED_PATH = re.compile(r"""(["'])([^"'\n]*[\\/][^"'\n]*)\1""")
_WINDOWS_PATH = re.compile(r"""(?:\b[A-Za-z]:[\\/]|\\\\)[^"'\n]*""")
_POSIX_PATH = re.compile(r"""(?<![\w:/.~-])/[^\s"']+""")


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1]


def _error_summary(error: BaseException) -> str:
    """原始錯誤的摘要：例外類型與訊息的第一行，路徑只留檔名（診斷資訊會貼進公開的 Issue，路徑常帶
    著帳號名稱），太長的只留開頭。"""
    lines = str(error).strip().splitlines()
    text = type(error).__name__
    if lines:
        first = _QUOTED_PATH.sub(lambda m: m.group(1) + _basename(m.group(2)) + m.group(1), lines[0])
        first = _POSIX_PATH.sub(lambda m: _basename(m.group(0)), _WINDOWS_PATH.sub(
            lambda m: _basename(m.group(0)), first))
        text = f"{text}: {first}"
    return text if len(text) <= DETAIL_MAX_CHARS else text[:DETAIL_MAX_CHARS] + "…"


_noted_problems: set[GpuUnavailable] = set()


def _noted(problem: GpuUnavailable) -> GpuUnavailable:
    """每種原因在日誌寫一次（設定頁與轉錄頁每次問都會偵測一次）。寫 info 不寫 warning：沒有顯卡
    的電腦本來就用不了本機轉錄，Docker 模式的 API 容器也本來就沒裝 torch。"""
    if problem not in _noted_problems:
        _noted_problems.add(problem)
        logger.info(f"本機轉錄不能用：{problem.problem}"
                    + (f"（{problem.detail}）" if problem.detail else ""))
    return problem


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


def _unusable_gpu(gpu: Gpu | GpuUnavailable) -> LocalNotReady:
    if isinstance(gpu, GpuUnavailable):
        return LocalNotReady(gpu.reason, gpu.message)
    # 不在清單裡的通常是太舊的卡，也可能是比這版 torch 新一代的卡，所以不說「太舊」
    return LocalNotReady("unsupported_gpu", f"目前的 PyTorch 不支援這張顯卡（{gpu.name}），"
                         "本機轉錄不能用，可以改用 Gemini")


def gpu_problem(gpu: Gpu | GpuUnavailable) -> str | None:
    """這張顯卡（:func:`detect_gpu` 的結果）跑不了本機轉錄的原因與下一步；跑得了時是 None。

    轉錄頁的就緒提示（經 :func:`ensure_local_ready`）與設定頁的本機卡片都照它；診斷資訊寫同一個
    :class:`GpuUnavailable` 的 ``problem``。
    """
    return None if isinstance(gpu, Gpu) and gpu.supported else str(_unusable_gpu(gpu))


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
    if not isinstance(gpu, Gpu) or not gpu.supported:
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
