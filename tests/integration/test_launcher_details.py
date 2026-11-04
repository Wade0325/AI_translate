"""Mimiji.exe 的「內容 → 詳細資料」與圖示（#277）。

- 版本號換成檔案版本的規則（build_release.ps1 的 ConvertTo-FileVersion）與建置時產生的 C# 檔
  （New-VersionInfoSource）：用 PowerShell 的語法樹從腳本取出函式執行（不另寫一份），和
  test_build_release_download.py 相同。Windows 用內建的 Windows PowerShell 5.1（和發版建置時相同），
  其他平台有 pwsh 時用 pwsh，都沒有時跳過。
- 圖示：tools/portable/mimiji.ico 是 ICO，有檔案總管與工作列會用到的尺寸。之後換圖示時這裡把關。
- 編譯：tools/launcher.cs 加上產生的 C# 檔與圖示，用 build_release.ps1 同樣的 csc 參數編譯。Windows 用
  內建 csc 編譯後，以 Windows 讀版本資訊的 API（tools/portable_zip.py 的 read_exe_info）讀出產品名稱、
  版本與圖示；其他平台裝了 Mono 時只編譯（-langversion:5 擋下內建 csc 不支援的語法）。
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from tools import portable_zip

ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "build_release.ps1"
LAUNCHER_SOURCE = ROOT / "tools" / "launcher.cs"
ICON = ROOT / "tools" / "portable" / "mimiji.ico"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
WINDOWS = sys.platform == "win32"

# 從 build_release.ps1 取出兩個函式：$InputFile 每一行是一個版本號，換成檔案版本後一行一個寫進
# $OutputFile（出錯時寫 ERROR 與訊息）；$SourceVersion 的 C# 檔寫進 $SourceFile。輸出都寫成 UTF-8 的檔案：
# Windows PowerShell 5.1 印到 stdout 時用系統碼頁，中文的錯誤訊息會變亂碼
HARNESS = r"""
param($BuildScript, $InputFile, $OutputFile, $SourceVersion, $SourceFile)
$ErrorActionPreference = "Stop"
$ast = [System.Management.Automation.Language.Parser]::ParseFile($BuildScript, [ref]$null, [ref]$null)
$isFunction = { param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }
foreach ($fn in $ast.FindAll($isFunction, $true)) {
    if (@("ConvertTo-FileVersion", "New-VersionInfoSource") -contains $fn.Name) {
        . ([scriptblock]::Create($fn.Extent.Text))
    }
}
$utf8 = New-Object Text.UTF8Encoding $false
$lines = foreach ($version in [IO.File]::ReadAllLines($InputFile, $utf8)) {
    try { ConvertTo-FileVersion $version } catch { "ERROR " + $_.Exception.Message }
}
[IO.File]::WriteAllLines($OutputFile, [string[]]@($lines), $utf8)
[IO.File]::WriteAllText($SourceFile, (New-VersionInfoSource $SourceVersion), (New-Object Text.UTF8Encoding $true))
"""

# 版本號 → 檔案版本（PR 內文的對照表）
FILE_VERSIONS = [
    ("v0.1.0", "0.1.0.0"),
    ("v0.1.0-rc.1", "0.1.0.0"),        # 預發布的標記不進檔案版本
    ("v0.1.0-beta.1", "0.1.0.0"),
    ("v1.2.3+build.5", "1.2.3.0"),
    ("0.2.3", "0.2.3.0"),              # v 可以省略
    ("V1.2.3", "1.2.3.0"),
    ("v01.002.0003", "1.2.3.0"),       # 前面的 0 不算
    ("v65534.0.1", "65534.0.1.0"),     # 組件版本每一段最大 65534
    ("dev", "0.0.0.0"),                # 本機建置的預設
    ("ci", "0.0.0.0"),                 # CI 的 portable job
    ("v1.2", "0.0.0.0"),               # 不是 vX.Y.Z 的寫法
    ("v1.2.3.4", "0.0.0.0"),
    ("v1.2.3rc1", "0.0.0.0"),
    ("v１.2.3", "0.0.0.0"),            # 全形數字不算
]
TOO_LARGE = ["v65535.0.0", "v1.2.9999999999"]


def _powershell() -> str | None:
    # Windows 先找 powershell.exe（5.1）：發版建置用的是它，不是 pwsh
    return shutil.which("powershell") or shutil.which("pwsh")


def _run_harness(tmp_path: Path, versions: list[str], source_version: str) -> tuple[list[str], Path]:
    """回傳每個版本號的檔案版本（或 ERROR 開頭的訊息），以及 source_version 產生的 C# 檔。"""
    shell = _powershell()
    if shell is None:
        pytest.skip("沒有 PowerShell")
    harness = tmp_path / "harness.ps1"
    harness.write_text(HARNESS, encoding="utf-8-sig")
    inputs, outputs, source = tmp_path / "versions.txt", tmp_path / "file-versions.txt", tmp_path / "version.cs"
    inputs.write_text("\n".join(versions) + "\n", encoding="utf-8")
    cmd = [shell, "-NoProfile", "-NonInteractive"]
    if os.name == "nt":
        cmd += ["-ExecutionPolicy", "Bypass"]
    cmd += ["-File", str(harness), str(BUILD_SCRIPT), str(inputs), str(outputs), source_version, str(source)]
    # 不沿用 PSModulePath：見 test_build_release_download.py
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                            env=env, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return outputs.read_text(encoding="utf-8").splitlines(), source


