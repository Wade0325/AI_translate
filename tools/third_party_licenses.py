"""產生 ffmpeg.exe 靜態連入的函式庫、以及 Rust 套件的授權清單（#274）。

用法（在 repo 根目錄，要連網；第一次約要半小時，之後用 build/cache/third-party 的快取）：

    python -m tools.third_party_licenses

產生三個檔案（發布包的 licenses\\ 資料夾）：

    tools/portable/licenses/ffmpeg/libraries.txt    BtbN 建進 ffmpeg.exe 的 C／C++ 函式庫，加上 mingw-w64
                                                    與 GCC 的執行期函式庫
    tools/portable/licenses/ffmpeg/rust-crates.txt  其中 rav1e、librsvg 是 Rust 寫的：它們 Cargo.lock 的套件
    tools/portable/licenses/uv/crates.txt           uv.exe：uv 的 Cargo.lock 的套件

版本都從 build_release.ps1 的釘版來（$BtbnCommit、$UvVersion 等）。改了釘版就要重新產生；
tests/unit/test_third_party_licenses.py 比對檔案開頭記的釘版，沒有重新產生時紅燈。

每個函式庫的原始碼以 git 依 commit 抓取（只抓檔案樹，要讀的授權檔才下載）；svn 依 revision；
Rust 套件從 crates.io 下載後驗 Cargo.lock 的 checksum。授權檔收原始碼樹裡所有像授權檔的檔案（認法見
tools/license_texts.py），但略過測試、範例、效能測試等不會編進函式庫的資料夾。

只讀、不執行上游的任何程式碼（BtbN 的腳本也是解析而已，見 tools/btbn_stages.py）。
"""

from __future__ import annotations

import ast
import configparser
import hashlib
import html.parser
import re
import subprocess
import sys
import tarfile
import io
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from tools import btbn_stages, cargo_crates, ffmpeg_sources
from tools.license_texts import Component, LicenseFile, decode, is_license_file, render, skipped

ROOT = Path(__file__).resolve().parent.parent
LICENSES = ROOT / "tools" / "portable" / "licenses"
FFMPEG_LIBRARIES = LICENSES / "ffmpeg" / "libraries.txt"
FFMPEG_CRATES = LICENSES / "ffmpeg" / "rust-crates.txt"
UV_CRATES = LICENSES / "uv" / "crates.txt"
CACHE = ROOT / "build" / "cache" / "third-party"

UV_REPO = "https://github.com/astral-sh/uv.git"
RUST_REPO = "https://github.com/rust-lang/rust.git"
GCC_REPO = "https://github.com/gcc-mirror/gcc.git"
# 套件沒附授權檔時用的 SPDX 標準全文
SPDX_REPO = "https://github.com/spdx/license-list-data.git"
SPDX_REF = "v3.29.0"
SPDX_COMMIT = "31ba1a50e5397e00a304dbadc76531740e89ee48"

COMMIT = re.compile(r"[0-9a-f]{40}")

# repo 裡沒有授權檔、授權寫在原始碼開頭註解的：{repo 網址（去掉 .git、小寫）: 收哪些路徑開頭的檔案}
LICENSE_IN_HEADERS: dict[str, tuple[str, ...]] = {
    # 每個標頭檔開頭寫「This copyright notice applies to this header file only」，MIT
    "https://github.com/ffmpeg/nv-codec-headers": ("include/ffnvcodec/",),
}


def _git(*args: str, cwd: Path | None = None, timeout: int = 900) -> str:
    result = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(args)} 失敗：{result.stderr.strip()}")
    return result.stdout


