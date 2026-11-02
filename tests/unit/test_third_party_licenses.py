"""ffmpeg 靜態連入的函式庫與 Rust 套件的授權清單（#274）：tools/third_party_licenses.py。

產生要連網（python -m tools.third_party_licenses），這裡測兩件事：
- 已 commit 的清單是照 build_release.ps1 現在的釘版產生的：升級 ffmpeg 或 uv 而沒有重新產生時紅燈；
- 產生器裡不連網的部分：git 樹裡認授權檔、子模組、DEPS、tar.gz。
"""
import io
import re
import subprocess
import tarfile
from pathlib import Path

import pytest

from tools import ffmpeg_sources, license_texts, third_party_licenses

ROOT = Path(__file__).resolve().parents[2]
REGENERATE = "清單過期：在 repo 根目錄執行 python -m tools.third_party_licenses 重新產生"


def _script() -> str:
    return ffmpeg_sources.BUILD_SCRIPT.read_text(encoding="utf-8-sig")


def _uv_version() -> str:
    match = re.search(r'^\$UvVersion = "([^"]+)"', _script(), re.M)
    assert match
    return match.group(1)


class TestCommittedLists:
    @pytest.mark.parametrize("path", [third_party_licenses.FFMPEG_LIBRARIES, third_party_licenses.FFMPEG_CRATES])
    def test_ffmpeg_lists_match_the_pinned_build(self, path):
        pins = ffmpeg_sources.pins(_script())
        text = path.read_text(encoding="utf-8")

        assert license_texts.header_value(text, "FFmpeg build") == pins.build, REGENERATE
        btbn = license_texts.header_value(text, "BtbN/FFmpeg-Builds") or ""
        assert btbn.startswith(f"{pins.btbn_commit}（"), REGENERATE

    def test_uv_list_matches_the_pinned_version(self):
        text = third_party_licenses.UV_CRATES.read_text(encoding="utf-8")

        assert (license_texts.header_value(text, "uv") or "").startswith(f"{_uv_version()}（"), REGENERATE

    @pytest.mark.parametrize("path", [third_party_licenses.FFMPEG_LIBRARIES, third_party_licenses.FFMPEG_CRATES,
                                      third_party_licenses.UV_CRATES])
    def test_every_component_has_license_texts(self, path):
        text = path.read_text(encoding="utf-8")
        listing, _, texts = text.partition(f"\n{license_texts.TEXTS_START}\n")
        numbers = {int(n) for n in re.findall(r" \[(\d+)\]", listing.split(license_texts.LISTING_START, 1)[1])}
        headers = re.findall(rf"^{license_texts.RULE}\n\[(\d+)\] ", texts, re.M)

        assert numbers and sorted(numbers) == [int(n) for n in headers] == list(range(1, len(headers) + 1))

    def test_libraries_cover_the_toolchain_runtime(self):
        text = third_party_licenses.FFMPEG_LIBRARIES.read_text(encoding="utf-8")

        # winpthreads（MIT）與 GCC 的執行期函式庫例外條款是一定會連入的
        assert "mingw-w64-libraries/winpthreads/COPYING" in text
        assert "GCC RUNTIME LIBRARY EXCEPTION" in text


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def upstream(tmp_path, monkeypatch) -> tuple[Path, str]:
    """本機的 repo：根目錄與 third_party 的授權檔、測試資料夾裡的授權檔、一個子模組。"""
    monkeypatch.setattr(third_party_licenses, "CACHE", tmp_path / "cache")
    repo = tmp_path / "group" / "lib.git"
    repo.mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    files = {"LICENSE": b"Copyright A\r\n", "third_party/yuv/LICENSE": b"Copyright Y",
             "tests/data/LICENSE": b"test fixture", "src/license.c": b"int x;",
             ".gitmodules": b'[submodule "dep"]\n\tpath = deps/hwy\n\turl = ../hwy.git\n'}
    for rel, data in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
    _git("add", ".", cwd=repo)
    _git("update-index", "--add", "--cacheinfo", f"160000,{'e' * 40},deps/hwy", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo, _git("rev-parse", "HEAD", cwd=repo)


class TestGitTree:
    def test_license_files_skip_tests_and_code(self, upstream):
        repo, commit = upstream
        tree = third_party_licenses.GitTree(repo.as_uri(), commit)

        assert [(f.path, f.text) for f in tree.license_files()] == [
            ("LICENSE", "Copyright A"), ("third_party/yuv/LICENSE", "Copyright Y")]
        assert [f.path for f in tree.license_files(removed=["third_party"])] == ["LICENSE"]

    def test_submodules_resolve_relative_urls(self, upstream):
        repo, commit = upstream
        tree = third_party_licenses.GitTree(repo.as_uri(), commit)

        assert tree.submodules() == [("deps/hwy", (repo.parent / "hwy.git").as_uri(), "e" * 40)]
        assert tree.submodules(only=["other"]) == []

    def test_wrong_commit_is_refused(self, upstream):
        repo, _ = upstream

        with pytest.raises(ValueError, match="抓不到"):
            third_party_licenses.GitTree(repo.as_uri(), "0" * 40)


def test_gclient_deps_are_parsed_without_running_them():
    deps = """
use_relative_paths = True
vars = {
  'google_git': 'https://github.com/google',
  'effcee_revision': 'f8e8',
}
deps = {
  'third_party/effcee': Var('google_git') + '/effcee.git@' + Var('effcee_revision'),
}
"""
    assert third_party_licenses.gclient_deps(deps) == {
        "third_party/effcee": ("https://github.com/google/effcee.git", "f8e8")}

    with pytest.raises(ValueError, match="看不懂的寫法"):
        third_party_licenses.gclient_deps("deps = {'x': __import__('os').getcwd()}")


def test_tarball_license_files_drop_the_top_folder():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in {"proxy-libintl-0.5/COPYING": b"LGPL", "proxy-libintl-0.5/test/LICENSE": b"x",
                           "proxy-libintl-0.5/libintl.c": b"code"}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    files = third_party_licenses.tarball_license_files(buffer.getvalue())

    assert [(f.path, f.text) for f in files] == [("COPYING", "LGPL")]


def test_svn_listing_links():
    parser = third_party_licenses._Links()
    parser.feed('<ul><li><a href="../">..</a></li><li><a href="COPYING">COPYING</a></li>'
                '<li><a href="doc/">doc/</a></li></ul>')

    assert parser.links == ["COPYING", "doc/"]


def test_leading_comment_of_a_header():
    source = "/*\n * Copyright (c) NVIDIA\n *\n * Permission is hereby granted\n */\n\n/** doc */\nint x;\n"

    assert third_party_licenses.leading_comment(source) == "Copyright (c) NVIDIA\n\nPermission is hereby granted"
    assert third_party_licenses.leading_comment("#include <x.h>\n/* later */") is None


def test_license_in_headers_when_the_repo_has_no_license_file(upstream, monkeypatch):
    repo, _ = upstream
    (repo / "LICENSE").unlink()
    (repo / "third_party" / "yuv" / "LICENSE").unlink()
    (repo / "include").mkdir()
    (repo / "include" / "api.h").write_bytes(b"/*\n * MIT, Copyright (c) Vendor\n */\nint api;\n")
    _git("add", "-A", ".", cwd=repo)
    _git("commit", "-q", "-m", "headers", cwd=repo)
    commit = _git("rev-parse", "HEAD", cwd=repo)
    tree = third_party_licenses.GitTree(repo.as_uri(), commit)

    with pytest.raises(ValueError, match="找不到授權檔"):
        third_party_licenses._git_component("lib", tree, commit)

    monkeypatch.setattr(third_party_licenses, "LICENSE_IN_HEADERS",
                        {repo.as_uri().removesuffix(".git").lower(): ("include/",)})
    component = third_party_licenses._git_component("lib", tree, commit)

    assert [(f.path, f.text) for f in component.files] == [("include/api.h 開頭的註解", "MIT, Copyright (c) Vendor")]
