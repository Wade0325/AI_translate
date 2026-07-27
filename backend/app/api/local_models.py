"""Local ASR 模型權重管理 API（standalone 模式的首次下載與狀態查詢）。

權重約 25 GB，不隨發布包提供；使用者首次要用 Local provider 時由此下載到
HF_HOME（standalone 模式指向 data/models/hf_cache）。下載在獨立執行緒進行，
前端以輪詢 status 取得進度；HuggingFace 原生支援斷點續傳，中斷後再 POST
一次 download 即繼續。
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.provider.local import weights
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()

_MIN_FREE_BYTES = 30 * 1024 ** 3

_lock = threading.Lock()
_state = {
    "state": "idle",       # idle | downloading | completed | failed
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


def _download_worker():
    from huggingface_hub import snapshot_download
    try:
        tqdm_cls = _make_progress_tqdm()
        total = len(weights.REQUIRED_REPOS)
        for idx, repo in enumerate(weights.REQUIRED_REPOS, start=1):
            with _lock:
                _state.update(
                    repo_index=idx, current_repo=repo, progress_pct=None)
            logger.info(f"下載 Local 模型權重 ({idx}/{total}): {repo}")
            snapshot_download(repo, tqdm_class=tqdm_cls)
        with _lock:
            _state.update(state="completed", current_repo=None)
        logger.info("Local 模型權重全部下載完成")
    except Exception as e:
        logger.error(f"Local 模型權重下載失敗: {e}")
        with _lock:
            _state.update(state="failed", error=str(e))


@router.get("/local-models/status")
def local_models_status():
    """GPU 與權重狀態；下載進行中時同時回報進度。"""
    cuda_ok, gpu_name = weights.cuda_status()
    models = [
        {"repo_id": repo, "downloaded": weights.repo_is_ready(repo)}
        for repo in weights.REQUIRED_REPOS
    ]
    with _lock:
        download = dict(_state)
    return {
        "standalone": get_settings().is_standalone,
        "gpu_available": cuda_ok,
        "gpu_name": gpu_name,
        "hf_home": get_settings().hf_home,
        "models": models,
        "all_downloaded": all(m["downloaded"] for m in models),
        "download": download,
    }


@router.post("/local-models/download")
def start_local_models_download():
    """啟動（或續傳）權重下載。已在下載中或已完成時為 no-op。"""
    with _lock:
        if _state["state"] == "downloading":
            return {"started": False, "reason": "already-downloading"}

    if not weights.missing_repos():
        with _lock:
            _state.update(state="completed", error=None)
        return {"started": False, "reason": "already-downloaded"}

    hf_home = Path(get_settings().hf_home)
    hf_home.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(hf_home).free
    if free < _MIN_FREE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"磁碟空間不足：模型權重約需 30 GB，"
                   f"目前剩餘 {free / 1024 ** 3:.1f} GB",
        )

    with _lock:
        _state.update(
            state="downloading", error=None,
            repo_index=0, current_repo=None, progress_pct=None)
    threading.Thread(
        target=_download_worker, daemon=True, name="hf-weights-download").start()
    return {"started": True}
