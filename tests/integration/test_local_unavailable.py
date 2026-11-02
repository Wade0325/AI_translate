"""本機不能用時，轉錄頁、設定頁與「複製診斷資訊」寫同一個原因（#262、#311）。

測試範圍（免安裝模式）：
  GET /api/v1/setting/local-models/readiness  轉錄頁選本機時的就緒提示
  GET /api/v1/setting/local-models/status     設定頁的本機卡片
  POST /api/v1/setting/test                   設定頁的「測試」
  GET /api/v1/diagnostics                     複製診斷資訊

torch 換成 tests/support/fake_torch.py 的假 torch，走真的 :func:`weights.detect_gpu`。
"""
import platform

import pytest

from app.core.config import get_settings
from app.provider.local import packages, weights
from tests.support.fake_torch import (
    DLL_LOAD_FAILED,
    INIT_FAILED,
    NO_DRIVER,
    RTX_4080,
    TOO_OLD,
    fake_torch,
    torch_import_fails,
)

_real_vc_runtime_problem = weights._vc_runtime_problem  # windows_standalone 換掉它；查 DLL 的測試換回來

READINESS_URL = "/api/v1/setting/local-models/readiness"
TEST_URL = "/api/v1/setting/test"
STATUS_URL = "/api/v1/setting/local-models/status"
DIAGNOSTICS_URL = "/api/v1/diagnostics"


@pytest.fixture(autouse=True)
def windows_standalone(monkeypatch, tmp_path):
    """免安裝模式的 Windows 電腦，nvidia-smi 回報驅動 472.12，模型權重都已下載。"""
    monkeypatch.setattr(get_settings(), "app_mode", "standalone")
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(weights, "command_output", lambda *command: "472.12\n")
    monkeypatch.setattr(weights, "_vc_runtime_problem", lambda: None)
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


@pytest.mark.parametrize("nvidia, reason, problem", [
    (True, "torch_load_failed", "PyTorch 載入失敗：這台電腦沒有 Microsoft Visual C++ 可轉散發套件"),
    # 沒有 NVIDIA 驅動時，裝好 VC++ 本機轉錄也還是不能用：先說顯卡（#304）
    (False, "no_gpu", "這台電腦沒有可用的 NVIDIA 顯卡（找不到 NVIDIA 驅動）"),
], ids=["nvidia_driver", "no_nvidia_driver"])
def test_missing_visual_cpp_runtime_reads_the_same_everywhere(client, monkeypatch, tmp_path,
                                                              nvidia, reason, problem):
    system32 = tmp_path / "System32"
    system32.mkdir()
    if nvidia:
        (system32 / "nvcuda.dll").write_bytes(b"")
    monkeypatch.setattr(weights, "_vc_runtime_problem", _real_vc_runtime_problem)
    monkeypatch.setattr(weights, "_system32", lambda: system32)
    torch_import_fails(monkeypatch, DLL_LOAD_FAILED)

    said = what_each_page_says(client)

    assert said["reason"] == reason
    assert said["readiness"].startswith(f"{problem}，本機轉錄不能用，")
    assert weights.VC_REDIST_URL in said["readiness"]
    assert said["settings"] == said["readiness"]
    assert said["diagnostics"] == f"- 顯卡：{problem}"


def test_a_usable_gpu_is_ready_everywhere(client, monkeypatch):
    fake_torch(monkeypatch, card=RTX_4080)

    said = what_each_page_says(client)

    assert (said["reason"], said["readiness"], said["settings"]) == (None, None, None)
    assert said["gpu_available"] is True
    assert said["diagnostics"] == "- 顯卡：NVIDIA GeForce RTX 4080 SUPER（16 GB）"
    assert said["torch_error"] is None


def test_a_package_that_fails_to_load_is_not_ready_anywhere(client, monkeypatch):
    # PR #306 在 Wade 的電腦上的情況：顯卡能用，import moss_transcribe_diarize 卻因為使用者自己裝的
    # torchvision 失敗。以前轉錄頁說能轉錄、任務失敗時又說「缺少套件」（#311）
    fake_torch(monkeypatch, card=RTX_4080)
    packages._results[packages.MOSS] = packages.PackageUnavailable(
        "package_load_failed", "moss-transcribe-diarize",
        detail="RuntimeError: operator torchvision::nms does not exist")
    problem = "moss-transcribe-diarize 套件載入失敗"

    readiness = client.get(READINESS_URL).json()
    test = client.post(TEST_URL, json={"provider": "local", "apiKeys": [], "model": "moss-align"})
    lines = client.get(DIAGNOSTICS_URL).json()["text"].splitlines()

    assert (readiness["ready"], readiness["reason"]) == (False, "package_load_failed")
    assert readiness["message"] == (f"{problem}，本機轉錄不能用，"
                                    "請回報問題並附上診斷資訊，或改用 Gemini")
    assert test.json() == {"success": False, "message": readiness["message"]}
    assert f"- 本機模型的套件：{problem}" in lines
    assert ("- moss-transcribe-diarize 的錯誤：RuntimeError: operator torchvision::nms does not "
            "exist") in lines
