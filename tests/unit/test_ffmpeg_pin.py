"""免安裝版打包的 ffmpeg 和 CI 測的是同一個（#17、#129）。

兩邊都用 BtbN 的 LGPL build，以日期 tag 釘版並驗 SHA-256：CI 的設定在 .github/workflows/ci.yml，
打包在 build_release.ps1。升版時兩邊要一起換，少換一邊這裡會紅燈。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ci_pin() -> dict[str, str]:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pin = {}
    for key in ("FFMPEG_TAG", "FFMPEG_BUILD", "SHA256_WINDOWS"):
        found = re.findall(rf"^\s*{key}: (\S+)$", text, re.M)
        assert len(found) == 1, f"ci.yml 的 {key} 應該剛好一個：{found}"
        pin[key] = found[0]
    return pin


def _release_variable(name: str) -> str:
    text = (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")
    found = re.findall(rf'^\${name} = "([^"]*)"', text, re.M)
    assert len(found) == 1, f"build_release.ps1 的 ${name} 應該剛好一個：{found}"
    return found[0]


def test_release_bundles_the_build_ci_tests():
    ci = _ci_pin()
    assert _release_variable("FfmpegTag") == ci["FFMPEG_TAG"]
    assert _release_variable("FfmpegBuild") == ci["FFMPEG_BUILD"]
    assert _release_variable("FfmpegSha256") == ci["SHA256_WINDOWS"]


def test_release_downloads_the_pinned_lgpl_zip():
    # 不是 releases/latest，也不是 GPL build
    assert _release_variable("FfmpegAsset") == "$FfmpegBuild-win64-lgpl-9.0.zip"
    assert _release_variable("FfmpegUrl") == (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/$FfmpegTag/$FfmpegAsset")
