"""本機的模型權重管理 API（免安裝模式的首次下載與狀態查詢）。

權重不隨發布包提供；使用者首次要用本機的模型時由此下載到 HF_HOME
（免安裝模式指向 data/models/hf_cache）。預設模型 moss-align 只需 MOSS 與對齊器
（大小見 weights.REPO_SIZE_GB）；「MOSS + Qwen3-ASR」「VibeVoice + Qwen3-ASR」用到的權重屬選用，
另外以 ``?model=all`` 下載。下載在獨立執行緒進行，前端以輪詢 status 取得進度；
HuggingFace 原生支援斷點續傳，中斷後再 POST 一次 download 即繼續。
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.provider.local import weights
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()

_FREE_SPACE_MARGIN_GB = 2.0

_lock = threading.Lock()
_state = {
    "state": "idle",       # idle | downloading | completed | failed
    "target": None,        # 下載目標：預設模型名稱或 "all"
    "repo_index": 0,
    "repo_count": len(weights.REQUIRED_REPOS),
    "current_repo": None,
    "progress_pct": None,  # 目前 repo 的檔案完成百分比（粗粒度）
    "error": None,
}


def _make_progress_tqdm():
    from tqdm.auto import tqdm as _tqdm

    class _ProgressTqdm(_tqdm):
        def update(self, n=1):
            result = super().update(n)
            if self.total:
                with _lock:
                    _state["progress_pct"] = round(self.n / self.total * 100, 1)
            return result

    return _ProgressTqdm


def _download_worker(repos: list[str]):
    try:
        tqdm_cls = _make_progress_tqdm()
        total = len(repos)
        for idx, repo in enumerate(repos, start=1):
            with _lock:
                _state.update(
                    repo_index=idx, repo_count=total, current_repo=repo, progress_pct=None)
            logger.info(f"下載本機模型權重 ({idx}/{total}): {repo}")
            weights.download_snapshot(repo, tqdm_class=tqdm_cls)
        with _lock:
            _state.update(state="completed", current_repo=None)
        logger.info("本機模型權重下載完成")
    except Exception as e:
        # 例外的文字可能帶著使用者電腦上的路徑：原因只記在 log，畫面給固定訊息
        logger.error(f"本機模型權重下載失敗: {type(e).__name__}: {e}")
        with _lock:
            _state.update(state="failed", error="請確認網路連線與磁碟空間，一直失敗的話請回報問題")


def _target_repos(model: Optional[str]) -> tuple[str, ...]:
    try:
        return weights.download_targets(model)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"不支援的本機模型: {model}") from None


@router.get("/local-models/status")
def local_models_status():
    """GPU 與權重狀態；下載進行中時同時回報進度。

    ``all_downloaded`` 只看預設模型所需的權重；選用權重以 ``required: false`` 標示。
    """
    cuda_ok, gpu_name = weights.cuda_status()
    models = [
        {
            "repo_id": repo,
            "downloaded": weights.repo_is_ready(repo),
            "required": repo in weights.REQUIRED_REPOS,
            "used_by": [m for m, repos in weights.MODEL_REPOS.items() if repo in repos],
        }
        for repo in weights.ALL_REPOS
    ]
    with _lock:
        download = dict(_state)
    return {
        "standalone": get_settings().is_standalone,
        "gpu_available": cuda_ok,
        "gpu_name": gpu_name,
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


@router.post("/local-models/download")
def start_local_models_download(
    model: Optional[str] = Query(
        None, description="省略＝預設模型所需；all＝所有本機模型；或指定模型名稱"),
):
    """啟動（或續傳）權重下載。已在下載中或目標已齊備時為 no-op。"""
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
            repo_index=0, repo_count=len(missing), current_repo=None, progress_pct=None)
    threading.Thread(
        target=_download_worker, args=(missing,), daemon=True,
        name="hf-weights-download").start()
    return {"started": True, "repos": missing}
