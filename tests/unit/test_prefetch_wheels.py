"""首次佈建前先下載 torch 的 wheel，斷線之後可以接著下載（tools/portable/prefetch_wheels.py，#303）。

用本機的 HTTP 伺服器當下載來源：照測試的設定在傳到一半時切斷連線、暫時連不上、不支援續傳、
回錯誤狀態。檢查斷線之後只下載還沒下載的部分（Range 的起點與伺服器實際送出的量）、驗 SHA-256、
結束代碼與給使用者看的訊息。釘住的版本和 requirements-standalone.txt 與 build_release.ps1 一致。
"""
from __future__ import annotations

import errno
import hashlib
import io
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tools import portable_zip
from tools.portable import prefetch_wheels as prefetch
from tools.portable.prefetch_wheels import Wheel

ROOT = Path(__file__).resolve().parents[2]
FILENAME = "torch-2.8.0+cu128-cp311-cp311-win_amd64.whl"
PAYLOAD = bytes(range(256)) * (3 * 1024 * 4 + 7)  # 約 3 MB：好幾次 CHUNK
MB = 1024 * 1024


@dataclass
class Server:
    """下載來源。cut_after 依序套用在每一次回應：送出這麼多位元組的內容就切斷（None 是送完）。"""

    payload: bytes = PAYLOAD
    cut_after: list[int | None] = field(default_factory=list)
    down: bool = False  # 連上之後什麼都不回就關掉（網路斷了）
    statuses: list[int] = field(default_factory=list)  # 先依序回這些狀態，用完才正常回應
    ignore_range: bool = False
    content_length: int | None = None  # 回應裡宣稱的大小；None 是照實
    ranges: list[str | None] = field(default_factory=list)  # 每一次請求的 Range
    sent: int = 0  # 實際送出的內容位元組
    url: str = ""


def _handler(server: Server) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            server.ranges.append(self.headers.get("Range"))
            if server.down:
                self.close_connection = True
                return
            if server.statuses:
                self.send_response(server.statuses.pop(0))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data, start = server.payload, 0
            requested = self.headers.get("Range")
            if requested and not server.ignore_range:
                start = int(re.fullmatch(r"bytes=(\d+)-", requested).group(1))
                if start >= len(data):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(data)}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            else:
                self.send_response(200)
            body = data[start:]
            length = server.content_length if server.content_length is not None else len(body)
            self.send_header("Content-Length", str(length))
            self.end_headers()
            cut = server.cut_after.pop(0) if server.cut_after else None
            body = body if cut is None else body[:cut]
            self.wfile.write(body)
            server.sent += len(body)
            if cut is not None:
                self.wfile.flush()
                self.close_connection = True

    return Handler


