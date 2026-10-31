"""tools/ffmpeg_sources.py：發版時準備 FFmpeg 的原始碼附件並驗證（#274）。

真的抓 FFmpeg 與 BtbN 的原始碼要連網，由 CI 的 portable job 在 Windows 上跑一次（ci.yml）。
這裡用本機的 git repo 與自己做的 zip，測驗證本身：釘的 commit 對不上、授權全文不同、不是 LGPLv3 build、
configure 參數和 THIRD_PARTY_NOTICES.txt 寫的不同時，都要擋下來。
"""
import hashlib
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools import ffmpeg_sources

ROOT = Path(__file__).resolve().parents[2]
CONFIGURE = "--prefix=/ffbuild/prefix --enable-version3 --enable-libopus --extra-version=20260930"
LGPL = b"GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3\n"
GPL = b"GNU GENERAL PUBLIC LICENSE\nVersion 3\n"


def _script() -> str:
    return (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")


def _exe(configure: str = CONFIGURE, license_text: str = "LGPL version 3 or later") -> bytes:
    """像 BtbN 的 exe 一樣內嵌 configure 參數與各函式庫的授權字串。"""
    parts = [b"MZ\x90\x00", configure.encode(), b"\x00\x00"]
    for lib in ("libavcodec", "libavformat", "libavutil"):
        parts += [f"{lib} license: {license_text}".encode(), b"\x00"]
    return b"".join(parts)


def _build_zip(path: Path, *, license_txt: bytes = LGPL, exe: bytes | None = None) -> Path:
    top = "ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-9.0"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{top}/LICENSE.txt", license_txt)
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            archive.writestr(f"{top}/bin/{name}", _exe() if exe is None else exe)
    return path


def _notices(configure: str = CONFIGURE) -> str:
    """THIRD_PARTY_NOTICES.txt 的寫法：configure 參數折成好幾行，前後是空行。"""
    words = configure.split()
    return "原始碼\n\n    " + " ".join(words[:2]) + "\n    " + " ".join(words[2:]) + "\n\n其中\n"


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def upstream(tmp_path) -> tuple[str, str]:
    """有一個 commit 的本機 repo（假的 FFmpeg）：回傳（file:// 網址，commit）。"""
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    (repo / "COPYING.LGPLv3").write_bytes(LGPL)
    (repo / "COPYING.GPLv3").write_bytes(GPL)
    (repo / "configure").write_text("#!/bin/sh\n", encoding="ascii")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo.as_uri(), _git("rev-parse", "HEAD", cwd=repo)


@pytest.fixture
def licenses(tmp_path) -> Path:
    directory = tmp_path / "licenses"
    directory.mkdir()
    # commit 進 repo 的版本：Windows 的 checkout 是 CRLF
    (directory / "COPYING.LGPLv3.txt").write_bytes(LGPL.replace(b"\n", b"\r\n"))
    (directory / "COPYING.GPLv3.txt").write_bytes(GPL)
    return directory


class TestPins:
    def test_reads_build_release_ps1(self):
        pins = ffmpeg_sources.pins(_script())

        assert pins.asset == f"{pins.build}-win64-lgpl-9.0.zip"
        assert pins.url == (f"https://github.com/BtbN/FFmpeg-Builds/releases/download/"
                            f"{pins.tag}/{pins.asset}")
        assert pins.release_assets == (
            pins.asset, f"FFmpeg-{pins.ffmpeg_commit}.tar.gz",
            f"FFmpeg-Builds-{pins.btbn_commit}.tar.gz", "SHA256SUMS")

    def test_ffmpeg_commit_must_match_the_build_name(self):
        script = _script().replace('$FfmpegCommit = "2a571b6', '$FfmpegCommit = "3a571b6')

        with pytest.raises(ValueError, match="對不上"):
            ffmpeg_sources.pins(script)

    @pytest.mark.parametrize("name", ["FfmpegCommit", "BtbnCommit"])
    def test_commits_must_be_written_in_full(self, name):
        script = _script()
        start = script.index(f'${name} = "') + len(f'${name} = "')
        short = script[:start + 10] + script[start + 40:]

        with pytest.raises(ValueError, match="40 碼"):
            ffmpeg_sources.pins(short)

    def test_missing_pin_is_an_error(self):
        with pytest.raises(ValueError, match=r"\$BtbnCommit"):
            ffmpeg_sources.pins(_script().replace("$BtbnCommit = ", "$Other = "))


class TestSourceCheckout:
    def test_archives_the_pinned_commit(self, tmp_path, upstream):
        url, commit = upstream
        checkout = ffmpeg_sources.SourceCheckout(url, commit, tmp_path / "work")

        archive = checkout.archive(tmp_path / f"FFmpeg-{commit}.tar.gz")

        with tarfile.open(archive) as tar:
            names = tar.getnames()
        assert f"FFmpeg-{commit}/configure" in names
        assert f"FFmpeg-{commit}/COPYING.GPLv3" in names
        assert checkout.read("COPYING.LGPLv3") == LGPL

    def test_unknown_commit_fails(self, tmp_path, upstream):
        url, _ = upstream

        with pytest.raises(ValueError, match="git fetch"):
            ffmpeg_sources.SourceCheckout(url, "0" * 40, tmp_path / "work")


class TestLicenseProblems:
    def test_matching_licenses_pass(self, tmp_path, upstream, licenses):
        url, commit = upstream
        checkout = ffmpeg_sources.SourceCheckout(url, commit, tmp_path / "work")

        assert ffmpeg_sources.license_problems(_build_zip(tmp_path / "b.zip"), checkout, licenses) == []

    def test_committed_text_that_differs_fails(self, tmp_path, upstream, licenses):
        url, commit = upstream
        checkout = ffmpeg_sources.SourceCheckout(url, commit, tmp_path / "work")
        (licenses / "COPYING.GPLv3.txt").write_bytes(b"GNU GENERAL PUBLIC LICENSE\nVersion 2\n")

        (problem,) = ffmpeg_sources.license_problems(_build_zip(tmp_path / "b.zip"), checkout, licenses)

        assert "COPYING.GPLv3.txt" in problem

    def test_gpl_build_zip_fails(self, tmp_path, upstream, licenses):
        # BtbN 的 GPL build 附的 LICENSE.txt 是 GPLv3
        url, commit = upstream
        checkout = ffmpeg_sources.SourceCheckout(url, commit, tmp_path / "work")

        (problem,) = ffmpeg_sources.license_problems(
            _build_zip(tmp_path / "b.zip", license_txt=GPL), checkout, licenses)

        assert "不是 LGPL build" in problem


class TestBinaryProblems:
    def test_lgplv3_build_described_by_the_notices_passes(self, tmp_path):
        assert ffmpeg_sources.binary_problems(_build_zip(tmp_path / "b.zip"), _notices()) == []

    @pytest.mark.parametrize("configure", [
        CONFIGURE.replace("--enable-version3", "--enable-gpl --enable-version3"),
        CONFIGURE + " --enable-nonfree",
        CONFIGURE.replace("--enable-version3 ", ""),
    ])
    def test_gpl_nonfree_or_lgplv2_build_fails(self, tmp_path, configure):
        archive = _build_zip(tmp_path / "b.zip", exe=_exe(configure))

        problems = ffmpeg_sources.binary_problems(archive, _notices(configure))

        assert problems and all("不是 LGPLv3 build" in p for p in problems)

    def test_other_license_string_fails(self, tmp_path):
        archive = _build_zip(tmp_path / "b.zip", exe=_exe(license_text="GPL version 3 or later"))

        problems = ffmpeg_sources.binary_problems(archive, _notices())

        assert len(problems) == 2 and all("內嵌的授權" in p for p in problems)

    def test_notices_with_other_configure_fail(self, tmp_path):
        archive = _build_zip(tmp_path / "b.zip")

        problems = ffmpeg_sources.binary_problems(archive, _notices(CONFIGURE + " --enable-libfoo"))

        assert problems == [f"{exe} 的 configure 參數和 THIRD_PARTY_NOTICES.txt 寫的不同"
                            for exe in ("ffmpeg.exe", "ffprobe.exe")]

    def test_real_notices_configure_is_an_lgplv3_build(self):
        notices = ffmpeg_sources.NOTICES.read_text(encoding="utf-8")

        flags = (ffmpeg_sources.notices_configure(notices) or "").split()

        assert "--enable-version3" in flags
        assert not {"--enable-gpl", "--enable-nonfree"} & set(flags)
        assert "--disable-libx264" in flags


class TestDownloadAndSums:
    def test_cached_file_with_the_right_hash_is_reused(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "a.zip").write_bytes(b"zip")
        out = tmp_path / "out"
        out.mkdir()

        path = ffmpeg_sources.download_verified(
            "https://invalid.example/a.zip", out / "a.zip", hashlib.sha256(b"zip").hexdigest(), cache)

        assert path.read_bytes() == b"zip"

    def test_sha256sums_format(self, tmp_path):
        (tmp_path / "a.tar.gz").write_bytes(b"a")
        (tmp_path / "b.zip").write_bytes(b"b")

        sums = ffmpeg_sources.write_sums(tmp_path, ["b.zip", "a.tar.gz"])

        # sha256sum -c 的格式：雜湊、兩個空白、檔名；LF 換行
        assert sums.read_bytes() == (
            f"{hashlib.sha256(b'b').hexdigest()}  b.zip\n"
            f"{hashlib.sha256(b'a').hexdigest()}  a.tar.gz\n").encode()
