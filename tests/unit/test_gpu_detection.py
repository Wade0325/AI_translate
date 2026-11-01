"""本機不能用時分清原因（#262）：沒有 NVIDIA 顯卡、驅動太舊、CUDA 初始化失敗、PyTorch 載入失敗。

從 :func:`weights.detect_gpu` 與轉錄前的檢查（:func:`weights.ensure_local_ready`）觀察，torch 換成
tests/support/fake_torch.py 的假 torch。
"""
import platform
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.error_codes import ErrorCode, describe
from app.provider.local import weights
from tests.support.fake_torch import (
    DLL_LOAD_FAILED,
    INIT_FAILED,
    NO_DEVICE,
    NO_DRIVER,
    RTX_4080,
    TOO_OLD,
    UNEXPECTED,
    fake_torch,
    torch_import_fails,
)

STANDALONE_REQUIREMENTS = (
    Path(__file__).resolve().parents[2] / "backend" / "requirements-standalone.txt")
_real_missing_vc_runtime = weights._missing_vc_runtime  # machine 換掉它；查 DLL 的測試換回來


@pytest.fixture
def machine(monkeypatch):
    """一台 Windows 電腦：nvidia-smi 回報的驅動版本由測試決定（None 是問不到）。"""
    state = SimpleNamespace(driver=None)
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(weights, "command_output", lambda *command: (
        f"{state.driver}\n" if state.driver and command[0] == "nvidia-smi" else None))
    monkeypatch.setattr(weights, "_missing_vc_runtime", lambda: False)
    monkeypatch.setattr(weights, "repo_is_ready", lambda repo: True)
    return state


def not_ready() -> weights.LocalNotReady:
    with pytest.raises(weights.LocalNotReady) as caught:
        weights.ensure_local_ready()
    return caught.value


class TestUsableGpu:
    def test_a_supported_card_is_ready_without_asking_why(self, monkeypatch, machine):
        calls = fake_torch(monkeypatch, card=RTX_4080)

        gpu = weights.ensure_local_ready()

        assert gpu == weights.Gpu("NVIDIA GeForce RTX 4080 SUPER", 16.0, True)
        assert weights.gpu_problem(gpu) is None
        assert calls == []  # 看得到顯卡時不再初始化一次


class TestNoNvidiaGpu:
    def test_no_driver(self, monkeypatch, machine):
        # 沒有 NVIDIA 顯卡的電腦多半是這種：沒有裝 NVIDIA 驅動
        fake_torch(monkeypatch, init_error=RuntimeError(NO_DRIVER))

        error = not_ready()

        assert error.reason == "no_gpu"
        assert str(error) == ("這台電腦沒有可用的 NVIDIA 顯卡（找不到 NVIDIA 驅動），本機轉錄不能用，"
                              "可以改用 Gemini；有 NVIDIA 顯卡的話，裝好驅動後重新開啟 Mimiji")
        assert describe(error).code == ErrorCode.LOCAL_NO_GPU

    def test_driver_but_no_device(self, monkeypatch, machine):
        fake_torch(monkeypatch, init_error=RuntimeError(NO_DEVICE))

        error = not_ready()

        assert error.reason == "no_gpu"
        assert str(error) == "這台電腦沒有可用的 NVIDIA 顯卡，本機轉錄不能用，可以改用 Gemini"
        assert weights.detect_gpu().detail == f"RuntimeError: {NO_DEVICE}"


