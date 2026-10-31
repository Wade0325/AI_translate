"""假的 torch：只有 :func:`app.provider.local.weights.detect_gpu` 用到的部分（#262）。

CI 沒有顯卡也沒裝 torch（tests/conftest.py 換成 MagicMock）。錯誤訊息照 torch 2.8.0+cu128（Windows）的
c10_cuda.dll 裡的原文：c10/cuda/CUDAFunctions.cpp 的 ``device_count_impl`` 與
``device_count_ensure_non_zero``。
"""

from __future__ import annotations

import builtins
import sys
import types
from types import SimpleNamespace

NO_DRIVER = ("Found no NVIDIA driver on your system. Please check that you have an NVIDIA GPU and "
             "installed a driver from http://www.nvidia.com/Download/index.aspx")
NO_DEVICE = "No CUDA GPUs are available"
TOO_OLD = ("The NVIDIA driver on your system is too old (found version 11040). Please update your "
           "GPU driver by downloading and installing a new version from the URL: "
           "http://www.nvidia.com/Download/index.aspx Alternatively, go to: https://pytorch.org to "
           "install a PyTorch version that has been compiled with your version of the CUDA driver.")
INIT_FAILED = "CUDA driver initialization failed, you might not have a CUDA gpu."
UNEXPECTED = ("Unexpected error from cudaGetDeviceCount(). Did you run some cuda functions before "
              "calling NumCudaDevices() that might have already set an error? Error 804: forward "
              "compatibility was attempted on non supported HW")
# torch 2.8.0 的 torch/__init__.py 載入 DLL 失敗時丟的 OSError：WinError 加上 DLL 的完整路徑
DLL_LOAD_FAILED = OSError(
    22, "找不到指定的模組。 Error loading "
    '"C:\\Users\\王小明\\Desktop\\Mimiji\\runtime\\Lib\\site-packages\\torch\\lib\\c10.dll" '
    "or one of its dependencies.")

RTX_4080 = ("NVIDIA GeForce RTX 4080 SUPER", 16 * 2**30, (8, 9))
CU128_ARCHES = ["sm_61", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"]


def fake_torch(monkeypatch, *, card=None, init_error=None, cuda="12.8", version="2.8.0+cu128",
               properties_error=None):
    """換上假的 torch：``card``（名稱、記憶體位元組、運算能力）是看得到的顯卡；沒有時
    ``is_available()`` 是 False，``init()`` 丟 ``init_error``。"""
    torch = types.ModuleType("torch")
    torch.__version__ = version
    torch.version = SimpleNamespace(cuda=cuda)
    calls = []

    def init():
        calls.append("init")
        if init_error is not None:
            raise init_error

    def get_device_properties(index):
        if properties_error is not None:
            raise properties_error
        return SimpleNamespace(name=card[0], total_memory=card[1])

    torch.cuda = SimpleNamespace(
        is_available=lambda: card is not None, init=init,
        get_device_properties=get_device_properties,
        get_device_capability=lambda index: card[2], get_arch_list=lambda: CU128_ARCHES)
    monkeypatch.setitem(sys.modules, "torch", torch)
    return calls


def torch_import_fails(monkeypatch, error: BaseException):
    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "torch":
            raise error
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(builtins, "__import__", failing_import)