class GitTree:
    """一個 commit 的檔案樹。只抓樹（--filter=blob:none），讀檔時才下載那個檔案。"""

    def __init__(self, url: str, ref: str, mirrors: Sequence[str] = ()):
        errors = []
        for candidate in (url, *mirrors):
            workdir = CACHE / "git" / re.sub(r"[^\w.-]+", "_", candidate.split("://", 1)[-1])
            try:
                self.commit = self._fetch(candidate, ref, workdir)
            except (ValueError, subprocess.TimeoutExpired) as e:
                errors.append(str(e))
                continue
            self.url, self.dir = url, workdir
            break
        else:
            raise ValueError(f"抓不到 {url} 的 {ref}：" + "；".join(errors))
        if COMMIT.fullmatch(ref) and self.commit != ref:
            raise ValueError(f"從 {url} 抓到的是 {self.commit}，不是釘的 {ref}")
        self.entries: dict[str, tuple[str, str]] = {}  # 路徑 → (mode, 物件 ID)
        for line in _git("ls-tree", "-r", "--full-tree", self.commit, cwd=self.dir).splitlines():
            meta, path = line.split("\t", 1)
            mode, _, sha = meta.split()
            self.entries[path] = (mode, sha)

    @staticmethod
    def _fetch(url: str, ref: str, workdir: Path) -> str:
        marker = workdir / ("ref-" + re.sub(r"[^\w.-]+", "_", ref))
        if marker.is_file():
            return marker.read_text(encoding="ascii").strip()
        if not (workdir / ".git").is_dir():
            workdir.mkdir(parents=True, exist_ok=True)
            _git("init", "-q", cwd=workdir)
            _git("remote", "add", "origin", url, cwd=workdir)
        target = ref if COMMIT.fullmatch(ref) else f"refs/tags/{ref}"
        print(f"抓取 {url} {ref}", flush=True)
        try:
            _git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", target, cwd=workdir)
        except ValueError:
            if target == ref:
                raise
            _git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", ref, cwd=workdir)
        commit = _git("rev-parse", "FETCH_HEAD^{commit}", cwd=workdir).strip()
        marker.write_text(commit, encoding="ascii")
        return commit

    def read(self, path: str) -> bytes:
        _, sha = self.entries[path]
        result = subprocess.run(["git", "cat-file", "blob", sha], cwd=self.dir, capture_output=True,
                                timeout=600)
        if result.returncode != 0:
            raise ValueError(f"讀不到 {self.url} 的 {path}：{result.stderr.decode(errors='replace')}")
        return result.stdout

    def license_files(self, removed: Iterable[str] = ()) -> list[LicenseFile]:
        found = []
        for path, (mode, _) in sorted(self.entries.items()):
            if mode == "160000" or not is_license_file(path) or skipped(path, removed):
                continue
            text = decode(self.read(path))
            if text:
                found.append(LicenseFile(path, text))
        return found

    def submodules(self, only: Sequence[str] = ()) -> list[tuple[str, str, str]]:
        """（路徑, 網址, commit）：.gitmodules 列的、這個 commit 釘住的子模組；only 有值時只取那些路徑。"""
        if ".gitmodules" not in self.entries:
            return []
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(self.read(".gitmodules").decode("utf-8"))
        found = []
        for section in config.sections():
            path, url = config[section]["path"], config[section]["url"]
            mode, sha = self.entries.get(path, ("", ""))
            if mode != "160000" or (only and path not in only) or skipped(f"{path}/x"):
                continue
            if url.startswith("../"):
                url = urllib.parse.urljoin(self.url.rstrip("/") + "/", url)
            found.append((path, url, sha))
        return found


