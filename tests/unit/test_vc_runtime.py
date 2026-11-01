"""沒裝 Microsoft Visual C++ 可轉散發套件（或太舊）的 Windows 電腦，本機轉錄說清楚原因與下一步（#304）。

免安裝版只附 vcruntime140*.dll，torch 要的 msvcp140.dll、vcomp140.dll 從 System32 載入。從
:func:`weights.detect_gpu` 觀察：torch 換成載入失敗的假 torch，System32 換成測試的資料夾。
啟動器（tools/launcher.cs）在啟動伺服器前做同一個檢查：兩邊的清單、版本與連結要相同。
"""
import platform
import re
import sys
from pathlib import Path

import pytest

from app.core.error_codes import ErrorCode, describe
from app.provider.local import weights
from tests.support.fake_torch import DLL_LOAD_FAILED, torch_import_fails

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tools" / "launcher.cs"
STANDALONE_REQUIREMENTS = ROOT / "backend" / "requirements-standalone.txt"

MISSING = "PyTorch 載入失敗：這台電腦沒有 Microsoft Visual C++ 可轉散發套件"
INSTALL = "從 https://aka.ms/vc14/vc_redist.x64.exe 下載安裝後重新開啟 Mimiji，或改用 Gemini"


@pytest.fixture
def system32(monkeypatch, tmp_path) -> Path:
    """一台有 NVIDIA 驅動的 Windows 電腦，System32 一開始沒有 VC++ 可轉散發套件；torch 載入失敗。"""
    folder = tmp_path / "System32"
    folder.mkdir()
    (folder / "nvcuda.dll").write_bytes(b"")
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(weights, "_system32", lambda: folder)
    monkeypatch.setattr(weights, "command_output", lambda *command: None)
    torch_import_fails(monkeypatch, DLL_LOAD_FAILED)
    return folder


def install(folder: Path, version: tuple[int, int] | None, monkeypatch) -> None:
    for dll in weights.VC_RUNTIME_DLLS:
        (folder / dll).write_bytes(b"")
    monkeypatch.setattr(weights, "_file_version", lambda path: (
        version if path == folder / "msvcp140.dll" else None))


class TestMissing:
    def test_missing_runtime_says_where_to_download_it(self, system32):
        gpu = weights.detect_gpu()

        assert gpu.reason == "torch_load_failed"
        assert gpu.message == f"{MISSING}，本機轉錄不能用，{INSTALL}"
        assert gpu.detail.startswith("OSError:")
        with pytest.raises(weights.LocalNotReady) as caught:
            weights.ensure_local_ready()
        assert describe(caught.value).code == ErrorCode.LOCAL_TORCH_LOAD_FAILED

    @pytest.mark.parametrize("dll", weights.VC_RUNTIME_DLLS)
    def test_each_dll_is_required(self, system32, monkeypatch, dll):
        install(system32, (14, 44), monkeypatch)
        (system32 / dll).unlink()

        assert weights.detect_gpu().problem == MISSING

    def test_without_nvidia_driver_the_card_comes_first(self, system32):
        # 裝好 VC++ 之後本機轉錄也還是不能用：先說顯卡，下一步兩樣都寫
        (system32 / "nvcuda.dll").unlink()

        gpu = weights.detect_gpu()

        assert gpu.reason == "no_gpu"
        assert gpu.message == (
            "這台電腦沒有可用的 NVIDIA 顯卡（找不到 NVIDIA 驅動），本機轉錄不能用，可以改用 Gemini；"
            "有 NVIDIA 顯卡的話，裝好驅動與 Microsoft Visual C++ 可轉散發套件"
            "（https://aka.ms/vc14/vc_redist.x64.exe）後重新開啟 Mimiji")
        assert gpu.detail.startswith("OSError:")


class TestVersion:
    def test_old_runtime_says_both_versions(self, system32, monkeypatch):
        install(system32, (14, 29), monkeypatch)

        gpu = weights.detect_gpu()

        assert gpu.reason == "torch_load_failed"
        assert gpu.message == (
            "PyTorch 載入失敗：這台電腦的 Microsoft Visual C++ 可轉散發套件太舊（目前 14.29，"
            f"需要 14.38 以上），本機轉錄不能用，{INSTALL}")

    @pytest.mark.parametrize("version", [(14, 38), (14, 51), (15, 0)])
    def test_recent_runtime_is_not_blamed(self, system32, monkeypatch, version):
        install(system32, version, monkeypatch)

        assert weights.detect_gpu().problem == "PyTorch 載入失敗"

    def test_unreadable_version_is_not_called_old(self, system32, monkeypatch):
        install(system32, None, monkeypatch)

        assert weights.detect_gpu().problem == "PyTorch 載入失敗"

    def test_the_minimum_was_checked_for_the_shipped_torch(self):
        # 最低版本是照 torch 2.8.0+cu128（Windows）的 DLL 由 linker 14.38 連結查的：
        # 免安裝版換了 torch，就要重讀新版 DLL 的 PE 標頭，重訂 VC_RUNTIME_MIN_VERSION
        pinned = re.search(r"^torch==(\S+)", STANDALONE_REQUIREMENTS.read_text(encoding="utf-8"),
                           re.MULTILINE)
        assert pinned and pinned.group(1) == weights.VC_RUNTIME_TABLE_TORCH


class TestFileVersion:
    @pytest.mark.skipif(sys.platform != "win32", reason="要 Windows 的 version.dll")
    def test_reads_the_file_version_of_a_windows_executable(self):
        python = Path(sys.base_prefix) / "python.exe"

        assert weights._file_version(python) == sys.version_info[:2]

    @pytest.mark.skipif(sys.platform != "win32", reason="要 Windows 的 version.dll")
    def test_a_file_without_version_information_is_none(self, tmp_path):
        plain = tmp_path / "msvcp140.dll"
        plain.write_bytes(b"not a PE file")

        assert weights._file_version(plain) is None

    def test_other_platforms_do_not_read_it(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")

        assert weights._file_version(tmp_path / "msvcp140.dll") is None


def test_other_platforms_never_blame_the_runtime(monkeypatch, tmp_path):
    # Docker 模式的 GPU worker 是 Linux
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(weights, "_system32", lambda: tmp_path)

    assert weights._vc_runtime_problem() is None


class TestLauncherAgrees:
    """啟動器在伺服器啟動前提示，轉錄頁在 torch 載入失敗後說明：兩邊看的東西要一樣。"""

    source = LAUNCHER.read_text(encoding="utf-8")

    def test_same_dlls(self):
        listed = re.search(r"VcRuntimeDlls = \{([^}]*)\}", self.source)
        assert listed
        assert tuple(re.findall(r'"([^"]+)"', listed.group(1))) == weights.VC_RUNTIME_DLLS

    def test_same_minimum_version(self):
        major = re.search(r"const int VcRuntimeMinMajor = (\d+);", self.source)
        minor = re.search(r"const int VcRuntimeMinMinor = (\d+);", self.source)
        assert major and minor
        assert (int(major.group(1)), int(minor.group(1))) == weights.VC_RUNTIME_MIN_VERSION

    def test_same_download_link(self):
        assert f'const string VcRedistUrl = "{weights.VC_REDIST_URL}";' in self.source

    def test_same_sign_of_an_nvidia_driver(self):
        assert '"nvcuda.dll"' in self.source
