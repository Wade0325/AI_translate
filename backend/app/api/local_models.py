"""本機的模型權重管理 API（免安裝模式的首次下載與狀態查詢）。

權重不隨發布包提供；使用者首次要用本機的模型時由此下載到 HF_HOME
（免安裝模式指向 data/models/hf_cache）。預設模型 moss-align 只需 MOSS 與對齊器
（大小見 weights.REPO_SIZE_GB）；「MOSS + Qwen3-ASR」「VibeVoice + Qwen3-ASR」用到的權重屬選用，
另外以 ``?model=all`` 下載。下載在獨立執行緒進行，前端以輪詢 status 取得進度。

進度以位元組計算（:class:`_DownloadPlan`）：開始前先問 Hub 這次要下載的每個檔案多大，之後每次查
狀態時看快取裡已經有多少。中斷後再 POST 一次 download，已下載完成的檔案會跳過；沒下載完的檔案從頭
下載：huggingface_hub 1.23 下載失敗時刪掉那個檔案的暫存檔（file_download._download_to_tmp_and_move）。
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.provider.local import weights
from app.provider.local.provider import vram_notice
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()

_FREE_SPACE_MARGIN_GB = 2.0

# 各模型權重在釘住的 revision 上，Hugging Face 模型卡（README.md）開頭 license 欄位的原文，以及查的是
# 哪個 revision。2026-10-31 照 https://huggingface.co/api/models/<repo>/revision/<revision> 的
# cardData.license 核對。weights.REPO_REVISIONS 換版時要重新核對：測試確認兩邊的 revision 相同
_MODEL_CARD_LICENSES = {
    weights.MOSS_MODEL_ID: ("704aa4a9c304e8520be88901e0d1960158ef5b15", "apache-2.0"),
    weights.ALIGNER_MODEL_ID: ("c07281df297b9905d24a508279258cccf987a064", "apache-2.0"),
    weights.ASR_MODEL_ID: ("bcd2b5b7f32b480ab5790554cfa8347f246a14f3", "apache-2.0"),
    weights.DIARIZATION_MODEL_ID: ("f22241c2062b3b25272bf117397e03d73381037a", "mit"),
}


def _model_card_url(repo_id: str) -> str:
    """釘住的 revision 的模型卡：授權寫在它開頭的 license 欄位。"""
    revision, _ = _MODEL_CARD_LICENSES[repo_id]
    return f"https://huggingface.co/{repo_id}/blob/{revision}/README.md"


@dataclass(frozen=True)
class _DownloadPlan:
    """一次下載要放進快取的所有檔案，用來算已經下載了多少位元組。"""
    files: tuple[tuple[Path, int], ...]
    """每個檔案下載完成後在快照裡的位置（``<repo 的快取資料夾>/snapshots/<commit>/<檔名>``）與大小。"""
    blob_dirs: frozenset[Path]
    """各 repo 快取資料夾裡的 ``blobs``：下載中的檔案先寫在這裡的暫存檔。"""
    started_at: float
    """開始下載的時間（``time.time()``）：比它舊的暫存檔是之前被強制結束的下載留下的，不算。"""

    @property
    def total_bytes(self) -> int:
        return sum(size for _, size in self.files)

    def downloaded_bytes(self) -> int:
        """快取裡已有的位元組：下載完成的檔案，加上這次下載開始後寫入的暫存檔。

        huggingface_hub 先把檔案寫進 ``blobs/*.incomplete``，寫完才放進快照，所以下載到一半的
        大檔看暫存檔的大小。暫存檔的命名是 huggingface_hub 的內部做法，改了也只是少算正在下載的
        那幾個檔案，下載完成的照樣算得到。
        """
        done = sum(size for path, size in self.files if path.exists())
        partial = 0
        for blobs in self.blob_dirs:
            for temp in blobs.glob("*.incomplete"):
                try:
                    stat = temp.stat()
                except OSError:
                    continue  # 剛寫完、已經搬走
                if stat.st_mtime >= self.started_at:
                    partial += stat.st_size
        return min(done + partial, self.total_bytes)


def _plan_download(repos: list[str]) -> _DownloadPlan:
    """問 Hub 每個 repo 釘住的版本（和 weights.download_snapshot 下載的同一版）有哪些檔案、各多大。

    用 snapshot_download 的 dry_run：不下載，每個檔案回報大小與下載完成後在快照裡的位置。
    """
    from huggingface_hub import snapshot_download
    # 往前留兩秒：檔案系統記的修改時間可能取自比 time.time() 粗的時鐘（每個時鐘週期才更新），
    # 緊接著建立的暫存檔，時間可能比這裡早幾毫秒。被強制結束的下載不會在兩秒內又開始一次（要重開 app）
    started_at = time.time() - 2
    files, blob_dirs = [], set()
    for repo in repos:
        for info in snapshot_download(repo, revision=weights.REPO_REVISIONS.get(repo), dry_run=True):
            path = Path(info.local_path)
            files.append((path, info.file_size))
            # 檔名可能帶子資料夾（figures/DER.jpg），往上數過檔名、<commit> 與 snapshots 三段
            blob_dirs.add(path.parents[len(PurePosixPath(info.filename).parts) + 1] / "blobs")
    return _DownloadPlan(tuple(files), frozenset(blob_dirs), started_at)


_lock = threading.Lock()
_state = {
    "state": "idle",       # idle | downloading | completed | failed
    "target": None,        # 下載目標：預設模型名稱或 "all"
    "repo_index": 0,
    "repo_count": len(weights.REQUIRED_REPOS),
    "current_repo": None,
    "downloaded_bytes": None,  # 這次下載的檔案已在本機的位元組；問完 Hub 之前是 None
    "total_bytes": None,       # 這次下載的檔案總共多大（位元組）
    "error": None,
}
_plan: _DownloadPlan | None = None


def _download_worker(repos: list[str]):
    global _plan
    try:
        plan = _plan_download(repos)
        with _lock:
            _plan = plan
            _state.update(total_bytes=plan.total_bytes, downloaded_bytes=0)
        total = len(repos)
        for idx, repo in enumerate(repos, start=1):
            with _lock:
                _state.update(repo_index=idx, repo_count=total, current_repo=repo)
            logger.info(f"下載本機模型權重 ({idx}/{total}): {repo}")
            weights.download_snapshot(repo)
        with _lock:
            _state.update(state="completed", current_repo=None, downloaded_bytes=plan.total_bytes)
        logger.info("本機模型權重下載完成")
    except Exception as e:
        # 例外的文字可能帶著使用者電腦上的路徑：原因只記在 log，畫面給固定訊息
        logger.error(f"本機模型權重下載失敗: {type(e).__name__}: {e}")
        with _lock:
            _state.update(state="failed", error="請確認網路連線與磁碟空間，一直失敗的話請回報問題")


def _download_status() -> dict:
    """下載狀態；下載中時順便看快取，更新已下載的位元組。

    只增不減：檔案寫完、搬進快照的那一瞬間，暫存檔已經不在、快照裡還沒有，看起來會少一個檔案。
    """
    with _lock:
        plan = _plan if _state["state"] == "downloading" else None
    if plan is not None:
        downloaded = plan.downloaded_bytes()
        with _lock:
            if _state["state"] == "downloading" and _plan is plan:
                _state["downloaded_bytes"] = max(_state["downloaded_bytes"] or 0, downloaded)
    with _lock:
        return dict(_state)


def _target_repos(model: Optional[str]) -> tuple[str, ...]:
    try:
        return weights.download_targets(model)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"不支援的本機模型: {model}") from None


@router.get("/local-models/status")
def local_models_status():
    """GPU 與權重狀態；下載進行中時同時回報進度。

    ``all_downloaded`` 只看預設模型所需的權重；選用權重以 ``required: false`` 標示。每個權重附上
    Hugging Face 模型卡寫的授權（``license``，照原文）與模型卡的網址（``model_card_url``）。
    ``gpu_problem`` 是顯卡跑不了本機轉錄的原因與下一步（:func:`weights.gpu_problem`），``vram_notice``
    是預設模型在這張顯卡上的記憶體提示（#11），都可以直接顯示給使用者。
    """
    gpu = weights.detect_gpu()
    card = gpu if isinstance(gpu, weights.Gpu) else None
    problem = weights.gpu_problem(gpu)
    models = [
        {
            "repo_id": repo,
            "downloaded": weights.repo_is_ready(repo),
            "required": repo in weights.REQUIRED_REPOS,
            "used_by": [m for m, repos in weights.MODEL_REPOS.items() if repo in repos],
            "license": _MODEL_CARD_LICENSES[repo][1],
            "model_card_url": _model_card_url(repo),
        }
        for repo in weights.ALL_REPOS
    ]
    download = _download_status()
    return {
        "standalone": get_settings().is_standalone,
        "gpu_available": problem is None,
        "gpu_name": card.name if card else None,
        "gpu_vram_gb": card.vram_gb if card else None,
        "gpu_problem": problem,
        "vram_notice": vram_notice(None),
        "hf_home": get_settings().hf_home,
        "default_model": weights.DEFAULT_LOCAL_MODEL,
        "required_size_gb": weights.size_gb(weights.REQUIRED_REPOS),
        "optional_size_gb": weights.size_gb(
            r for r in weights.ALL_REPOS if r not in weights.REQUIRED_REPOS),
        "models": models,
        "all_downloaded": all(m["downloaded"] for m in models if m["required"]),
        "optional_downloaded": all(m["downloaded"] for m in models if not m["required"]),
        "download": download,
    }


@router.get("/local-models/readiness")
def local_readiness(
    model: Optional[str] = Query(None, description="轉錄頁選的本機模型；省略＝預設模型"),
):
    """轉錄頁選本機時先問的事（#11）：現在能不能用這個模型轉錄，不能時的原因與 ``reason``
    （見 :class:`weights.LocalNotReady`），以及顯卡記憶體的提示（只提示、不擋）。

    和轉錄前的檢查是同一套判斷，不載入模型。只在免安裝模式查：Docker 模式的本機轉錄在主機的
    GPU worker，API 容器看到的不是它的顯卡與模型權重（和設定頁的「測試」相同），回
    ``checked: false``，轉錄頁不提示也不擋，由任務時的檢查把關。
    """
    if not get_settings().is_standalone:
        return {"checked": False, "ready": None, "reason": None, "message": None,
                "vram_notice": None}
    try:
        weights.ensure_local_ready(model)
    except weights.LocalNotReady as e:
        reason, message = e.reason, str(e)
    else:
        reason = message = None
    return {"checked": True, "ready": reason is None, "reason": reason, "message": message,
            "vram_notice": vram_notice(model)}


@router.post("/local-models/download")
def start_local_models_download(
    model: Optional[str] = Query(
        None, description="省略＝預設模型所需；all＝所有本機模型；或指定模型名稱"),
):
    """啟動（或續傳）權重下載。已在下載中或目標已齊備時為 no-op。"""
    global _plan
    repos = _target_repos(model)
    hf_home = Path(get_settings().hf_home)
    # 檢查與設定在同一把鎖內：兩個同時的請求不會各自起一條下載執行緒
    with _lock:
        if _state["state"] == "downloading":
            return {"started": False, "reason": "already-downloading"}

        missing = [r for r in repos if not weights.repo_is_ready(r)]
        if not missing:
            # 目標已齊（也可能是其他途徑補齊的）：清掉先前殘留的失敗狀態
            _state.update(state="completed", error=None)
            return {"started": False, "reason": "already-downloaded"}

        hf_home.mkdir(parents=True, exist_ok=True)
        need_gb = weights.size_gb(missing) + _FREE_SPACE_MARGIN_GB
        free = shutil.disk_usage(hf_home).free
        if free < need_gb * 1024 ** 3:
            raise HTTPException(
                status_code=400,
                detail=f"磁碟空間不足：需要約 {need_gb:.0f} GB，"
                       f"目前剩餘 {free / 1024 ** 3:.1f} GB",
            )

        _state.update(
            state="downloading", target=model or weights.DEFAULT_LOCAL_MODEL, error=None,
            repo_index=0, repo_count=len(missing), current_repo=None,
            downloaded_bytes=None, total_bytes=None)
        _plan = None  # 上一次下載的檔案清單：問完 Hub、換成這次的之前不算進度
    threading.Thread(
        target=_download_worker, args=(missing,), daemon=True,
        name="hf-weights-download").start()
    return {"started": True, "repos": missing}
