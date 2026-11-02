"""首次佈建前先把大的 wheel 下載到本機，斷線之後可以從中斷的地方接著下載（#303）。

build_release.ps1 把它放在發布包的 bin\\prefetch_wheels.py；啟動器（tools/launcher.cs）在首次佈建時、
執行 uv 之前，用隨包的 runtime\\python.exe 執行它::

    runtime\\python.exe -I -X utf8 bin\\prefetch_wheels.py <資料夾>

下載完、驗過 SHA-256 的 wheel 放在 <資料夾> 裡，啟動器接著以 ``uv pip install --find-links <資料夾>``
安裝，uv 就用本機的檔案，不再下載一次：--find-links 與套件索引有同一個檔名的 wheel 時，uv 0.12.23 先放
--find-links 的，索引的要「更相容」才換掉，同一個檔名不會（uv 的 crates/uv-resolver/src/version_map.rs
的 get_simple 與 crates/uv-distribution-types/src/prioritized_distribution.rs 的 insert_built）。不用
``torch @ file:///...``：那樣 uv 會把檔案的路徑（常帶著帳號名稱）記進 torch 的 direct_url.json。
佈建成功之後，啟動器刪掉整個資料夾。

為什麼要這一步：uv 下載中斷時會重試幾次，每次都從頭下載，放棄之後下載到一半的部分也不留。torch 一個
檔就有 3.46 GB，佔首次佈建九成的下載量；#35 在 CI 量到下載到 1.69 GB 時斷網，恢復後 torch 又從頭
下載一次。這裡用 HTTP Range 續傳：下載中的檔案存成 .part，斷線時先自己重試；重試都失敗才結束，
下次執行時從 .part 的大小接著下載。

只用標準函式庫：這時候還沒佈建，runtime 裡只有 Python 本身。

結束代碼（啟動器照它決定下一步）：
  0  下載好了（或上次已經下載好），而且驗過 SHA-256
  2  網路中斷，重試都失敗；已下載的部分留著，下次接著下載。啟動器停下來
  3  下載完的檔案 SHA-256 不符，已經刪掉；下次從頭下載。啟動器停下來
  4  寫不進資料夾（磁碟空間不足、沒有權限）；已下載的部分留著。啟動器停下來
  5  這個來源下載不到（伺服器沒有這個檔案、憑證驗證不了、檔案大小和釘住的不同）。
     啟動器照樣執行 uv，由 uv 照原本的方式從套件索引下載 torch（中斷就要從頭再來）
其他的結束代碼（例如這支程式自己出錯）和 5 一樣：預先下載只是讓中斷之後可以接著下載，
做不到時不能讓首次佈建比沒有這一步時更容易失敗。
"""

from __future__ import annotations

import hashlib
import http.client
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, TextIO


@dataclass(frozen=True)
class Wheel:
    label: str
    """給使用者看的名稱。"""
    url: str
    size: int
    sha256: str

    @property
    def filename(self) -> str:
        return urllib.parse.unquote(self.url.rsplit("/", 1)[1])


WHEELS = (
    # requirements-standalone.txt 的 torch==2.8.0+cu128；Python 3.11（build_release.ps1 的
    # $PythonEmbedVersion）、Windows x64 的 wheel。SHA-256 抄自套件索引
    # （https://download.pytorch.org/whl/cu128/torch/ 的連結後面的 #sha256=），大小是伺服器回的
    # Content-Length；整個檔案下載後自己算的也相同。換 torch 的版本時一起換，
    # tests/unit/test_prefetch_wheels.py 檢查兩邊一致
    Wheel(
        label="PyTorch",
        url="https://download.pytorch.org/whl/cu128/torch-2.8.0%2Bcu128-cp311-cp311-win_amd64.whl",
        size=3_461_420_395,
        sha256="34c55443aafd31046a7963b63d30bc3b628ee4a704f826796c865fdfd05bb596",
    ),
)

EXIT_INTERRUPTED = 2
EXIT_MISMATCH = 3
EXIT_DISK = 4
EXIT_FALLBACK = 5

TIMEOUT_SECONDS = 30
"""連線與每次讀取的逾時：網路斷了但連線沒有關掉時，最多等這麼久就重試。"""
RETRY_DELAYS = (2, 5, 10, 20, 30)
"""連續失敗（中間沒有多下載到任何東西）時，每次重試前等的秒數；用完就結束。"""
CHUNK = 1024 * 1024
FREE_SPACE_MARGIN = 100 * 1000 ** 2
"""開始下載前，磁碟除了還要下載的量，至少再留這麼多。"""