class _Links(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if tag == "a" and href and not href.startswith(("../", "/", "http")):
            self.links.append(href)


def _http(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def svn_license_files(repo: str, rev: str) -> list[LicenseFile]:
    """svn 的某個 revision：以 mod_dav_svn 的 !svn/bc/<rev> 網址瀏覽目錄。"""
    parsed = urllib.parse.urlsplit(repo)
    root, _, sub = parsed.path.partition("/svn/")
    base = f"{parsed.scheme}://{parsed.netloc}{root}/svn/!svn/bc/{rev}/{sub}/"
    print(f"抓取 {repo} r{rev}", flush=True)
    found = []
    pending = [""]
    while pending:
        folder = pending.pop()
        parser = _Links()
        parser.feed(_http(base + folder).decode("utf-8", errors="replace"))
        for link in parser.links:
            path = folder + urllib.parse.unquote(link)
            if link.endswith("/"):
                if not skipped(path + "x"):
                    pending.append(path)
            elif is_license_file(path):
                text = decode(_http(base + urllib.parse.quote(path)))
                if text:
                    found.append(LicenseFile(path, text))
    return sorted(found, key=lambda f: f.path)


def download_verified(urls: Sequence[str], sha256: str, name: str) -> bytes:
    cached = CACHE / "downloads" / name
    if cached.is_file() and hashlib.sha256(cached.read_bytes()).hexdigest() == sha256:
        return cached.read_bytes()
    errors = []
    for url in urls:
        try:
            data = _http(url)
        except OSError as e:
            errors.append(f"{url}：{e}")
            continue
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise ValueError(f"{name} 的 SHA-256 不符：預期 {sha256}，實際 {actual}（{url}）")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
        return data
    raise ValueError(f"下載不到 {name}：" + "；".join(errors))


def tarball_license_files(data: bytes) -> list[LicenseFile]:
    """tar.gz 裡的授權檔；路徑去掉最上層的資料夾。"""
    found = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for member in tar.getmembers():
            path = PurePosixPath(*PurePosixPath(member.name).parts[1:]).as_posix()
            if member.isfile() and is_license_file(path) and not skipped(path):
                f = tar.extractfile(member)
                text = decode(f.read()) if f else None
                if text:
                    found.append(LicenseFile(path, text))
    return sorted(found, key=lambda f: f.path)


def meson_wrap(tree: GitTree, name: str) -> Component:
    """meson 的 [wrap-file]：下載 source_url（或 source_fallback_url）並驗 source_hash。"""
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(tree.read(f"subprojects/{name}.wrap").decode("utf-8"))
    if not config.has_section("wrap-file"):
        raise ValueError(f"subprojects/{name}.wrap 不是 [wrap-file]，還不支援")
    wrap = config["wrap-file"]
    urls = [wrap["source_url"], *([wrap["source_fallback_url"]] if "source_fallback_url" in wrap else [])]
    data = download_verified(urls, wrap["source_hash"], wrap["source_filename"])
    return Component(name, wrap["directory"], tarball_license_files(data), source=wrap["source_url"],
                     notes=[f"SHA-256：{wrap['source_hash']}（subprojects/{name}.wrap）"])


def gclient_deps(text: str) -> dict[str, tuple[str, str]]:
    """shaderc 的 DEPS（gclient 格式）：{路徑: (網址, commit)}。只解析，不執行。"""
    tree = ast.parse(text)
    variables: dict[str, str] = {}
    deps: dict[str, tuple[str, str]] = {}

    def value(node: ast.expr) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return value(node.left) + value(node.right)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Var"
                and len(node.args) == 1):
            return variables[value(node.args[0])]
        raise ValueError(f"DEPS 有看不懂的寫法：{ast.dump(node)}")

    for stmt in tree.body:
        if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Dict)):
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        pairs = [(value(k), v) for k, v in zip(stmt.value.keys, stmt.value.values, strict=True) if k]
        if target.id == "vars":
            variables.update((k, value(v)) for k, v in pairs)
        elif target.id == "deps":
            for path, node in pairs:
                url, _, commit = value(node).rpartition("@")
                deps[path] = (url, commit)
    return deps


def _version(tree: GitTree, ref: str) -> str:
    return tree.commit if ref == tree.commit else f"{ref}（{tree.commit}）"


