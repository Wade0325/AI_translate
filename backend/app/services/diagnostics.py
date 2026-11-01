"""設定頁「複製診斷資訊」的內容（#24）：使用者回報問題時貼進 GitHub Issue。

app 不自動回傳任何東西（ADR-0005），所以排查只能靠使用者主動附上的資訊；這段文字讓使用者一鍵
複製，自己決定貼不貼。

只寫這台電腦與 app 的狀態：版本、執行模式、作業系統、Python 與主要套件、顯卡與驅動、本機模型
權重、ffmpeg 與磁碟剩餘空間。去識別的做法和日誌檔相同（#231），是一開始就不拿：

- **不讀資料庫**：原檔名、提示詞、轉錄結果與 API 金鑰都在資料庫裡，這裡不碰它。
- **不寫路徑**：data 資料夾、模型權重與 ffmpeg 的路徑常帶著帳號名稱。
- **不寫電腦名稱與使用者名稱**：作業系統只寫名稱、版本與架構。
"""

from __future__ import annotations

import platform
import shutil
from collections.abc import Iterator
from pathlib import Path

from app.core.config import get_settings
from app.core.version import APP_VERSION
from app.provider.local import weights
from app.provider.local.provider import vram_notice
from app.services.environment_manifest import PACKAGES, package
from app.utils.binaries import ffmpeg_bin
from app.utils.commands import command_output

TITLE = "診斷資訊"

DIAGNOSED_PACKAGES = (*PACKAGES, "google-genai")
"""轉錄結果會隨版本改變的套件，加上 Gemini 的用戶端。"""

Line = tuple[str, str]


def report() -> str:
    """設定頁複製的整段文字：第一行是標題，之後每項一行「- 項目：值」，貼進 Issue 會變成清單。"""
    return "\n".join([TITLE, *(f"- {label}：{value}" for label, value in lines())]) + "\n"


def lines() -> Iterator[Line]:
    settings = get_settings()
    yield "版本", APP_VERSION
    yield "執行模式", "免安裝模式" if settings.is_standalone else "Docker 模式"
    yield "作業系統", operating_system()
    yield "Python", platform.python_version()
    yield "套件", "、".join(f"{name} {package(name)['version'] or '未安裝'}"
                          for name in DIAGNOSED_PACKAGES)
    if settings.is_standalone:
        yield from local_transcription()
    else:
        # Docker 模式的本機轉錄在主機的 GPU worker：API 容器看到的不是它的顯卡與模型權重
        # （和設定頁的「測試」、轉錄頁的事前檢查相同，見 api/local_models.py）
        yield "本機轉錄", "Docker 模式在主機的 GPU worker 轉錄，這裡看不到它的顯卡與模型權重"
    yield "ffmpeg", ffmpeg_version() or "找不到"
    if settings.is_standalone:
        yield "data 資料夾所在磁碟的剩餘空間", free_space(settings.data_path)


def free_space(folder: Path) -> str:
    """資料夾所在磁碟的剩餘空間（GB）：模型權重要好幾 GB，長音檔轉成的 wav 也不小。"""
    try:
        return f"{shutil.disk_usage(folder).free / 1024 ** 3:.1f} GB"
    except OSError:
        return "讀不到"


def operating_system() -> str:
    """名稱、版本與架構，例如 ``Windows 11（10.0.26100，AMD64）``。

    不用 ``platform.uname()`` 整組或 ``platform.node()``：裡面有電腦名稱。
    """
    system, version = platform.system(), platform.version()
    return f"{system} {release(system, platform.release(), version)}（{version}，{platform.machine()}）"


WINDOWS_11_FIRST_BUILD = 22000


def release(system: str, reported: str, version: str) -> str:
    """作業系統的版本名稱。免安裝版的 Python 3.11 在 Windows 11 上回報 10（3.12 才修），照組建號
    改正：Windows 11 的組建號從 22000 開始（``10.0.22000``）。"""
    if system == "Windows" and reported == "10":
        build = version.split(".")[2:3]
        if build and build[0].isdigit() and int(build[0]) >= WINDOWS_11_FIRST_BUILD:
            return "11"
    return reported


def local_transcription() -> Iterator[Line]:
    """本機轉錄要的東西：驅動、顯卡、顯卡記憶體的提示與模型權重（只在免安裝模式問）。

    驅動和顯卡分開問：PyTorch 用不了顯卡時，nvidia-smi 可能照樣找得到卡。用不了的原因和轉錄頁、
    設定頁是同一份判斷（:func:`weights.detect_gpu`，#262），另外附上 PyTorch 的原始錯誤。
    """
    yield "NVIDIA 驅動", weights.nvidia_driver_version() or "找不到 nvidia-smi"
    gpu = weights.detect_gpu()
    if isinstance(gpu, weights.GpuUnavailable):
        yield "顯卡", gpu.problem
        if gpu.detail:
            yield "PyTorch 的錯誤", gpu.detail
    else:
        unsupported = "" if gpu.supported else "，目前的 PyTorch 不支援這張顯卡"
        yield "顯卡", f"{gpu.name}（{round(gpu.vram_gb)} GB{unsupported}）"
        notice = vram_notice(None)
        if notice:
            yield "顯卡記憶體", notice

    ready = {repo: weights.repo_is_ready(repo) for repo in weights.ALL_REPOS}
    for model, repos in weights.MODEL_REPOS.items():
        missing = [repo for repo in repos if not ready[repo]]
        label = f"模型權重 {model}" + ("（預設）" if model == weights.DEFAULT_LOCAL_MODEL else "（選用）")
        yield label, "已下載" if not missing else "缺少 " + "、".join(missing)


def ffmpeg_version() -> str | None:
    """``ffmpeg -version`` 第一行的版本（``ffmpeg version <版本> Copyright …``）；找不到時是 None。

    只取版本那一段：後面幾行是編譯設定，用不到。
    """
    output = command_output(ffmpeg_bin(), "-version")
    words = output.split(maxsplit=3) if output else []
    if words[:2] != ["ffmpeg", "version"] or len(words) < 3:
        return None
    return words[2]
