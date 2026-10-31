"""本機不能用時，轉錄頁、設定頁與「複製診斷資訊」寫同一個原因（#262）。

測試範圍（免安裝模式）：
  GET /api/v1/setting/local-models/readiness  轉錄頁選本機時的就緒提示
  GET /api/v1/setting/local-models/status     設定頁的本機卡片
  GET /api/v1/diagnostics                     複製診斷資訊

torch 換成 tests/support/fake_torch.py 的假 torch，走真的 :func:`weights.detect_gpu`。
"""
import platform

import pytest

from app.core.config import get_settings
from app.provider.local import weights
from tests.support.fake_torch import (
    DLL_LOAD_FAILED,
    INIT_FAILED,
    NO_DRIVER,
    RTX_4080,
    TOO_OLD,
    fake_torch,
    torch_import_fails,
)

READINESS_URL = "/api/v1/setting/local-models/readiness"
STATUS_URL = "/api/v1/setting/local-models/status"
DIAGNOSTICS_URL = "/api/v1/diagnostics"


@pytest.fixture(autouse=True)
def windows_standalone(monkeypatch, tmp_path):
    """免安裝模式的 Windows 電腦，nvidia-smi 回報驅動 472.12，模型權重都已下載。"""
    monkeypatch.setattr(get_settings(), "app_mode", "standalone")
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(weights, "command_output", lambda *command: "472.12\n")
    monkeypatch.setattr(weights, "_missing_vc_runtime", lambda: False)
    monkeypatch.setattr(weights, "repo_is_ready", lambda repo: True)


def what_each_page_says(client) -> dict:
    readiness = client.get(READINESS_URL).json()
    status = client.get(STATUS_URL).json()
    lines = client.get(DIAGNOSTICS_URL).json()["text"].splitlines()
    return {
        "reason": readiness["reason"],
        "readiness": readiness["message"],
        "settings": status["gpu_problem"],
        "gpu_available": status["gpu_available"],
        "diagnostics": next(line for line in lines if line.startswith("- 顯卡：")),
        "torch_error": next((line for line in lines if line.startswith("- PyTorch 的錯誤：")), None),
    }


@pytest.mark.parametrize("cause, reason, problem", [
    (lambda mp: fake_torch(mp, init_error=RuntimeError(NO_DRIVER)), "no_gpu",
     "這台電腦沒有可用的 NVIDIA 顯卡（找不到 NVIDIA 驅動）"),
    (lambda mp: fake_torch(mp, init_error=RuntimeError(TOO_OLD)), "driver_too_old",
     "NVIDIA 顯卡驅動太舊（目前 472.12，需要 572.61 以上）"),
    (lambda mp: fake_torch(mp, init_error=RuntimeError(INIT_FAILED)), "cuda_init_failed",
     "顯卡的 CUDA 初始化失敗"),
    (lambda mp: torch_import_fails(mp, DLL_LOAD_FAILED), "torch_load_failed", "PyTorch 載入失敗"),
], ids=["no_gpu", "driver_too_old", "cuda_init_failed", "torch_load_failed"])
def test_every_page_gives_the_same_reason(client, monkeypatch, cause, reason, problem):
    cause(monkeypatch)

    said = what_each_page_says(client)

    assert said["reason"] == reason
    assert said["readiness"].startswith(f"{problem}，本機轉錄不能用，")
    assert said["settings"] == said["readiness"]
    assert said["gpu_available"] is False
    assert said["diagnostics"] == f"- 顯卡：{problem}"
    assert said["torch_error"] and "王小明" not in said["torch_error"]


def test_a_usable_gpu_is_ready_everywhere(client, monkeypatch):
    fake_torch(monkeypatch, card=RTX_4080)

    said = what_each_page_says(client)

    assert (said["reason"], said["readiness"], said["settings"]) == (None, None, None)
    assert said["gpu_available"] is True
    assert said["diagnostics"] == "- 顯卡：NVIDIA GeForce RTX 4080 SUPER（16 GB）"
    assert said["torch_error"] is None