def leading_comment(source: str) -> str | None:
    """C 原始碼開頭的 /* … */ 註解（去掉每行開頭的 *）；開頭不是註解時回傳 None。"""
    match = re.match(r"\s*/\*(.*?)\*/", source, re.S)
    if match is None:
        return None
    lines = [re.sub(r"^\s*\*? ?", "", line) for line in match.group(1).split("\n")]
    return "\n".join(line.rstrip() for line in lines).strip("\n") or None


def _git_component(name: str, tree: GitTree, ref: str, removed: Iterable[str] = (),
                   notes: Sequence[str] = ()) -> Component:
    files = tree.license_files(removed)
    notes = list(notes)
    prefixes = LICENSE_IN_HEADERS.get(tree.url.removesuffix(".git").lower(), ())
    if not files and prefixes:
        for path in sorted(p for p in tree.entries if p.startswith(prefixes)):
            comment = leading_comment(decode(tree.read(path)) or "")
            if comment:
                files.append(LicenseFile(f"{path} 開頭的註解", comment))
        notes.append("repo 沒有授權檔：授權寫在每個原始碼檔的開頭，收它們開頭的註解")
    if not files:
        raise ValueError(f"{name}（{tree.url} {ref}）找不到授權檔")
    return Component(name, _version(tree, ref), files, source=tree.url, notes=notes)


def stage_components(stage: btbn_stages.Stage, seen: set[tuple[str, str]]) -> list[Component]:
    """一個 BtbN stage 的元件：它的 repo、子模組、meson subproject、DEPS 列的 repo。"""
    out: list[Component] = []

    def add_git(name: str, url: str, ref: str, mirrors: Sequence[str] = (), removed: Iterable[str] = (),
                notes: Sequence[str] = ()) -> GitTree | None:
        tree = GitTree(url, ref, mirrors)
        key = (url.removesuffix(".git").lower(), tree.commit)
        if key in seen:
            return tree
        seen.add(key)
        out.append(_git_component(name, tree, ref, removed, notes))
        return tree

    script = stage.script.path
    for i, source in enumerate(stage.sources):
        name = stage.name if i == 0 else f"{stage.name}：{PurePosixPath(source.repo).name.removesuffix('.git')}"
        if isinstance(source, btbn_stages.SvnSource):
            files = svn_license_files(source.repo, source.rev)
            if not files:
                raise ValueError(f"{name}（{source.repo} r{source.rev}）找不到授權檔")
            out.append(Component(name, f"r{source.rev}", files, source=source.repo,
                                 notes=[f"BtbN：{script}"]))
            continue
        tree = add_git(name, source.repo, source.ref, source.mirrors, stage.removed if i == 0 else (),
                       [f"BtbN：{script}"])
        if i != 0 or tree is None:
            continue
        pending = [(stage.name, tree)] if stage.submodules is not None else []
        while pending:
            parent, parent_tree = pending.pop(0)
            only = stage.submodules if parent_tree is tree else ()
            for path, url, sha in parent_tree.submodules(only or ()):
                child = add_git(f"{parent} 的子模組 {path}", url, sha)
                if child is not None:
                    pending.append((f"{parent}/{path}", child))
        for wrap in stage.meson_wraps:
            out.append(meson_wrap(tree, wrap))
        if stage.git_sync_deps:
            for path, (url, commit) in gclient_deps(tree.read("DEPS").decode("utf-8")).items():
                if not skipped(f"{path}/x"):
                    add_git(f"{stage.name} 的 {path}（utils/git-sync-deps）", url, commit)
    return out


def ffmpeg_components(pins: ffmpeg_sources.Pins, notices: str) -> tuple[list[Component], list[GitTree]]:
    """BtbN 建進 ffmpeg.exe 的函式庫，以及用 cargo 建置的 stage 的 repo（給 Rust 套件用）。"""
    btbn = GitTree(ffmpeg_sources.BTBN_REPO, pins.btbn_commit)
    files = {p: btbn.read(p).decode("utf-8") for p in btbn.entries if p.startswith("scripts.d/")}
    scripts = btbn_stages.Scripts(files)
    _check_configure(scripts, notices)
    stages = scripts.stages()
    seen: set[tuple[str, str]] = set()
    components: list[Component] = []
    for stage in stages:
        components += stage_components(stage, seen)
    components.append(gcc_runtime(btbn))
    cargo = [GitTree(s.sources[0].repo, s.sources[0].ref) for s in stages
             if s.cargo and isinstance(s.sources[0], btbn_stages.GitSource)]
    return components, cargo


