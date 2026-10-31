"""build_release.ps1 的下載：驗 SHA-256，快取裡的檔案不符時刪掉重抓，不沿用（#266）。

執行 build_release.ps1 裡真的 Get-Verified：用 PowerShell 的語法樹從腳本取出函式定義（不另寫
一份），下載來源換成本機的 HTTP server。Windows 用內建的 Windows PowerShell 5.1（和 CI 的
portable job、release.yml 建置時相同），其他平台有 pwsh 時用 pwsh，都沒有時跳過。
"""
import hashlib
import http.server
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NAME = "asset.zip"
PINNED = b"the pinned release asset\n"
PINNED_SHA256 = hashlib.sha256(PINNED).hexdigest()

# 從 build_release.ps1 取出 Get-Verified 與它用到的函式，在 $CacheDir 下載 $Url
HARNESS = r"""
param($BuildScript, $CacheDir, $Url, $Name, $Sha256)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ast = [System.Management.Automation.Language.Parser]::ParseFile($BuildScript, [ref]$null, [ref]$null)
$isFunction = { param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }
foreach ($fn in $ast.FindAll($isFunction, $true)) {
    if (@("Step", "Get-SHA256", "Get-Verified") -contains $fn.Name) {
        . ([scriptblock]::Create($fn.Extent.Text))
    }
}
$path = Get-Verified $Url $Name $Sha256
Write-Output "RESULT=$path"
"""


def _powershell() -> str | None:
    # Windows 先找 powershell.exe（5.1）：發版建置用的是它，不是 pwsh
    return shutil.which("powershell") or shutil.which("pwsh")


pytestmark = pytest.mark.skipif(_powershell() is None, reason="沒有 PowerShell")


@dataclass
class _Server:
    url: str
    body: bytes = PINNED
    requests: list[str] = field(default_factory=list)


@pytest.fixture
def server() -> Iterator[_Server]:
    """本機的 HTTP server：每個 GET 都回 server.body，並記下路徑。"""
    state = _Server(url="")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(state.body)))
            self.end_headers()
            self.wfile.write(state.body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{httpd.server_address[1]}/{NAME}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def _get_verified(tmp_path: Path, url: str) -> subprocess.CompletedProcess[str]:
    harness = tmp_path / "harness.ps1"
    harness.write_text(HARNESS, encoding="utf-8-sig")
    shell = _powershell()
    assert shell
    cmd = [shell, "-NoProfile", "-NonInteractive"]
    if os.name == "nt":
        cmd += ["-ExecutionPolicy", "Bypass"]
    cmd += ["-File", str(harness), str(ROOT / "build_release.ps1"), str(tmp_path / "cache"),
            url, NAME, PINNED_SHA256]
    # 錯誤訊息是中文，Windows PowerShell 用系統碼頁輸出；只比對 ASCII 的部分
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                          timeout=120, check=False)


def _cached(tmp_path: Path) -> Path:
    return tmp_path / "cache" / NAME


def _returned_path(result: subprocess.CompletedProcess[str]) -> Path:
    lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT=")]
    assert len(lines) == 1, result.stdout
    return Path(lines[0].removeprefix("RESULT="))


def test_downloads_into_cache_when_nothing_is_cached(tmp_path, server):
    result = _get_verified(tmp_path, server.url)

    assert result.returncode == 0, result.stdout + result.stderr
    assert server.requests == [f"/{NAME}"]
    assert _cached(tmp_path).read_bytes() == PINNED
    assert _returned_path(result).samefile(_cached(tmp_path))
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == [NAME]


def test_uses_cached_file_without_downloading_when_hash_matches(tmp_path, server):
    _cached(tmp_path).parent.mkdir()
    _cached(tmp_path).write_bytes(PINNED)

    result = _get_verified(tmp_path, server.url)

    assert result.returncode == 0, result.stdout + result.stderr
    assert server.requests == []
    assert _returned_path(result).samefile(_cached(tmp_path))


def test_deletes_and_downloads_again_when_cached_hash_mismatches(tmp_path, server):
    # 上次下載中斷留下的半個檔案，或被換掉的檔案：不沿用
    _cached(tmp_path).parent.mkdir()
    _cached(tmp_path).write_bytes(PINNED[:5])

    result = _get_verified(tmp_path, server.url)

    assert result.returncode == 0, result.stdout + result.stderr
    assert server.requests == [f"/{NAME}"]
    assert _cached(tmp_path).read_bytes() == PINNED


def test_fails_and_keeps_nothing_when_download_hash_mismatches(tmp_path, server):
    server.body = b"a different file under the same url\n"

    result = _get_verified(tmp_path, server.url)

    assert result.returncode != 0
    # Windows PowerShell 5.1 印錯誤時會照視窗寬度斷行：去掉空白再找雜湊
    output = "".join((result.stdout + result.stderr).split())
    assert "SHA-256" in output
    assert hashlib.sha256(server.body).hexdigest() in output
    # 驗不過的檔案不留在快取：下次建置會重新下載，不會用到它
    assert list((tmp_path / "cache").iterdir()) == []