# download.pytorch.org（CloudFront）的憑證鏈：pytorch.org → Amazon RSA 2048 M01 → Amazon Root CA 1
# （伺服器送的這張由 Starfield Services Root Certificate Authority - G2 交叉簽署）。這兩張根憑證抄自
# https://www.amazontrust.com/repository/ 的 AmazonRootCA1.pem 與 SFSRootCAG2.pem，和 Mozilla 的根憑證
# 清單裡的相同（SHA-256 指紋見 tests/unit/test_prefetch_wheels.py），分別到 2038-01-17 與 2037-12-31。
#
# 為什麼除了 Windows 的憑證存放區還要這兩張：Python 只讀存放區裡已經有的根憑證（ssl 的
# load_default_certs 列舉 CA 與 ROOT 兩個存放區），不會像 Windows 自己的 HTTPS 那樣，在遇到不認得的
# 根憑證時才去 Windows Update 下載（自動更新根憑證）。新電腦的存放區可能還沒有這兩張，只靠存放區
# 會在第一步就驗證失敗、整個佈建都做不了。uv 用自己內建的根憑證，不受這個影響。
# 存放區照樣載入：公司網路以自己的憑證檢查 HTTPS 時，它的根憑證只在存放區裡
EXTRA_ROOT_CERTIFICATES = """\
-----BEGIN CERTIFICATE-----
MIIDQTCCAimgAwIBAgITBmyfz5m/jAo54vB4ikPmljZbyjANBgkqhkiG9w0BAQsF
ADA5MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6
b24gUm9vdCBDQSAxMB4XDTE1MDUyNjAwMDAwMFoXDTM4MDExNzAwMDAwMFowOTEL
MAkGA1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJv
b3QgQ0EgMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALJ4gHHKeNXj
ca9HgFB0fW7Y14h29Jlo91ghYPl0hAEvrAIthtOgQ3pOsqTQNroBvo3bSMgHFzZM
9O6II8c+6zf1tRn4SWiw3te5djgdYZ6k/oI2peVKVuRF4fn9tBb6dNqcmzU5L/qw
IFAGbHrQgLKm+a/sRxmPUDgH3KKHOVj4utWp+UhnMJbulHheb4mjUcAwhmahRWa6
VOujw5H5SNz/0egwLX0tdHA114gk957EWW67c4cX8jJGKLhD+rcdqsq08p8kDi1L
93FcXmn/6pUCyziKrlA4b9v7LWIbxcceVOF34GfID5yHI9Y/QCB/IIDEgEw+OyQm
jgSubJrIqg0CAwEAAaNCMEAwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMC
AYYwHQYDVR0OBBYEFIQYzIU07LwMlJQuCFmcx7IQTgoIMA0GCSqGSIb3DQEBCwUA
A4IBAQCY8jdaQZChGsV2USggNiMOruYou6r4lK5IpDB/G/wkjUu0yKGX9rbxenDI
U5PMCCjjmCXPI6T53iHTfIUJrU6adTrCC2qJeHZERxhlbI1Bjjt/msv0tadQ1wUs
N+gDS63pYaACbvXy8MWy7Vu33PqUXHeeE6V/Uq2V8viTO96LXFvKWlJbYK8U90vv
o/ufQJVtMVT8QtPHRh8jrdkPSHCa2XV4cdFyQzR1bldZwgJcJmApzyMZFo6IQ6XU
5MsI+yMRQ+hDKXJioaldXgjUkK642M4UwtBV8ob2xJNDd2ZhwLnoQdeXeGADbkpy
rqXRfboQnoZsG4q5WTP468SQvvG5
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIID7zCCAtegAwIBAgIBADANBgkqhkiG9w0BAQsFADCBmDELMAkGA1UEBhMCVVMx
EDAOBgNVBAgTB0FyaXpvbmExEzARBgNVBAcTClNjb3R0c2RhbGUxJTAjBgNVBAoT
HFN0YXJmaWVsZCBUZWNobm9sb2dpZXMsIEluYy4xOzA5BgNVBAMTMlN0YXJmaWVs
ZCBTZXJ2aWNlcyBSb290IENlcnRpZmljYXRlIEF1dGhvcml0eSAtIEcyMB4XDTA5
MDkwMTAwMDAwMFoXDTM3MTIzMTIzNTk1OVowgZgxCzAJBgNVBAYTAlVTMRAwDgYD
VQQIEwdBcml6b25hMRMwEQYDVQQHEwpTY290dHNkYWxlMSUwIwYDVQQKExxTdGFy
ZmllbGQgVGVjaG5vbG9naWVzLCBJbmMuMTswOQYDVQQDEzJTdGFyZmllbGQgU2Vy
dmljZXMgUm9vdCBDZXJ0aWZpY2F0ZSBBdXRob3JpdHkgLSBHMjCCASIwDQYJKoZI
hvcNAQEBBQADggEPADCCAQoCggEBANUMOsQq+U7i9b4Zl1+OiFOxHz/Lz58gE20p
OsgPfTz3a3Y4Y9k2YKibXlwAgLIvWX/2h/klQ4bnaRtSmpDhcePYLQ1Ob/bISdm2
8xpWriu2dBTrz/sm4xq6HZYuajtYlIlHVv8loJNwU4PahHQUw2eeBGg6345AWh1K
Ts9DkTvnVtYAcMtS7nt9rjrnvDH5RfbCYM8TWQIrgMw0R9+53pBlbQLPLJGmpufe
hRhJfGZOozptqbXuNC66DQO4M99H67FrjSXZm86B0UVGMpZwh94CDklDhbZsc7tk
6mFBrMnUVN+HL8cisibMn1lUaJ/8viovxFUcdUBgF4UCVTmLfwUCAwEAAaNCMEAw
DwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMCAQYwHQYDVR0OBBYEFJxfAN+q
AdcwKziIorhtSpzyEZGDMA0GCSqGSIb3DQEBCwUAA4IBAQBLNqaEd2ndOxmfZyMI
bw5hyf2E3F/YNoHN2BtBLZ9g3ccaaNnRbobhiCPPE95Dz+I0swSdHynVv/heyNXB
ve6SbzJ08pGCL72CQnqtKrcgfU28elUSwhXqvfdqlS5sdJ/PHLTyxQGjhdByPq1z
qwubdQxtRbeOlKyWN7Wg0I8VRw7j6IPdj/3vQQF3zCepYoUz8jcI73HPdwbeyBkd
iEDPfUYd/x7H4c7/I9vG+o1VTqkC50cRRj70/b17KSa7qWFiNyi2LSr2EIZkyXCn
0q23KXB56jzaYyWf/Wi3MOxw+3WKt21gZ7IeyLnp2KhvAotnDU0mV3HaIPzBSlCN
sSi6
-----END CERTIFICATE-----
"""