def _check_configure(scripts: btbn_stages.Scripts, notices: str) -> None:
    """THIRD_PARTY_NOTICES.txt 記的 configure 參數裡，每個 --enable-xxx 都要有建了的 stage 負責。"""
    configure = ffmpeg_sources.notices_configure(notices)
    if configure is None:
        raise ValueError("THIRD_PARTY_NOTICES.txt 裡找不到 configure 參數")
    produced = {"--enable-version3"}  # variants/defaults-lgpl.sh
    for name in scripts.closure():
        if scripts.stage_enabled(name):
            for script in scripts.resolve(name):
                if scripts.enabled(script):
                    produced |= scripts.configure_flags(script)
    missing = sorted(f for f in configure.split() if f.startswith("--enable-") and f not in produced)
    if missing:
        raise ValueError("這些 configure 參數找不到對應的 BtbN stage，解析的結果不可信：" + " ".join(missing))


def gcc_runtime(btbn: GitTree) -> Component:
    """GCC 的執行期函式庫（libgcc、libstdc++、libgomp）：BtbN 的工具鏈以 -static-libgcc -static-libstdc++ 連入。"""
    config = btbn.read("images/base-win64/ct-ng-config").decode("utf-8")
    match = re.search(r'^CT_GCC_VERSION="([\d.]+)"$', config, re.M)
    if match is None:
        raise ValueError("images/base-win64/ct-ng-config 裡找不到 CT_GCC_VERSION")
    tag = f"releases/gcc-{match.group(1)}"
    tree = GitTree(GCC_REPO, tag)
    files = [LicenseFile(p, decode(tree.read(p)) or "") for p in ("COPYING.RUNTIME", "COPYING3")]
    return Component("GCC 執行期函式庫（libgcc、libstdc++、libgomp）", _version(tree, tag), files,
                     source=GCC_REPO, notes=["BtbN：images/base-win64/ct-ng-config 的 CT_GCC_VERSION"])


def rust_std(version: str, note: str) -> Component:
    tree = GitTree(RUST_REPO, version)
    files = [LicenseFile(p, decode(tree.read(p)) or "") for p in ("COPYRIGHT", "LICENSE-APACHE", "LICENSE-MIT")]
    return Component("Rust 標準函式庫", _version(tree, version), files, source=RUST_REPO, license="MIT OR Apache-2.0",
                     notes=[note])


class Spdx:
    def __init__(self) -> None:
        self.tree: GitTree | None = None

    def __call__(self, identifier: str) -> str:
        if self.tree is None:
            self.tree = GitTree(SPDX_REPO, SPDX_COMMIT)
        path = f"text/{identifier}.txt"
        if path not in self.tree.entries:
            raise ValueError(f"SPDX {SPDX_REF} 沒有 {identifier} 的全文")
        return decode(self.tree.read(path)) or ""


