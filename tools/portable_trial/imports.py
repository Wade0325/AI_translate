"""試發布（#35）：用免安裝版佈建好的 runtime\\python.exe 逐一 import 執行要用到的套件。

用法（由 run_trial.py 呼叫）：

    runtime\\python.exe imports.py <backend 資料夾> <輸出的 JSON>

記下每個模組 import 花的秒數與錯誤、torch 看到的 CUDA，以及 import 完之後行程載入了哪些 DLL、
從哪裡載入：沒有 VC++ 執行階段的電腦上，從 C:\\Windows\\System32 載入的 msvcp140.dll 之類就會找不到。
只用標準函式庫（免安裝版的 runtime 裡沒有別的）。
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

MODULES = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "google.genai",
    "opencc",
    "soundfile",
    "numpy",
    "torch",
    "torchaudio",
    "silero_vad",
    "av",
    "librosa",
    "huggingface_hub",
    "transformers",
    "accelerate",
    "bitsandbytes",
    "moss_transcribe_diarize",
    "app.provider.local.moss",
    "app.provider.local.asr",
)


def loaded_modules() -> list[str]:
    """這個行程目前載入的每一個 DLL 的完整路徑。"""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.EnumProcessModules.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    psapi.GetModuleFileNameExW.argtypes = [
        wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    process = kernel32.GetCurrentProcess()
    handles = (wintypes.HMODULE * 8192)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcessModules(process, handles, ctypes.sizeof(handles), ctypes.byref(needed)):
        return []
    count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), len(handles))
    buffer = ctypes.create_unicode_buffer(32768)
    paths = []
    for i in range(count):
        if psapi.GetModuleFileNameExW(process, handles[i], buffer, len(buffer)):
            paths.append(buffer.value)
    return paths


def main() -> int:
    backend, out = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, str(backend))
    os.environ.setdefault("APP_MODE", "standalone")
    results: dict[str, object] = {"python": sys.version, "executable": sys.executable}
    modules = []
    for name in MODULES:
        started = time.perf_counter()
        entry: dict[str, object] = {"module": name}
        try:
            module = importlib.import_module(name)
            entry["ok"] = True
            entry["version"] = getattr(module, "__version__", None)
        except Exception as e:  # 每一個都要記下來，不中斷
            entry["ok"] = False
            entry["error"] = f"{type(e).__name__}: {e}"
            entry["traceback"] = traceback.format_exc()[-3000:]
        entry["seconds"] = round(time.perf_counter() - started, 2)
        modules.append(entry)
    results["modules"] = modules

    try:
        import torch

        results["torch"] = {
            "version": torch.__version__,
            "cuda_build": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count(),
            "cpu_matmul": float((torch.ones(4, 4) @ torch.ones(4, 4)).sum()),
        }
    except Exception as e:
        results["torch"] = {"error": f"{type(e).__name__}: {e}"}

    results["loaded_dlls"] = loaded_modules()
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(m["ok"] for m in modules) else 1


if __name__ == "__main__":
    sys.exit(main())
