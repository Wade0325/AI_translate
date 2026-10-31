"""發版附件：免安裝版隨包的 FFmpeg 的原始碼取得方式（#274）。

散布 bin\\ffmpeg.exe 與 bin\\ffprobe.exe 時，要在同一個地方提供和它們完全對應的原始碼（GPLv3 §6(d)，
LGPLv3 引用它；#80 的研究）。依 Wade 的決定（#274），發版時把下列檔案上傳成同一個 GitHub Release
的附件；這支腳本準備檔案並驗證，上傳由發版 workflow（#278）做：

- BtbN 的 build zip（兩個 exe 取自其中）：以 build_release.ps1 釘的 SHA-256 驗證。
- FFmpeg-<commit>.tar.gz：那個 build 的 FFmpeg commit 的完整原始碼。
- FFmpeg-Builds-<commit>.tar.gz：產生那個 build 的 BtbN 建置腳本（configure 參數、每個外部函式庫
  釘住的上游版本與修補）。
- SHA256SUMS：以上檔案的 SHA-256，給下載的人驗證（sha256sum -c 的格式）。

用法（在哪個目錄執行都可以，一律以 repo 根目錄為基準）：

    python tools/ffmpeg_sources.py fetch build/release-assets

原始碼用 git 依 commit 抓取，以 commit 雜湊驗證：git 收到的每個物件都以內容算出 ID，抓到的 commit
就是釘的那一個，內容也就是它的內容。不下載 GitHub 產生的 archive 再釘它的 SHA-256：GitHub 只保證
同一個 commit 的 archive 檔案內容不變，壓縮後的位元組可能不同
（https://docs.github.com/repositories/working-with-files/using-files/downloading-source-code-archives）。
tar.gz 由這裡用 git archive 產生，SHA-256 寫進 SHA256SUMS 一起上傳。

另外檢查發布包附的授權與聲明真的對得上這個 build（不符就失敗，不產生附件）：
- tools/portable/licenses/ffmpeg/ 的 LGPLv3 與 GPLv3 全文，和這個 commit 的 COPYING.LGPLv3、COPYING.GPLv3
  相同；BtbN 的 zip 附的 LICENSE.txt 也是同一份 LGPLv3。
- 兩個 exe 內嵌的授權是「LGPL version 3 or later」，configure 沒有 --enable-gpl 或 --enable-nonfree，
  而且 configure 參數和 tools/portable/THIRD_PARTY_NOTICES.txt 寫的相同。
- BtbN 的 release tag 還在時，指向釘的建置腳本 commit（BtbN 只保留月底版兩年，tag 不在了就略過）。

釘版（tag、檔名、SHA-256、兩個 commit）只寫在 build_release.ps1，這裡讀它；升版時一起換，
tests/unit/test_ffmpeg_pin.py 檢查它們彼此一致。CI 的 portable job 每個 PR 都在 Windows 上跑一次。
只用標準函式庫，另外需要 git。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "build_release.ps1"
CACHE_DIR = ROOT / "build" / "cache"  # build_release.ps1 的 Get-Verified 也下載到這裡
LICENSES = ROOT / "tools" / "portable" / "licenses" / "ffmpeg"
NOTICES = ROOT / "tools" / "portable" / "THIRD_PARTY_NOTICES.txt"

FFMPEG_REPO = "https://github.com/FFmpeg/FFmpeg.git"
BTBN_REPO = "https://github.com/BtbN/FFmpeg-Builds.git"

COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
# 兩個 exe 內嵌的 configure 參數（ffmpeg -buildconf 印的那一行）與各函式庫的授權字串
CONFIGURE = re.compile(rb"--prefix=[\x20-\x7e]+")
LIBRARY_LICENSE = re.compile(rb"(lib\w+) license: ([\x20-\x7e]+)")
EXPECTED_LICENSE = "LGPL version 3 or later"


@dataclass(frozen=True)
class Pins:
    """build_release.ps1 釘的 ffmpeg。"""

    tag: str
    build: str
    asset: str
    url: str
    sha256: str
    ffmpeg_commit: str
    btbn_commit: str

    @property
    def ffmpeg_archive(self) -> str:
        return f"FFmpeg-{self.ffmpeg_commit}.tar.gz"

    @property
    def btbn_archive(self) -> str:
        return f"FFmpeg-Builds-{self.btbn_commit}.tar.gz"

    @property
    def release_assets(self) -> tuple[str, ...]:
        """要上傳到 GitHub Release 的檔案（SHA256SUMS 放最後）。"""
        return (self.asset, self.ffmpeg_archive, self.btbn_archive, "SHA256SUMS")


def pins(script: str) -> Pins:
    """讀 build_release.ps1 的 ffmpeg 釘版；字串裡的 $變數 展開。彼此對不上時丟 ValueError。"""
    raw = dict(re.findall(r'^\$(\w+) = "([^"]*)"', script, re.M))

    def value(name: str) -> str:
        if name not in raw:
            raise ValueError(f"build_release.ps1 裡找不到 ${name}")
        return re.sub(r"\$(\w+)", lambda m: value(m.group(1)), raw[name])

    found = Pins(tag=value("FfmpegTag"), build=value("FfmpegBuild"), asset=value("FfmpegAsset"),
                 url=value("FfmpegUrl"), sha256=value("FfmpegSha256"),
                 ffmpeg_commit=value("FfmpegCommit"), btbn_commit=value("BtbnCommit"))
    for name, commit in (("FfmpegCommit", found.ffmpeg_commit), ("BtbnCommit", found.btbn_commit)):
        if not COMMIT.fullmatch(commit):
            raise ValueError(f"${name} 要寫完整的 40 碼 commit：{commit}")
    if not SHA256.fullmatch(found.sha256):
        raise ValueError(f"$FfmpegSha256 不是 SHA-256：{found.sha256}")
    # BtbN 的檔名是 git describe 的結果：n9.0.2-17-g2a571b6068 的 g 後面是 commit 的開頭
    described = re.search(r"-g([0-9a-f]{7,40})$", found.build)
    if not described or not found.ffmpeg_commit.startswith(described.group(1)):
        raise ValueError(f"$FfmpegCommit（{found.ffmpeg_commit}）和 $FfmpegBuild（{found.build}）"
                         "的 commit 對不上")
    return found


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(url: str, dest: Path, sha256: str, cache_dir: Path | None = CACHE_DIR) -> Path:
    """把 url 下載到 dest 並驗 SHA-256；快取裡已經有、雜湊也對時直接複製。不符時刪掉並丟 ValueError。"""
    cached = cache_dir / dest.name if cache_dir else None
    if cached and cached.is_file() and sha256_of(cached) == sha256:
        shutil.copyfile(cached, dest)
        return dest
    part = dest.with_name(dest.name + ".part")
    print(f"下載 {url}", flush=True)
    with urllib.request.urlopen(url, timeout=60) as response, part.open("wb") as f:
        shutil.copyfileobj(response, f, 1 << 20)
    actual = sha256_of(part)
    if actual != sha256:
        part.unlink()
        raise ValueError(f"{dest.name} 的 SHA-256 不符：預期 {sha256}，實際 {actual}（{url}）")
    part.replace(dest)
    return dest


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(args)} 失敗：{result.stderr.strip()}")
    return result.stdout


class SourceCheckout:
    """只抓一個 commit 的 git repo（--depth 1），驗證抓到的就是那個 commit。"""

    def __init__(self, repo_url: str, commit: str, workdir: Path):
        self.commit = commit
        self.dir = workdir
        _git("init", "-q", str(workdir))
        _git("fetch", "-q", "--depth", "1", repo_url, commit, cwd=workdir)
        fetched = _git("rev-parse", "FETCH_HEAD^{commit}", cwd=workdir).strip()
        if fetched != commit:
            raise ValueError(f"從 {repo_url} 抓到的是 {fetched}，不是釘的 {commit}")

    def read(self, path: str) -> bytes:
        result = subprocess.run(["git", "show", f"{self.commit}:{path}"], cwd=self.dir,
                                capture_output=True)
        if result.returncode != 0:
            raise ValueError(f"{self.commit} 裡沒有 {path}")
        return result.stdout

    def archive(self, dest: Path) -> Path:
        """把這個 commit 打包成 dest（.tar.gz），最上層資料夾是檔名去掉 .tar.gz。"""
        prefix = dest.name.removesuffix(".tar.gz")
        _git("archive", "--format=tar.gz", f"--prefix={prefix}/", "-o", str(dest), self.commit,
             cwd=self.dir)
        return dest


def _same_text(a: bytes, b: bytes) -> bool:
    """內容相同，不計換行是 CRLF 還是 LF（Windows 的 checkout 會換成 CRLF）。"""
    return a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")


def license_problems(build_zip: Path, source: SourceCheckout, licenses: Path = LICENSES) -> list[str]:
    """發布包附的 LGPLv3、GPLv3 全文和這個 FFmpeg commit、BtbN 的 zip 對得上嗎；問題的說明，沒有時是空的。"""
    problems = []
    lgpl = source.read("COPYING.LGPLv3")
    gpl = source.read("COPYING.GPLv3")
    for committed, upstream, name in ((licenses / "COPYING.LGPLv3.txt", lgpl, "COPYING.LGPLv3"),
                                      (licenses / "COPYING.GPLv3.txt", gpl, "COPYING.GPLv3")):
        if not committed.is_file():
            problems.append(f"缺少 {committed}")
        elif not _same_text(committed.read_bytes(), upstream):
            problems.append(f"{committed} 和 FFmpeg {source.commit} 的 {name} 不同")
    with zipfile.ZipFile(build_zip) as archive:
        names = [n for n in archive.namelist() if n.count("/") == 1 and n.endswith("/LICENSE.txt")]
        if len(names) != 1:
            problems.append(f"{build_zip.name} 裡找不到最上層資料夾的 LICENSE.txt")
        elif not _same_text(archive.read(names[0]), lgpl):
            problems.append(f"{build_zip.name} 的 LICENSE.txt 不是 FFmpeg 的 COPYING.LGPLv3："
                            "這不是 LGPL build？")
    return problems


def build_info(exe: bytes) -> tuple[str | None, dict[str, str]]:
    """exe 內嵌的 configure 參數，以及各函式庫的授權字串（例如 libavcodec → LGPL version 3 or later）。"""
    configure = CONFIGURE.search(exe)
    libraries = {m.group(1).decode(): m.group(2).decode() for m in LIBRARY_LICENSE.finditer(exe)}
    return (configure.group(0).decode() if configure else None), libraries


def notices_configure(notices: str) -> str | None:
    """THIRD_PARTY_NOTICES.txt 寫的 configure 參數（從 --prefix= 那一行到下一個空行），空白合成一個。"""
    match = re.search(r"^\s*(--prefix=.*?)(?:\n\s*\n)", notices, re.M | re.S)
    return " ".join(match.group(1).split()) if match else None


def binary_problems(build_zip: Path, notices: str) -> list[str]:
    """兩個 exe 是 LGPLv3 build，configure 參數和 THIRD_PARTY_NOTICES.txt 寫的相同；問題的說明。"""
    problems = []
    written = notices_configure(notices)
    if written is None:
        problems.append("THIRD_PARTY_NOTICES.txt 裡找不到 configure 參數（--prefix= 開頭的那幾行）")
    with zipfile.ZipFile(build_zip) as archive:
        for exe in ("ffmpeg.exe", "ffprobe.exe"):
            names = [n for n in archive.namelist() if n.endswith(f"/bin/{exe}")]
            if len(names) != 1:
                problems.append(f"{build_zip.name} 裡找不到 bin/{exe}")
                continue
            configure, libraries = build_info(archive.read(names[0]))
            if configure is None:
                problems.append(f"{exe} 裡找不到 configure 參數")
                continue
            flags = configure.split()
            if "--enable-version3" not in flags or {"--enable-gpl", "--enable-nonfree"} & set(flags):
                problems.append(f"{exe} 的 configure 不是 LGPLv3 build：要有 --enable-version3，"
                                "不能有 --enable-gpl 或 --enable-nonfree")
            wrong = {lib: text for lib, text in libraries.items() if text != EXPECTED_LICENSE}
            if not libraries or wrong:
                problems.append(f"{exe} 內嵌的授權不是「{EXPECTED_LICENSE}」：{wrong or '找不到'}")
            if written is not None and " ".join(flags) != written:
                problems.append(f"{exe} 的 configure 參數和 THIRD_PARTY_NOTICES.txt 寫的不同")
    return problems


def tag_problems(repo_url: str, tag: str, commit: str) -> list[str]:
    """BtbN 的 release tag 還在時要指向釘的 commit；tag 已經被刪掉（保留期過了）不算問題。"""
    lines = _git("ls-remote", repo_url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}").splitlines()
    refs = dict(reversed(line.split("\t", 1)) for line in lines if "\t" in line)
    target = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if target is None:
        print(f"{repo_url} 已經沒有 tag {tag}（BtbN 只保留月底版兩年），略過 tag 的檢查")
        return []
    return [] if target == commit else [f"BtbN 的 tag {tag} 指向 {target}，不是釘的 {commit}"]


def write_sums(outdir: Path, names: Sequence[str]) -> Path:
    """寫 SHA256SUMS（sha256sum -c 的格式：雜湊、兩個空白、檔名），回傳路徑。"""
    sums = outdir / "SHA256SUMS"
    lines = [f"{sha256_of(outdir / name)}  {name}\n" for name in names]
    with sums.open("w", encoding="ascii", newline="\n") as f:
        f.writelines(lines)
    return sums


def fetch(outdir: Path, script: str, *, ffmpeg_repo: str = FFMPEG_REPO, btbn_repo: str = BTBN_REPO,
          cache_dir: Path | None = CACHE_DIR, notices: str | None = None,
          licenses: Path = LICENSES) -> list[Path]:
    """準備發版附件到 outdir 並驗證；回傳附件的路徑（順序同 Pins.release_assets）。"""
    found = pins(script)
    outdir = outdir.resolve()  # git archive 在暫存的 repo 裡執行，相對路徑會指錯地方
    outdir.mkdir(parents=True, exist_ok=True)
    build_zip = download_verified(found.url, outdir / found.asset, found.sha256, cache_dir)

    problems = tag_problems(btbn_repo, found.tag, found.btbn_commit)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        print(f"抓取 FFmpeg {found.ffmpeg_commit}", flush=True)
        ffmpeg = SourceCheckout(ffmpeg_repo, found.ffmpeg_commit, Path(tmp) / "ffmpeg")
        problems += license_problems(build_zip, ffmpeg, licenses)
        problems += binary_problems(build_zip, NOTICES.read_text(encoding="utf-8")
                                    if notices is None else notices)
        if problems:
            raise ValueError("\n".join(problems))
        ffmpeg.archive(outdir / found.ffmpeg_archive)
        print(f"抓取 BtbN/FFmpeg-Builds {found.btbn_commit}", flush=True)
        btbn = SourceCheckout(btbn_repo, found.btbn_commit, Path(tmp) / "btbn")
        btbn.archive(outdir / found.btbn_archive)

    files = list(found.release_assets[:-1])
    write_sums(outdir, files)
    return [outdir / name for name in found.release_assets]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/ffmpeg_sources.py",
        description="準備隨包 FFmpeg 的原始碼與 build 原檔（GitHub Release 的附件），並驗證。")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch", help="下載、驗證並產生附件與 SHA256SUMS")
    fetch_parser.add_argument("outdir", type=Path, help="放附件的資料夾，例如 build/release-assets")
    args = parser.parse_args(argv)

    try:
        assets = fetch(args.outdir, BUILD_SCRIPT.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        print(f"失敗：{e}", file=sys.stderr)
        return 1
    print(f"附件（{args.outdir}）：")
    for path in assets:
        print(f"  {path.stat().st_size:>12}  {path.name}")
    print((args.outdir / "SHA256SUMS").read_text(encoding="ascii"), end="")
    return 0


if __name__ == "__main__":
    # 輸出到管線時用的是系統碼頁；印不出的字元改用跳脫，不讓腳本自己因為編碼而失敗
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    sys.exit(main())