class TestDriverTooOld:
    def test_names_the_current_and_the_required_version(self, monkeypatch, machine):
        machine.driver = "472.12"
        fake_torch(monkeypatch, init_error=RuntimeError(TOO_OLD))

        error = not_ready()

        assert error.reason == "driver_too_old"
        assert str(error) == ("NVIDIA 顯卡驅動太舊（目前 472.12，需要 572.61 以上），本機轉錄不能用，"
                              "更新驅動後重新開啟 Mimiji，或改用 Gemini")
        assert describe(error).code == ErrorCode.LOCAL_DRIVER_TOO_OLD

    def test_without_nvidia_smi_names_the_cuda_version_the_driver_supports(self, monkeypatch,
                                                                            machine):
        # PyTorch 的訊息帶的是 cuDriverGetVersion：11040 是 CUDA 11.4
        fake_torch(monkeypatch, init_error=RuntimeError(TOO_OLD))

        assert weights.detect_gpu().problem == (
            "NVIDIA 顯卡驅動太舊（目前的驅動支援到 CUDA 11.4，需要 572.61 以上）")

    def test_outside_windows_names_the_cuda_version_to_support(self, monkeypatch, machine):
        # Docker 模式的 GPU worker：Linux 上的 torch 2.7.0 帶 CUDA 12.6，表上只有免安裝版的 Windows
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        machine.driver = "470.82.01"
        fake_torch(monkeypatch, init_error=RuntimeError(TOO_OLD), cuda="12.6",
                   version="2.7.0+cu126")

        assert weights.detect_gpu().problem == (
            "NVIDIA 顯卡驅動太舊（目前 470.82.01，需要支援 CUDA 12.6 的驅動）")

    def test_the_required_version_was_checked_for_the_shipped_torch(self):
        # 表是照 torch 2.8.0+cu128（Windows）帶的 cudart 12.8.90（CUDA 12.8 Update 1）查的：
        # 免安裝版換了 torch，就要照 NVIDIA 的對照表重查 WINDOWS_DRIVER_FOR_CUDA
        pinned = re.search(r"^torch==(\S+)", STANDALONE_REQUIREMENTS.read_text(encoding="utf-8"),
                           re.MULTILINE)
        assert pinned and pinned.group(1) == weights.DRIVER_TABLE_TORCH
        cuda = re.search(r"\+cu(\d+)(\d)$", weights.DRIVER_TABLE_TORCH)
        assert cuda and f"{cuda.group(1)}.{cuda.group(2)}" in weights.WINDOWS_DRIVER_FOR_CUDA


class TestCudaInitFailed:
    @pytest.mark.parametrize("message", [INIT_FAILED, UNEXPECTED])
    def test_driver_present_but_cuda_does_not_start(self, monkeypatch, machine, message):
        machine.driver = "576.02"
        fake_torch(monkeypatch, init_error=RuntimeError(message))

        error = not_ready()

        assert error.reason == "cuda_init_failed"
        assert str(error) == ("顯卡的 CUDA 初始化失敗，本機轉錄不能用，重新開機後再試；還是一樣的話，"
                              "重新安裝最新的 NVIDIA 驅動，或改用 Gemini")
        assert describe(error).code == ErrorCode.LOCAL_CUDA_INIT_FAILED
        assert weights.detect_gpu().detail == f"RuntimeError: {message}"

    def test_card_seen_but_its_properties_fail(self, monkeypatch, machine):
        fake_torch(monkeypatch, card=RTX_4080,
                   properties_error=RuntimeError("CUDA error: unknown error"))

        assert not_ready().reason == "cuda_init_failed"