class TestFileVersion:
    def test_versions_become_four_numbers(self, tmp_path):
        found, _ = _run_harness(tmp_path, [v for v, _ in FILE_VERSIONS], "dev")

        assert list(zip([v for v, _ in FILE_VERSIONS], found, strict=True)) == FILE_VERSIONS

    @pytest.mark.parametrize("version", TOO_LARGE)
    def test_numbers_too_large_stop_the_build(self, tmp_path, version):
        # 版本資訊放不下：不默默寫成別的數字
        (found,), _ = _run_harness(tmp_path, [version], "dev")

        assert found.startswith("ERROR ")
        assert "65534" in found

    def test_source_has_the_numbers_and_the_whole_version(self, tmp_path):
        _, source = _run_harness(tmp_path, ["dev"], "v0.1.0-rc.1")

        text = source.read_text(encoding="utf-8-sig")
        assert '[assembly: System.Reflection.AssemblyVersion("0.1.0.0")]' in text
        assert '[assembly: System.Reflection.AssemblyFileVersion("0.1.0.0")]' in text
        assert '[assembly: System.Reflection.AssemblyInformationalVersion(@"v0.1.0-rc.1")]' in text

    def test_quote_in_version_stays_inside_the_string(self, tmp_path):
        # git 的 tag 可以有 "：C# 的逐字字串裡寫成 ""，不會讓編譯失敗或多出程式碼
        _, source = _run_harness(tmp_path, ["dev"], 'v1"x')

        assert '(@"v1""x")]' in source.read_text(encoding="utf-8-sig")


def _icon_sizes(data: bytes) -> list[int]:
    """ICO 檔裡每張圖的邊長；寬度寫 0 的是 256。"""
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1), "不是 ICO 檔"
    sizes = []
    for i in range(count):
        width, height, _, _, _, _, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        assert width == height
        assert offset + size <= len(data)
        sizes.append(width or 256)
    return sizes


def test_icon_has_the_sizes_windows_uses():
    # 檔案總管的各種檢視、工作列與標題列用 16、32、48 與 256；換圖示時至少要有這些
    assert {16, 32, 48, 256} <= set(_icon_sizes(ICON.read_bytes()))


def _has_compiler() -> bool:
    if WINDOWS:
        return CSC.is_file()
    return shutil.which("mcs") is not None


@pytest.mark.skipif(not _has_compiler(), reason="沒有 C# 編譯器（Windows 內建 csc，或 Mono）")
def test_compiled_launcher_shows_name_version_and_icon(tmp_path):
    _, source = _run_harness(tmp_path, ["dev"], "v0.1.0-rc.1")
    exe = tmp_path / "Mimiji.exe"
    # 和 build_release.ps1 第 5 步相同的參數
    if WINDOWS:
        cmd = [str(CSC), "/nologo", "/optimize", f"/win32icon:{ICON}", f"/out:{exe}", str(LAUNCHER_SOURCE),
               str(source)]
    else:
        cmd = ["mcs", "-langversion:5", "-optimize", f"-win32icon:{ICON}", f"-out:{exe}", str(LAUNCHER_SOURCE),
               str(source)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    if not WINDOWS:
        return  # 讀版本資訊要 Windows 的 API

    info = portable_zip.read_exe_info(exe)

    assert info is not None
    assert info.strings["ProductName"] == "Mimiji"
    assert info.strings["FileDescription"] == "Mimiji"  # 工作管理員顯示的名稱
    assert info.strings["ProductVersion"] == "v0.1.0-rc.1"
    assert info.strings["FileVersion"] == info.file_version == "0.1.0.0"
    assert info.strings["LegalCopyright"] in (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert info.strings["OriginalFilename"] == "Mimiji.exe"
    assert info.icons >= 1
    assert portable_zip.exe_problems(info, "Mimiji/Mimiji.exe", "v0.1.0-rc.1") == []
