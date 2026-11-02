"""發布包附的授權文件（#274）：NOTICE、tools/portable/THIRD_PARTY_NOTICES.txt 與 tools/portable/licenses/。

THIRD_PARTY_NOTICES.txt 寫明每個隨包元件的版本與來源；元件升版（build_release.ps1 的釘版）而沒有更新
聲明時，這裡紅燈。licenses/ 的每一個檔案都要在聲明裡指得到、都在 build_release.ps1 第 7 步的清單裡
（CI 建置免安裝版之後照那份清單檢查 zip，tools/portable_zip.py）。授權文字和下載來的元件是否相同，
建置時由 build_release.ps1 的 Assert-SameText 檢查，ffmpeg 的部分另外由 tools/ffmpeg_sources.py 檢查。
"""
import re
from pathlib import Path, PureWindowsPath

from tools import ffmpeg_sources, portable_zip

ROOT = Path(__file__).resolve().parents[2]
PORTABLE = ROOT / "tools" / "portable"
LICENSES = PORTABLE / "licenses"


def _script() -> str:
    return (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")


def _variable(name: str) -> str:
    found = re.findall(rf'^\${name} = "([^"]*)"', _script(), re.M)
    assert len(found) == 1, f"build_release.ps1 的 ${name} 應該剛好一個：{found}"
    return found[0]


def _notices() -> str:
    return (PORTABLE / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")


def _referenced_licenses() -> set[str]:
    """THIRD_PARTY_NOTICES.txt 指到的 licenses\\ 底下的檔案，用 /、相對於 licenses/。"""
    paths = re.findall(r"licenses\\(\S+\.txt)", _notices())
    return {PureWindowsPath(p).as_posix() for p in paths}


def _license_files() -> set[str]:
    return {p.relative_to(LICENSES).as_posix() for p in LICENSES.rglob("*") if p.is_file()}


class TestPlaceholders:
    def test_only_placeholder_is_version(self):
        # build_release.ps1 只換 {VERSION}；其他的大括號字樣會原樣出現在使用者看到的檔案裡
        assert set(re.findall(r"\{[A-Z_]+\}", _notices())) == {"{VERSION}"}

    def test_source_offer_points_to_this_versions_release(self):
        assert "https://github.com/Wade0325/AI_translate/releases/tag/{VERSION}" in _notices()


class TestComponentsMatchTheBuild:
    """聲明寫的版本與來源，和 build_release.ps1 實際打包的相同。"""

    def test_ffmpeg(self):
        pins = ffmpeg_sources.pins(_script())
        notices = _notices()

        for value in (pins.build.removeprefix("ffmpeg-"), pins.ffmpeg_commit, pins.tag,
                      pins.btbn_commit, pins.sha256):
            assert value in notices, value
        # 原始碼附件的檔名：發版 workflow（#278）照 tools/ffmpeg_sources.py 產生的檔名上傳
        for asset in pins.release_assets:
            assert f"\n    {asset}\n" in notices, asset

    def test_ffmpeg_required_statements(self):
        notices = _notices()

        # ffmpeg.org 的授權檢查清單與 FFmpeg 的 LICENSE.md（#80 的研究 §2.3 d、§2.4）
        assert "This software uses code of FFmpeg" in notices
        assert "This software is based in part on the work of the Independent JPEG Group." in notices
        assert "licenses\\ffmpeg\\COPYING.LGPLv3.txt" in notices
        assert "licenses\\ffmpeg\\COPYING.GPLv3.txt" in notices
        # 拼法：名稱寫 FFmpeg（兩個大寫 F、小寫 mpeg），全小寫的只有檔名與網址；不出現 FFMPEG、Ffmpeg
        spellings = set(re.findall(r"(?i)ffmpeg", notices))
        assert spellings == {"FFmpeg", "ffmpeg"}

    def test_python(self):
        version = _variable("PythonEmbedVersion")

        assert f"Python {version} embeddable package" in _notices()
        assert f"python-{version}-embed-amd64.zip" in _notices()

    def test_uv(self):
        version = _variable("UvVersion")
        copyright_line = next(line for line in (LICENSES / "uv" / "LICENSE-MIT.txt").read_text(
            encoding="utf-8").splitlines() if line.startswith("Copyright"))

        assert f"uv {version}" in _notices()
        assert f"releases/tag/{version}" in _notices()
        assert copyright_line in _notices()


class TestLicenseFiles:
    def test_every_file_is_referenced_by_the_notices(self):
        assert _license_files() == _referenced_licenses()

    def test_every_file_is_checked_in_the_built_zip(self):
        required = portable_zip.required_files(_script())

        assert {f"licenses/{rel}" for rel in _license_files()} <= set(required)
        assert {"LICENSE.txt", "NOTICE.txt", "THIRD_PARTY_NOTICES.txt"} <= set(required)

    def test_texts_are_the_licenses_the_notices_name(self):
        def head(rel: str) -> str:
            return (LICENSES / rel).read_text(encoding="utf-8")[:2000]

        assert "GNU LESSER GENERAL PUBLIC LICENSE" in head("ffmpeg/COPYING.LGPLv3.txt")
        assert "Version 3" in head("ffmpeg/COPYING.LGPLv3.txt")
        assert "GNU GENERAL PUBLIC LICENSE" in head("ffmpeg/COPYING.GPLv3.txt")
        assert "Version 3" in head("ffmpeg/COPYING.GPLv3.txt")
        assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in (
            LICENSES / "python" / "LICENSE.txt").read_text(encoding="utf-8")
        assert head("uv/LICENSE-MIT.txt").startswith("MIT License")
        assert "Apache License" in head("uv/LICENSE-APACHE.txt")


def test_notice_names_the_license_and_the_third_party_notices():
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")

    assert "Apache License, Version 2.0" in notice
    assert "THIRD_PARTY_NOTICES.txt" in notice
    # 發布包裡以 NOTICE.txt 出現，記事本要讀得對：只用 ASCII
    assert notice.isascii()
