"""免安裝版打包時下載的 Python embeddable 與 uv 都釘版並驗 SHA-256（#266）。

build_release.ps1 下載的每一個檔案都要經過 Get-Verified（驗 SHA-256，快取不符時刪掉重抓），
不准抓 releases/latest 之類會變動的網址。uv 和 CI（.github/workflows/ci.yml 的 docker job）
用同一版，升版時兩邊要一起換，少換一邊這裡會紅燈。ffmpeg 的釘版在 test_ffmpeg_pin.py。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHA256 = re.compile(r"[0-9a-f]{64}")


def _script() -> str:
    return (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")


def _release_variable(name: str) -> str:
    found = re.findall(rf'^\${name} = "([^"]*)"', _script(), re.M)
    assert len(found) == 1, f"build_release.ps1 的 ${name} 應該剛好一個：{found}"
    return found[0]


def test_uv_is_the_version_ci_uses():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    found = re.findall(r"pip install uv==(\S+)$", text, re.M)
    assert len(found) == 1, f"ci.yml 安裝 uv 的地方應該剛好一個：{found}"
    assert _release_variable("UvVersion") == found[0]


def test_uv_downloads_the_pinned_release_and_checks_its_hash():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _release_variable("UvVersion"))
    assert _release_variable("UvAsset") == "uv-x86_64-pc-windows-msvc.zip"
    # 不是 releases/latest
    assert _release_variable("UvUrl") == (
        "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvAsset")
    assert SHA256.fullmatch(_release_variable("UvSha256"))


def test_python_embed_downloads_the_pinned_release_and_checks_its_hash():
    version = _release_variable("PythonEmbedVersion")
    # 第 2 步寫的 python311._pth 與 python311.zip 綁定 3.11
    assert re.fullmatch(r"3\.11\.\d+", version)
    assert "python311._pth" in _script()
    assert _release_variable("PythonEmbedAsset") == "python-$PythonEmbedVersion-embed-amd64.zip"
    assert _release_variable("PythonEmbedUrl") == (
        "https://www.python.org/ftp/python/$PythonEmbedVersion/$PythonEmbedAsset")
    assert SHA256.fullmatch(_release_variable("PythonEmbedSha256"))


def test_every_download_is_verified_against_its_own_hash():
    script = _script()
    urls = set(re.findall(r'^\$(\w+)Url = "https://', script, re.M))
    assert urls == {"PythonEmbed", "Uv", "Ffmpeg"}

    # 每一個網址都經過 Get-Verified，配的是同一個名稱的 SHA-256
    calls = re.findall(r"Get-Verified \$(\w+)Url \S+ \$(\w+)Sha256$", script, re.M)
    assert sorted(url for url, _ in calls) == sorted(urls)
    assert all(url == sha for url, sha in calls), calls

    # 只有 Get-Verified 裡會下載；沒有不驗雜湊的下載，也沒有會變動的網址。註解不算
    code = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    downloads = [line for line in code if re.search(r"Invoke-WebRequest|Start-BitsTransfer|curl|wget", line)]
    assert downloads == ["    Invoke-WebRequest -Uri $url -OutFile $part -UseBasicParsing"]
    assert not [line for line in code if "/latest" in line]