def crate_components(lock_texts: Iterable[str], spdx: Callable[[str], str]) -> list[Component]:
    crates = sorted({c for text in lock_texts for c in cargo_crates.crates(text)},
                    key=lambda c: (c.name, c.version))

    def one(crate: cargo_crates.Crate) -> Component:
        data = download_verified([crate.url], crate.checksum, f"crates/{crate.name}-{crate.version}.crate")
        return cargo_crates.component(crate, data, spdx)

    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, crates))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"寫入 {path.relative_to(ROOT).as_posix()}（{len(text.encode('utf-8')):,} 位元組）")


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        print("用法：python -m tools.third_party_licenses（不接參數）", file=sys.stderr)
        return 2
    script = ffmpeg_sources.BUILD_SCRIPT.read_text(encoding="utf-8-sig")
    pins = ffmpeg_sources.pins(script)
    uv_version = _ps_var(script, "UvVersion")
    notices = ffmpeg_sources.NOTICES.read_text(encoding="utf-8")
    spdx = Spdx()
    try:
        libraries, cargo_trees = ffmpeg_components(pins, notices)
        uv = GitTree(UV_REPO, uv_version)
        toolchain = re.search(r'^channel = "([\d.]+)"$', uv.read("rust-toolchain.toml").decode("utf-8"), re.M)
        if toolchain is None:
            raise ValueError("uv 的 rust-toolchain.toml 裡找不到 channel")
        rust_version = toolchain.group(1)
        ffmpeg_crates = crate_components((t.read("Cargo.lock").decode("utf-8") for t in cargo_trees), spdx)
        uv_crates = crate_components([uv.read("Cargo.lock").decode("utf-8")], spdx)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    generated = "由 python -m tools.third_party_licenses 產生，不要手動修改。"
    btbn = f"BtbN/FFmpeg-Builds：{pins.btbn_commit}（scripts.d，{btbn_stages.TARGET}-{btbn_stages.VARIANT} {btbn_stages.ADDINS_STR}）"
    _write(FFMPEG_LIBRARIES, render([
        "FFmpeg（bin\\ffmpeg.exe、bin\\ffprobe.exe）靜態連入的函式庫",
        f"FFmpeg build：{pins.build}", btbn, generated, "",
        "BtbN 的建置腳本為這個 build 建了下面的函式庫，裝進同一個目錄給 FFmpeg 靜態連結；有些只給其他函式庫",
        "用，或這個 build 沒有啟用，所以清單只會比實際連入的多、不會少。每個函式庫附上它原始碼裡的授權檔",
        "（略過測試、範例等資料夾）。原始碼的取得方式見 THIRD_PARTY_NOTICES.txt 的 FFmpeg 一節：",
        "建置腳本（FFmpeg-Builds-<commit>.tar.gz）以 commit 釘住了這裡的每一個來源。",
    ], libraries, unit="個元件"))
    rav1e_librsvg = "、".join(f"{PurePosixPath(t.url).name.removesuffix('.git')} {t.commit}" for t in cargo_trees)
    _write(FFMPEG_CRATES, render([
        "FFmpeg 靜態連入的 Rust 套件（rav1e、librsvg 用 cargo 建置）",
        f"FFmpeg build：{pins.build}", btbn, f"Cargo.lock：{rav1e_librsvg}", generated, "",
        "列的是這兩個 Cargo.lock 裡所有 crates.io 的套件（含只在其他平台、測試或建置時用到的），",
        "下載後都驗過 Cargo.lock 的 checksum。",
    ], [rust_std(rust_version, "BtbN 的建置環境用 rustup 安裝當時的 stable 版，沒有釘版本；這裡附 "
                               f"{rust_version} 的授權檔"), *ffmpeg_crates], unit="個元件"))
    _write(UV_CRATES, render([
        "uv（bin\\uv.exe）靜態連入的 Rust 套件",
        f"uv：{uv_version}（{uv.commit}）", generated, "",
        "列的是 uv 的 Cargo.lock 裡所有 crates.io 的套件（含只在其他平台、測試或建置時用到的），",
        "下載後都驗過 Cargo.lock 的 checksum。",
    ], [rust_std(rust_version, "uv 的 rust-toolchain.toml 釘的版本"), *uv_crates], unit="個元件"))
    return 0


def _ps_var(script: str, name: str) -> str:
    match = re.search(rf'^\${name} = "([^"]+)"', script, re.M)
    if match is None:
        raise ValueError(f"build_release.ps1 沒有 ${name}")
    return match.group(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    sys.exit(main(sys.argv[1:]))