Opener = Callable[..., http.client.HTTPResponse]
"""開啟 urllib 的 Request，回傳回應（測試時換成接本機伺服器、不經過代理的）。"""


class DownloadInterrupted(Exception):
    """下載沒有完成，已下載的部分留著。"""


class VerificationFailed(Exception):
    """下載的檔案和預期的不同，已經刪掉。"""


class DiskProblem(Exception):
    """寫不進下載的資料夾，已下載的部分留著。"""


class CannotPrefetch(Exception):
    """這個來源下載不到，重試也沒有用；改由 uv 下載。discard 是 .part 要不要刪掉。"""

    def __init__(self, message: str, *, discard: bool = False):
        super().__init__(message)
        self.discard = discard


class _Retry(Exception):
    """這一次連線失敗，可以重試：網路斷線、逾時、伺服器暫時出錯。"""


class _RangeNotSatisfiable(Exception):
    """伺服器回 416：要求的起點不在檔案裡，.part 已經是完整的大小，或比檔案還大。"""


def make_context() -> ssl.SSLContext:
    """Windows 憑證存放區（Python 預設的）加上 EXTRA_ROOT_CERTIFICATES；照樣驗主機名稱與憑證鏈。"""
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=EXTRA_ROOT_CERTIFICATES)
    return context


def make_opener() -> Opener:
    """下載用的 HTTPS。代理伺服器照 urllib 的預設：環境變數（HTTPS_PROXY 等），沒有設時讀 Windows
    的網際網路設定。"""
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=make_context())).open


def amount(size: int) -> str:
    """給人看的大小：1 GB 以上寫成 GB（小數兩位），以下寫成 MB。"""
    if size >= 1000 ** 3:
        return f"{size / 1000 ** 3:.2f} GB"
    return f"{size / 1000 ** 2:.0f} MB"