class TestTorchLoadFailed:
    def test_dll_load_failure(self, monkeypatch, machine):
        torch_import_fails(monkeypatch, DLL_LOAD_FAILED)

        error = not_ready()

        assert error.reason == "torch_load_failed"
        assert str(error) == ("PyTorch 載入失敗，本機轉錄不能用，重新開機後再試；還是一樣的話，"
                              "請回報問題並附上診斷資訊，或改用 Gemini")
        assert describe(error).code == ErrorCode.LOCAL_TORCH_LOAD_FAILED

    def test_missing_visual_cpp_runtime(self, monkeypatch, machine):
        # torch 載入自己的 DLL 前也查 vcruntime140.dll、msvcp140.dll、vcruntime140_1.dll
        torch_import_fails(monkeypatch, DLL_LOAD_FAILED)
        loaded = []

        def cdll(name):
            loaded.append(name)
            if name == "msvcp140.dll":
                raise OSError(126, "找不到指定的模組。")

        monkeypatch.setattr(weights, "_missing_vc_runtime", _real_missing_vc_runtime)
        monkeypatch.setattr("ctypes.CDLL", cdll)

        gpu = weights.detect_gpu()

        assert gpu.reason == "torch_load_failed"
        assert gpu.message == (
            "PyTorch 載入失敗：這台電腦沒有 Microsoft Visual C++ 可轉散發套件，本機轉錄不能用，"
            "從 https://aka.ms/vc14/vc_redist.x64.exe 下載安裝後重新開啟 Mimiji，或改用 Gemini")
        assert loaded == ["vcruntime140.dll", "msvcp140.dll"]

    def test_torch_without_cuda(self, monkeypatch, machine):
        calls = fake_torch(monkeypatch, cuda=None, version="2.8.0+cpu")

        gpu = weights.detect_gpu()

        assert gpu.reason == "torch_load_failed"
        assert gpu.problem == "PyTorch 載入失敗：裝的版本（2.8.0+cpu）不支援 CUDA"
        assert calls == []

    def test_torch_not_installed(self, monkeypatch, machine):
        monkeypatch.setitem(sys.modules, "torch", None)  # import torch 丟 ImportError

        assert weights.detect_gpu().reason == "torch_load_failed"


class TestDetail:
    """原始錯誤會寫進診斷資訊、貼進公開的 Issue：路徑只留檔名（路徑常帶著帳號名稱）。"""

    def test_dll_path_keeps_only_the_file_name(self, monkeypatch, machine):
        torch_import_fails(monkeypatch, DLL_LOAD_FAILED)

        detail = weights.detect_gpu().detail

        assert detail == ('OSError: [Errno 22] 找不到指定的模組。 Error loading "c10.dll" '
                          "or one of its dependencies.")
        assert "王小明" not in detail and "Users" not in detail

    @pytest.mark.parametrize("text, expected", [
        ("Error loading C:\\Users\\Wade Lin\\torch\\lib\\c10.dll or one of its dependencies",
         "Error loading c10.dll or one of its dependencies"),
        ("No such file: '/home/wade/.cache/torch/lib/libc10.so'", "No such file: 'libc10.so'"),
        ("cannot open /home/wade/runtime/libcudart.so.12 here", "cannot open libcudart.so.12 here"),
        ("\\\\server\\share\\王小明\\torch.dll", "torch.dll"),
        # 網址照留
        (TOO_OLD, TOO_OLD),
    ])
    def test_paths_in_other_messages(self, text, expected):
        assert weights._error_summary(RuntimeError(text)) == f"RuntimeError: {expected}"

    def test_only_the_first_line_and_not_too_long(self):
        detail = weights._error_summary(RuntimeError("x" * 1000 + "\nsecond line"))
        assert detail == "RuntimeError: " + ("x" * 1000)[:weights.DETAIL_MAX_CHARS - 14] + "…"


def test_each_reason_is_logged_once(monkeypatch, machine):
    # 設定頁與轉錄頁每次問都會偵測一次，日誌不必每次都寫
    logged = []
    monkeypatch.setattr(weights, "_noted_problems", set())
    monkeypatch.setattr(weights.logger, "info", logged.append)
    fake_torch(monkeypatch, init_error=RuntimeError(INIT_FAILED))

    for _ in range(3):
        weights.detect_gpu()

    assert logged == [f"本機轉錄不能用：顯卡的 CUDA 初始化失敗（RuntimeError: {INIT_FAILED}）"]


@pytest.mark.parametrize(("output", "expected"), [
    ("576.02\n", "576.02"),
    ("576.02\n576.02\n", "576.02"),  # 兩張卡時每張一行，驅動是同一個
    ("", None),
    (None, None),
])
def test_nvidia_driver_version(monkeypatch, output, expected):
    monkeypatch.setattr(weights, "command_output", lambda *command: output)

    assert weights.nvidia_driver_version() == expected
