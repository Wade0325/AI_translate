"""app 的版本號（#85）：建置免安裝版時由 build_release.ps1 寫進發布包的 backend/VERSION，後端讀它。

版本號只在建置時注入（#24 的「單一版本來源」），所以 repo 裡沒有這個檔案；從原始碼執行
（Docker 模式、開發）時讀不到，版本號是 dev。build_release.ps1 在 Windows 上執行，CI 不跑，
這裡照 test_runtime_dirs_excluded.py 的做法讀它的文字，確認寫檔與結構檢查都還在。
"""
import re
from pathlib import Path

from app.core import version

ROOT = Path(__file__).resolve().parents[2]


def _release_script() -> str:
    return (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")


def test_reads_the_version_written_at_build(tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("v0.1.0-beta.1\n", encoding="utf-8")

    assert version.read_version(version_file) == "v0.1.0-beta.1"


def test_tolerates_a_utf8_bom(tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_bytes(b"\xef\xbb\xbfv0.1.0\r\n")

    assert version.read_version(version_file) == "v0.1.0"


def test_dev_when_not_built_from_a_release(tmp_path):
    assert version.read_version(tmp_path / "VERSION") == "dev"


def test_dev_when_the_file_is_blank(tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_text(" \n", encoding="utf-8")

    assert version.read_version(version_file) == "dev"


def test_version_file_sits_at_the_backend_root_and_is_not_committed():
    assert version.VERSION_FILE == ROOT / "backend" / "VERSION"
    # 進了 repo 的話，每個從原始碼執行的人都會看到一個不是自己在跑的版本號
    assert not version.VERSION_FILE.exists()


def test_release_build_writes_the_tag_into_the_package():
    script = _release_script()
    name = version.VERSION_FILE.name

    # 寫進發布包（$StageDir）而不是原始碼樹；PowerShell 5.1 的 utf8 會加 BOM，所以用 ascii
    assert re.search(
        r'Set-Content -Path \(Join-Path \$StageDir "backend\\' + name + r'"\)'
        r' -Value \$Version -Encoding ascii', script), \
        f"build_release.ps1 沒有把 -Version 寫進發布包的 backend\\{name}"
    # 打包前的結構檢查也要有它
    required = re.search(r"\$required = @\((.*?)\)", script, re.S)
    assert required and f'"backend\\{name}"' in required.group(1), \
        f"build_release.ps1 的結構檢查沒有列 backend\\{name}"