class Progress:
    """下載進度：輸出是 console 時同一行一直更新，導向檔案時每 10% 印一行。"""

    def __init__(self, label: str, total: int, out: TextIO, clock: Callable[[], float]):
        self.label, self.total, self.out, self.clock = label, total, out, clock
        self.live = out.isatty()
        self.shown_at = 0.0
        self.shown_step = -1
        self.open_line = False

    def update(self, done: int) -> None:
        percent = done * 100 // self.total
        if self.live:
            now = self.clock()
            if now - self.shown_at < 0.5 and done < self.total:
                return
            self.shown_at = now
            self.open_line = True
            end = ""
            prefix = "\r"
        else:
            step = percent // 10
            if step == self.shown_step:
                return
            self.shown_step = step
            end = "\n"
            prefix = ""
        print(f"{prefix}  {self.label}：{amount(done)} / {amount(self.total)}（{percent}%）",
              end=end, file=self.out, flush=True)

    def finish(self) -> None:
        """結束同一行的進度，之後的訊息從新的一行開始。"""
        if self.open_line:
            print(file=self.out, flush=True)
            self.open_line = False


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        raise DiskProblem(f"無法刪除 {path}：{e}") from e


def _move(part: Path, final: Path, sleep: Callable[[float], None]) -> None:
    """驗過才改成正式的檔名；防毒軟體剛好在掃描它時會暫時改不了名，等一下再試。"""
    for attempt in range(5):
        try:
            part.replace(final)
            return
        except PermissionError:
            if attempt == 4:
                raise
            sleep(1)


_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


def _transfer(wheel: Wheel, part: Path, offset: int, open_url: Opener,
              progress: Progress) -> None:
    """從 offset 接著下載到 part；連線中途斷掉時丟 _Retry，part 留著已經寫進去的部分。"""
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    request = urllib.request.Request(wheel.url, headers=headers)
    try:
        response = open_url(request, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError as e:
        if e.code == 416:
            e.close()
            raise _RangeNotSatisfiable() from e
        if e.code in (408, 429) or e.code >= 500:
            raise _Retry(f"伺服器暫時無法回應（HTTP {e.code}）") from e
        raise CannotPrefetch(f"伺服器回應 HTTP {e.code}（{wheel.url}）") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            raise CannotPrefetch(
                f"無法驗證 {urllib.parse.urlsplit(wheel.url).hostname} 的憑證"
                f"（{e.reason.verify_message}）") from e
        raise _Retry(_reason(e.reason)) from e
    except (OSError, http.client.HTTPException) as e:
        raise _Retry(_reason(e)) from e

    with response:
        sizes = []  # 回應說檔案有多大
        if response.status == 206 and offset:
            match = _CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", ""))
            if not match or int(match.group(1)) != offset:
                raise _Retry(f"伺服器回的範圍不對（{response.headers.get('Content-Range')}）")
            sizes.append(int(match.group(3)))
            mode = "ab"
        elif response.status == 200:
            # 沒有要求範圍，或伺服器不支援續傳：從頭寫
            offset = 0
            mode = "wb"
        else:
            raise CannotPrefetch(f"伺服器回應 HTTP {response.status}（{wheel.url}）")
        length = response.headers.get("Content-Length", "")
        if length.isdigit():
            sizes.append(offset + int(length))
        for size in sizes:
            if size != wheel.size:
                raise CannotPrefetch(
                    f"伺服器上的檔案是 {size:,} 位元組，預期是 {wheel.size:,} 位元組", discard=True)

        try:
            file: BinaryIO = part.open(mode)
        except OSError as e:
            raise DiskProblem(f"無法寫入 {part}：{e}") from e
        done = offset
        with file:
            while done < wheel.size:
                try:
                    block = response.read(min(CHUNK, wheel.size - done))
                except (OSError, http.client.HTTPException) as e:
                    raise _Retry(_reason(e)) from e
                if not block:
                    # http.client 在連線提早關掉時回傳空的，不丟例外
                    raise _Retry("連線在檔案傳完之前就關掉了")
                try:
                    file.write(block)
                except OSError as e:
                    raise DiskProblem(f"無法寫入 {part}：{e}") from e
                done += len(block)
                progress.update(done)


def _reason(error: object) -> str:
    if isinstance(error, TimeoutError):
        return f"{TIMEOUT_SECONDS} 秒沒有收到資料"
    if isinstance(error, BaseException):
        text = str(error)
        return f"{type(error).__name__}: {text}" if text else type(error).__name__
    return str(error)


def fetch(wheel: Wheel, folder: Path, *, open_url: Opener, out: TextIO,
          sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], float] = time.monotonic) -> Path:
    """下載 wheel 到 folder 並驗 SHA-256，回傳檔案的路徑。上次已經下載好、驗得過時直接用。

    Raises:
        DownloadInterrupted: 重試都失敗；已下載的部分留在 .part，下次接著下載。
        VerificationFailed: 下載完的檔案 SHA-256 不符；已經刪掉。
        DiskProblem: 寫不進 folder。
        CannotPrefetch: 這個來源下載不到，重試也沒有用。
    """
    final = folder / wheel.filename
    part = folder / (wheel.filename + ".part")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise DiskProblem(f"無法建立資料夾 {folder}：{e}") from e

    if final.exists():
        print(f"{wheel.label} 上次已經下載好了，正在檢查檔案...", file=out, flush=True)
        if _size(final) == wheel.size and sha256_of(final) == wheel.sha256:
            return final
        print(f"上次下載的 {wheel.label} 和預期的不同，刪掉重新下載。", file=out, flush=True)
        _remove(final)

    offset = _size(part)
    if offset > wheel.size:
        _remove(part)
        offset = 0
    remaining = wheel.size - offset
    free = shutil.disk_usage(folder).free
    if free < remaining + FREE_SPACE_MARGIN:
        raise DiskProblem(
            f"磁碟空間不足：下載 {wheel.label} 還要 {amount(remaining)}，"
            f"{folder.anchor or folder} 只剩 {amount(free)}")

    if offset:
        print(f"從上次中斷的地方接著下載 {wheel.label}（已有 {amount(offset)}，"
              f"還要 {amount(remaining)}）...", file=out, flush=True)
    else:
        print(f"正在下載 {wheel.label}（{amount(wheel.size)}）。中斷時已下載的部分會保留，"
              "下次從中斷的地方接著下載。", file=out, flush=True)

    progress = Progress(wheel.label, wheel.size, out, clock)
    failures = 0
    while _size(part) < wheel.size:
        before = _size(part)
        try:
            _transfer(wheel, part, before, open_url, progress)
        except _RangeNotSatisfiable:
            if _size(part) != wheel.size:
                _remove(part)  # 伺服器說起點不在檔案裡，.part 卻沒有檔案那麼大：從頭下載
        except _Retry as e:
            if _size(part) > before:
                failures = 0  # 有下載到東西：重新計算連續失敗的次數
            if failures == len(RETRY_DELAYS):
                progress.finish()
                raise DownloadInterrupted(str(e)) from e
            delay = RETRY_DELAYS[failures]
            failures += 1
            progress.finish()
            print(f"連線中斷（{e}），{delay} 秒後重試（第 {failures}/{len(RETRY_DELAYS)} 次）...",
                  file=out, flush=True)
            sleep(delay)
        except CannotPrefetch as e:
            progress.finish()
            if e.discard:
                _remove(part)
            raise
    progress.finish()

    print(f"正在檢查下載的 {wheel.label}（SHA-256）...", file=out, flush=True)
    actual = sha256_of(part)
    if actual != wheel.sha256:
        _remove(part)
        raise VerificationFailed(f"SHA-256 是 {actual}，預期是 {wheel.sha256}")
    try:
        _move(part, final, sleep)
    except OSError as e:
        raise DiskProblem(f"無法把 {part.name} 改名成 {final.name}：{e}") from e
    return final