class _Quiet(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # 下載端提早關掉連線時，伺服器這邊寫不出去是預期的


@pytest.fixture
def server():
    state = Server()
    httpd = _Quiet(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{httpd.server_address[1]}/whl/{urllib.parse.quote(FILENAME)}"
    yield state
    httpd.shutdown()
    httpd.server_close()


def _wheel(server: Server, *, sha256: str | None = None, size: int | None = None) -> Wheel:
    return Wheel(label="PyTorch", url=server.url,
                 size=size if size is not None else len(server.payload),
                 sha256=sha256 or hashlib.sha256(server.payload).hexdigest())


# 不經過環境變數設的代理伺服器：下載來源是本機
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({})).open

Run = namedtuple("Run", "code output sleeps")


def _run(folder: Path, wheel: Wheel, open_url=_direct) -> Run:
    out, sleeps = io.StringIO(), []
    code = prefetch.main([str(folder)], wheels=[wheel], open_url=open_url, out=out,
                         sleep=sleeps.append)
    return Run(code, out.getvalue(), sleeps)


def _files(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in folder.iterdir()} if folder.exists() else {}


class TestDownload:
    def test_downloads_the_wheel_and_checks_its_hash(self, server, tmp_path):
        result = _run(tmp_path / "downloads", _wheel(server))

        assert result.code == 0
        # 只留驗過的 wheel：資料夾直接給 uv 的 --find-links
        assert _files(tmp_path / "downloads") == {FILENAME: PAYLOAD}
        assert server.ranges == [None]
        assert result.sleeps == []

    def test_resumes_where_the_connection_dropped(self, server, tmp_path):
        server.cut_after = [MB + 123]

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert _files(tmp_path) == {FILENAME: PAYLOAD}
        # 第二次只要還沒下載的部分，伺服器總共只送了一份
        assert server.ranges == [None, f"bytes={MB + 123}-"]
        assert server.sent == len(PAYLOAD)
        assert result.sleeps == [prefetch.RETRY_DELAYS[0]]
        assert "連線中斷" in result.output and "秒後重試（第 1/5 次）" in result.output

    def test_keeps_retrying_while_each_attempt_gets_further(self, server, tmp_path):
        # 每次只下載到一點就斷：連續失敗的次數每次都重新算，不會用完重試就放棄
        server.cut_after = [300_000] * (len(prefetch.RETRY_DELAYS) + 3)

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert _files(tmp_path) == {FILENAME: PAYLOAD}
        assert server.sent == len(PAYLOAD)
        assert set(result.sleeps) == {prefetch.RETRY_DELAYS[0]}

    def test_server_that_ignores_the_range_starts_over(self, server, tmp_path):
        (tmp_path / f"{FILENAME}.part").write_bytes(PAYLOAD[:MB])
        server.ignore_range = True

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert _files(tmp_path) == {FILENAME: PAYLOAD}
        assert server.ranges == [f"bytes={MB}-"]

    def test_temporary_server_errors_are_retried(self, server, tmp_path):
        server.statuses = [503]

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert result.sleeps == [prefetch.RETRY_DELAYS[0]]
        assert "HTTP 503" in result.output

    def test_progress_is_printed_in_steps_when_not_a_console(self, server, tmp_path):
        result = _run(tmp_path, _wheel(server))

        lines = [line for line in result.output.splitlines() if line.startswith("  PyTorch：")]
        assert lines and lines[-1].endswith("（100%）")
        assert len(lines) <= 11


class TestInterrupted:
    def test_gives_up_after_the_retries_and_keeps_what_it_downloaded(self, server, tmp_path):
        server.cut_after = [MB]
        server.statuses = []

        def drop_after_first(request, timeout):
            if server.ranges:
                server.down = True
            return _direct(request, timeout=timeout)

        result = _run(tmp_path, _wheel(server), open_url=drop_after_first)

        assert result.code == prefetch.EXIT_INTERRUPTED
        assert result.sleeps == list(prefetch.RETRY_DELAYS)
        assert _files(tmp_path) == {f"{FILENAME}.part": PAYLOAD[:MB]}
        assert "PyTorch 下載中斷" in result.output
        assert "已下載的 1 MB 會保留，下次從這裡接著下載" in result.output

    def test_next_run_downloads_only_the_rest(self, server, tmp_path):
        (tmp_path / f"{FILENAME}.part").write_bytes(PAYLOAD[:MB])

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert _files(tmp_path) == {FILENAME: PAYLOAD}
        assert server.ranges == [f"bytes={MB}-"]
        assert server.sent == len(PAYLOAD) - MB
        assert "從上次中斷的地方接著下載 PyTorch" in result.output

    def test_complete_part_is_checked_without_downloading(self, server, tmp_path):
        # 上次下載完、還沒驗就被關掉
        (tmp_path / f"{FILENAME}.part").write_bytes(PAYLOAD)

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert _files(tmp_path) == {FILENAME: PAYLOAD}
        assert server.ranges == []



class TestFallback:
    """這個來源下載不到時不重試，交給 uv 照原本的方式下載：首次佈建不會比沒有這一步時更容易失敗。"""

    def test_missing_file_falls_back_to_uv(self, server, tmp_path):
        (tmp_path / f"{FILENAME}.part").write_bytes(PAYLOAD[:MB])
        server.statuses = [404]

        result = _run(tmp_path, _wheel(server))

        assert result.code == prefetch.EXIT_FALLBACK
        assert result.sleeps == []
        assert "伺服器回應 HTTP 404" in result.output
        assert "改由 uv 照原本的方式下載" in result.output
        # 可能只是暫時的：下載過的部分留著
        assert _files(tmp_path) == {f"{FILENAME}.part": PAYLOAD[:MB]}

    def test_certificate_that_cannot_be_verified_falls_back_to_uv(self, tmp_path):
        def untrusted(request, timeout):
            error = ssl.SSLCertVerificationError(1, "certificate verify failed")
            error.verify_message = "unable to get local issuer certificate"
            raise urllib.error.URLError(error)

        wheel = Wheel("PyTorch", f"https://download.pytorch.org/whl/cu128/{FILENAME}", 10, "0" * 64)
        result = _run(tmp_path, wheel, open_url=untrusted)

        assert result.code == prefetch.EXIT_FALLBACK
        assert result.sleeps == []
        assert "無法驗證 download.pytorch.org 的憑證（unable to get local issuer certificate）" in result.output

    @pytest.mark.parametrize("downloaded", [0, MB], ids=["fresh", "resumed"])
    def test_server_with_a_different_size_falls_back_before_downloading(self, server, tmp_path,
                                                                       downloaded):
        if downloaded:
            (tmp_path / f"{FILENAME}.part").write_bytes(PAYLOAD[:downloaded])
        server.content_length = len(PAYLOAD) - downloaded + 1

        result = _run(tmp_path, _wheel(server))

        assert result.code == prefetch.EXIT_FALLBACK
        assert server.sent <= len(PAYLOAD)
        # 不是同一個檔案：下載過的部分也不能用
        assert _files(tmp_path) == {}


class TestVerification:
    def test_wrong_hash_deletes_the_download(self, server, tmp_path):
        result = _run(tmp_path, _wheel(server, sha256="0" * 64))

        assert result.code == prefetch.EXIT_MISMATCH
        assert _files(tmp_path) == {}
        assert "和預期的不同" in result.output and "下次會重新下載" in result.output

    def test_corrupted_part_is_not_trusted(self, server, tmp_path):
        (tmp_path / f"{FILENAME}.part").write_bytes(b"\0" * MB)

        result = _run(tmp_path, _wheel(server))

        assert result.code == prefetch.EXIT_MISMATCH
        assert _files(tmp_path) == {}

    def test_part_larger_than_the_file_starts_over(self, server, tmp_path):
        (tmp_path / f"{FILENAME}.part").write_bytes(PAYLOAD + b"extra")

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert _files(tmp_path) == {FILENAME: PAYLOAD}
        assert server.ranges == [None]

    def test_part_the_server_says_is_past_the_end_starts_over(self, server, tmp_path):
        # 伺服器回 416（起點不在檔案裡），.part 卻沒有檔案那麼大：不是這個檔案的
        (tmp_path / f"{FILENAME}.part").write_bytes(PAYLOAD[:MB])
        server.statuses = [416]

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert server.ranges == [f"bytes={MB}-", None]
        assert _files(tmp_path) == {FILENAME: PAYLOAD}

    def test_verified_wheel_from_last_time_is_used_without_downloading(self, server, tmp_path):
        (tmp_path / FILENAME).write_bytes(PAYLOAD)

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert server.ranges == []
        assert "上次已經下載好了" in result.output

    def test_damaged_wheel_from_last_time_is_downloaded_again(self, server, tmp_path):
        (tmp_path / FILENAME).write_bytes(PAYLOAD[:-1] + b"?")

        result = _run(tmp_path, _wheel(server))

        assert result.code == 0
        assert _files(tmp_path) == {FILENAME: PAYLOAD}
        assert server.ranges == [None]


class TestDisk:
    def test_not_enough_space_stops_before_downloading(self, server, tmp_path, monkeypatch):
        usage = namedtuple("usage", "total used free")
        monkeypatch.setattr(prefetch.shutil, "disk_usage", lambda path: usage(0, 0, 10))

        result = _run(tmp_path, _wheel(server))

        assert result.code == prefetch.EXIT_DISK
        assert server.ranges == []
        assert "磁碟空間不足" in result.output

    def test_write_failure_keeps_what_was_written(self, server, tmp_path, monkeypatch):
        real_open = Path.open

        class FullDisk(io.BufferedWriter):
            def write(self, data):
                if self.tell() >= MB:
                    raise OSError(errno.ENOSPC, "No space left on device")
                return super().write(data)

        def open_part(path, mode="r", *args, **kwargs):
            if path.suffix == ".part" and "b" in mode and ("a" in mode or "w" in mode):
                return FullDisk(io.FileIO(path, mode.replace("b", "")))
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", open_part)

        result = _run(tmp_path, _wheel(server))

        assert result.code == prefetch.EXIT_DISK
        assert _files(tmp_path) == {f"{FILENAME}.part": PAYLOAD[:MB]}
        assert "No space left on device" in result.output


def test_needs_the_folder():
    out = io.StringIO()
    assert prefetch.main([], out=out) == 1
    assert "用法" in out.getvalue()


# ─── 釘住的 wheel ──────────────────────────────────────────────────────────

def _requirement(name: str) -> str:
    text = (ROOT / "backend" / "requirements-standalone.txt").read_text(encoding="utf-8")
    found = re.findall(rf"^{name}==(\S+)$", text, re.M)
    assert len(found) == 1, f"requirements-standalone.txt 的 {name}== 應該剛好一個：{found}"
    return found[0]


def _extra_index_url() -> str:
    text = (ROOT / "backend" / "requirements-standalone.txt").read_text(encoding="utf-8")
    found = re.findall(r"^--extra-index-url (\S+)$", text, re.M)
    assert len(found) == 1, found
    return found[0]


class TestPins:
    def test_only_torch_is_prefetched(self):
        assert [wheel.filename.split("-")[0] for wheel in prefetch.WHEELS] == ["torch"]

    def test_torch_is_the_version_the_requirements_pin(self):
        [wheel] = prefetch.WHEELS
        name, version, python, abi, platform = wheel.filename.removesuffix(".whl").split("-")
        assert (name, version) == ("torch", _requirement("torch"))
        # 隨包的 Python（build_release.ps1 的 $PythonEmbedVersion）與 64 位元的 Windows
        script = (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")
        [embed] = re.findall(r'^\$PythonEmbedVersion = "(\d+)\.(\d+)\.\d+"', script, re.M)
        assert python == abi == f"cp{embed[0]}{embed[1]}"
        assert platform == "win_amd64"

    def test_torch_comes_from_the_index_the_requirements_use(self):
        [wheel] = prefetch.WHEELS
        assert wheel.url == f"{_extra_index_url()}/{urllib.parse.quote(wheel.filename)}"

    def test_size_and_hash_are_pinned(self):
        [wheel] = prefetch.WHEELS
        assert re.fullmatch(r"[0-9a-f]{64}", wheel.sha256)
        assert wheel.size > 3 * 1000 ** 3  # torch 2.8.0+cu128 是 3.46 GB


class TestCertificates:
    # 兩張根憑證的 SHA-256 指紋：和 https://www.amazontrust.com/repository/ 列的、Mozilla 的根憑證
    # 清單裡的相同。download.pytorch.org 換了 CDN 時，這兩張也要跟著重查
    FINGERPRINTS = {
        "8ecde6884f3d87b1125ba31ac3fcb13d7016de7f57cc904fe1cb97c6ae98196e",  # Amazon Root CA 1
        "568d6905a2c88708a4b3025190edcfedb1974a606a13c6e5290fcb2ae63edab5",  # Starfield Services G2
    }

    def test_extra_roots_are_the_ones_download_pytorch_org_chains_to(self):
        pems = re.findall(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----",
                          prefetch.EXTRA_ROOT_CERTIFICATES, re.S)
        found = {hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() for pem in pems}
        assert found == self.FINGERPRINTS
        assert {urllib.parse.urlsplit(wheel.url).hostname for wheel in prefetch.WHEELS} == {
            "download.pytorch.org"}

    def test_context_trusts_them_and_still_verifies(self):
        context = prefetch.make_context()

        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        subjects = {dict(item[0] for item in cert["subject"]).get("commonName")
                    for cert in context.get_ca_certs()}
        assert {"Amazon Root CA 1", "Starfield Services Root Certificate Authority - G2"} <= subjects


class TestRelease:
    """發布包裡的位置與啟動器的呼叫方式。啟動器實際怎麼用它，tests/integration/test_launcher.py
    在 Windows 上用替身測。"""

    def test_release_puts_it_in_bin(self):
        script = (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")
        assert ('Copy-Item (Join-Path $Root "tools\\portable\\prefetch_wheels.py") '
                '(Join-Path $binDir "prefetch_wheels.py")') in script
        assert "bin/prefetch_wheels.py" in portable_zip.required_files(script)

    def test_launcher_handles_each_exit_code(self):
        launcher = (ROOT / "tools" / "launcher.cs").read_text(encoding="utf-8-sig")
        assert 'Path.Combine(root, "bin", "prefetch_wheels.py")' in launcher
        body = launcher.split("static void PrefetchWheels(", 1)[1].split("\n    }\n", 1)[0]
        handled = {int(code) for code in re.findall(r"^ +case (\d+):", body, re.M)}
        assert handled == {0, prefetch.EXIT_INTERRUPTED, prefetch.EXIT_MISMATCH, prefetch.EXIT_DISK,
                           prefetch.EXIT_FALLBACK}
        assert '"-I -X utf8 \\"{0}\\" \\"{1}\\""' in body