def main(argv: Sequence[str], *, wheels: Sequence[Wheel] = WHEELS,
         open_url: Opener | None = None, out: TextIO = sys.stdout,
         sleep: Callable[[float], None] = time.sleep) -> int:
    if len(argv) != 1:
        print("用法：prefetch_wheels.py <資料夾>", file=out)
        return 1
    folder = Path(argv[0])
    opener = open_url if open_url is not None else make_opener()
    for wheel in wheels:
        try:
            fetch(wheel, folder, open_url=opener, out=out, sleep=sleep)
        except DownloadInterrupted as e:
            kept = _size(folder / (wheel.filename + ".part"))
            print(f"{wheel.label} 下載中斷：{e}。", file=out)
            if kept:
                print(f"已下載的 {amount(kept)} 會保留，下次從這裡接著下載。", file=out)
            return EXIT_INTERRUPTED
        except VerificationFailed as e:
            print(f"下載的 {wheel.label} 和預期的不同（{e}），已經刪掉；下次會重新下載。", file=out)
            return EXIT_MISMATCH
        except DiskProblem as e:
            print(f"{wheel.label} 下載失敗：{e}。", file=out)
            return EXIT_DISK
        except CannotPrefetch as e:
            print(f"無法預先下載 {wheel.label}：{e}。改由 uv 照原本的方式下載；"
                  f"這次中斷的話，{wheel.label} 要從頭下載。", file=out)
            return EXIT_FALLBACK
        except KeyboardInterrupt:
            print(f"\n已停止下載 {wheel.label}；已下載的部分會保留，下次從這裡接著下載。", file=out)
            return EXIT_INTERRUPTED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
