"""tools/release_assets.py：發版的附件、標題與 release notes（#278）。

真的建置、抓 FFmpeg 原始碼與上傳 GitHub Release 要在 Windows 與 GitHub 上跑：prepare 與 check 由 CI 的
portable job 每個 PR 跑一次，上傳與公開由 #279 實跑。這裡測判斷本身：附件缺一個、多一個、雜湊不符，或草稿上
的附件和建置的不同時，都要擋下來；release notes 標 beta、帶「已知限制」，連結都指向這個 tag。
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

from tools import ffmpeg_sources, portable_zip, release_assets

ROOT = Path(__file__).resolve().parents[2]
REPO = "Wade0325/AI_translate"
TAG = "v0.1.0-rc.1"
PINS = ffmpeg_sources.pins((ROOT / "build_release.ps1").read_text(encoding="utf-8-sig"))
EXPECTED = release_assets.expected_assets(TAG, PINS)
# Markdown 連結的目標不是網址（沒有 scheme）
RELATIVE_LINK = re.compile(r"\]\((?![a-zA-Z][a-zA-Z0-9+.-]*:)[^)]*\)")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assets(directory: Path, expected=EXPECTED) -> Path:
    """每個附件都放一點內容，SHA256SUMS 列出其他每一個。"""
    directory.mkdir(parents=True, exist_ok=True)
    names = [name for name in expected if name != release_assets.SUMS]
    for name in names:
        (directory / name).write_bytes(f"內容 {name}".encode())
    ffmpeg_sources.write_sums(directory, names)
    return directory


class TestTitle:
    @pytest.mark.parametrize("tag", ["v0.1.0", "v0.1.0-rc.1", "v1.20.3", "v0.1.0-beta.2"])
    def test_release_tags_get_a_beta_title(self, tag):
        assert release_assets.title(tag) == f"Mimiji {tag} beta"

    @pytest.mark.parametrize("tag", ["vfoo", "v1", "v1.2", "0.1.0", "v0.1.0-", "v0.1.0 beta", 'v0.1.0"', "v0.1.0/x"])
    def test_other_tags_are_rejected_before_building(self, tag):
        with pytest.raises(ValueError, match="不是發版的格式"):
            release_assets.title(tag)


class TestExpectedAssets:
    def test_package_then_ffmpeg_sources_then_sums(self):
        assert EXPECTED == (
            f"{portable_zip.PRODUCT}-{TAG}-win64.zip",
            PINS.asset,
            f"FFmpeg-{PINS.ffmpeg_commit}.tar.gz",
            f"FFmpeg-Builds-{PINS.btbn_commit}.tar.gz",
            "SHA256SUMS",
        )

    def test_zip_name_matches_what_portable_zip_checks(self):
        assert portable_zip.ZIP_NAME.fullmatch(release_assets.zip_name(TAG))["version"] == TAG


class TestPrepare:
    def test_adds_the_package_and_hashes_every_asset(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        package = build / release_assets.zip_name("ci")
        package.write_bytes(b"PK zip")

        def fake_fetch(outdir: Path, script: str) -> list[Path]:
            # ffmpeg_sources.fetch 的行為：三個附件加上只列它們的 SHA256SUMS
            assert "$FfmpegCommit" in script
            outdir.mkdir(parents=True, exist_ok=True)
            names = list(PINS.release_assets[:-1])
            for name in names:
                (outdir / name).write_bytes(name.encode())
            ffmpeg_sources.write_sums(outdir, names)
            return [outdir / name for name in PINS.release_assets]

        out = tmp_path / "assets"
        paths = release_assets.prepare("ci", out, build, fetch=fake_fetch)

        expected = release_assets.expected_assets("ci", PINS)
        assert [path.name for path in paths] == list(expected)
        assert release_assets.check(out, expected) == []
        sums, problems = release_assets.parse_sums((out / "SHA256SUMS").read_text(encoding="ascii"))
        assert problems == []
        assert sums[package.name] == _sha256(b"PK zip")

    def test_missing_package_fails_before_fetching(self, tmp_path):
        def fetch_must_not_run(outdir: Path, script: str) -> list[Path]:
            raise AssertionError("沒有發布包時不該抓 FFmpeg 原始碼")

        with pytest.raises(ValueError, match="找不到發布包"):
            release_assets.prepare("ci", tmp_path / "out", tmp_path, fetch=fetch_must_not_run)


class TestCheck:
    def test_complete_assets_pass(self, tmp_path):
        assert release_assets.check(_assets(tmp_path / "a"), EXPECTED) == []

    def test_missing_asset_fails(self, tmp_path):
        directory = _assets(tmp_path / "a")
        (directory / PINS.btbn_archive).unlink()
        assert release_assets.check(directory, EXPECTED) == [f"缺少附件：{PINS.btbn_archive}"]

    def test_missing_folder_fails(self, tmp_path):
        assert release_assets.check(tmp_path / "nothing", EXPECTED) == [f"找不到附件的資料夾 {tmp_path / 'nothing'}"]

    def test_extra_file_fails(self, tmp_path):
        directory = _assets(tmp_path / "a")
        (directory / "app.db").write_bytes(b"x")
        assert release_assets.check(directory, EXPECTED) == ["多出不該上傳的檔案：app.db"]

    def test_empty_asset_fails(self, tmp_path):
        directory = _assets(tmp_path / "a")
        (directory / EXPECTED[0]).write_bytes(b"")
        assert release_assets.check(directory, EXPECTED) == [f"附件是空的：{EXPECTED[0]}"]

    def test_changed_asset_fails(self, tmp_path):
        directory = _assets(tmp_path / "a")
        (directory / EXPECTED[0]).write_bytes(b"changed")
        assert release_assets.check(directory, EXPECTED) == [f"{EXPECTED[0]} 的 SHA-256 和 SHA256SUMS 寫的不同"]

    def test_sums_must_list_every_asset_and_nothing_else(self, tmp_path):
        directory = _assets(tmp_path / "a")
        names = [EXPECTED[1], EXPECTED[2], EXPECTED[3]]
        ffmpeg_sources.write_sums(directory, names)  # 只有 FFmpeg 的那一份
        with (directory / "SHA256SUMS").open("a", encoding="ascii", newline="\n") as f:
            f.write(f"{'0' * 64}  other.zip\n")
        assert release_assets.check(directory, EXPECTED) == [
            f"SHA256SUMS 沒有列出 {EXPECTED[0]}", "SHA256SUMS 列了不是附件的 other.zip"]

    def test_malformed_and_duplicate_lines_fail(self):
        sums, problems = release_assets.parse_sums(f"{'a' * 64}  x.zip\n{'b' * 64}  x.zip\n{'c' * 64} y.zip\n")
        assert sums == {"x.zip": "a" * 64}
        assert problems == ["SHA256SUMS 重複列了 x.zip",
                            f"SHA256SUMS 第 3 行不是「SHA-256、兩個空白、檔名」：'{'c' * 64} y.zip'"]


README = """\
# 標題

## 🔒 資料與隱私

不相干的內容

---

## 🚧 已知限制

目前是測試版：

- **一項**：見[資料與隱私](#-資料與隱私)與 [ADR 0010](docs/adr/0010-no-code-signing.md)、[本機](./tools/x.md)。
- **兩項**：見 [Microsoft](https://learn.microsoft.com/x) 或 <mailto:a@example.com>。

---

## 🔧 開發者指南

不該出現
"""


class TestKnownLimitations:
    def test_takes_the_section_until_the_separator(self):
        text = release_assets.known_limitations(README, REPO, TAG)
        assert text.startswith("目前是測試版：")
        assert "**兩項**" in text
        assert "不該出現" not in text and "---" not in text and "不相干" not in text

    def test_section_ends_at_the_next_heading_without_separator(self):
        readme = "## 已知限制\n\n- 一項\n\n## 下一節\n\n- 不該出現\n"
        assert release_assets.known_limitations(readme, REPO, TAG) == "- 一項"

    def test_relative_links_point_at_the_tag(self):
        text = release_assets.known_limitations(README, REPO, TAG)
        blob = f"https://github.com/{REPO}/blob/{TAG}"
        assert f"[資料與隱私]({blob}/README.md#-資料與隱私)" in text
        assert f"[ADR 0010]({blob}/docs/adr/0010-no-code-signing.md)" in text
        assert f"[本機]({blob}/tools/x.md)" in text
        assert "[Microsoft](https://learn.microsoft.com/x)" in text
        assert "<mailto:a@example.com>" in text

    def test_missing_section_fails(self):
        with pytest.raises(ValueError, match="找不到「## 已知限制」"):
            release_assets.known_limitations("## 安裝\n\n內容\n", REPO, TAG)

    def test_empty_section_fails(self):
        with pytest.raises(ValueError, match="是空的"):
            release_assets.known_limitations("## 🚧 已知限制\n\n---\n", REPO, TAG)

    def test_the_real_readme_has_the_section(self):
        # 改 README 的標題或刪掉這一節時在這裡紅燈，不要等到推 tag 才失敗
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        text = release_assets.known_limitations(readme, REPO, TAG)
        assert "說話者編號" in text
        assert RELATIVE_LINK.findall(text) == []


class TestReleaseNotes:
    def _notes(self) -> str:
        return release_assets.release_notes(TAG, REPO, (ROOT / "README.md").read_text(encoding="utf-8"), PINS)

    def test_marks_beta_and_has_known_limitations(self):
        notes = self._notes()
        assert notes.startswith("> **這是測試版（beta）**")
        assert "\n## 已知限制\n" in notes

    def test_names_every_asset(self):
        notes = self._notes()
        for name in EXPECTED:
            assert f"`{name}`" in notes or f"**`{name}`**" in notes

    def test_links_are_absolute_and_point_at_the_tag(self):
        notes = self._notes()
        assert RELATIVE_LINK.findall(notes) == []
        assert f"https://github.com/{REPO}/blob/{TAG}/README.md#-安裝" in notes

    def test_rejects_a_bad_tag(self):
        with pytest.raises(ValueError, match="不是發版的格式"):
            release_assets.release_notes("latest", REPO, README, PINS)


def _release(directory: Path, *, draft: bool = True, **overrides) -> dict:
    """GitHub API 回傳的 release：附件都上傳完成，大小與 digest 和 directory 裡的相同。"""
    assets = [{"name": name, "state": "uploaded", "size": (directory / name).stat().st_size,
               "digest": f"sha256:{_sha256((directory / name).read_bytes())}"} for name in EXPECTED]
    release = {"tag_name": TAG, "draft": draft, "prerelease": True, "name": release_assets.title(TAG),
               "body": "> **這是測試版（beta）**\n\n## 已知限制\n\n- 一項\n\n## What's Changed\n", "assets": assets}
    release.update(overrides)
    return release


class TestVerifyRelease:
    def test_matching_draft_passes(self, tmp_path):
        directory = _assets(tmp_path / "a")
        assert release_assets.verify_release(_release(directory), TAG, directory, EXPECTED, draft=True) == []

    def test_published_release_passes_after_publishing(self, tmp_path):
        directory = _assets(tmp_path / "a")
        release = _release(directory, draft=False)
        assert release_assets.verify_release(release, TAG, directory, EXPECTED, draft=False) == []

    def test_draft_state_must_match_the_step(self, tmp_path):
        directory = _assets(tmp_path / "a")
        assert release_assets.verify_release(_release(directory, draft=False), TAG, directory, EXPECTED,
                                             draft=True) == ["release 應該還是草稿，draft 是 False"]

    def test_must_be_a_beta_prerelease_for_this_tag(self, tmp_path):
        directory = _assets(tmp_path / "a")
        release = _release(directory, tag_name="v9.9.9", prerelease=False, name="Mimiji v0.1.0-rc.1", body="")
        assert release_assets.verify_release(release, TAG, directory, EXPECTED, draft=True) == [
            f"release 的 tag 是 v9.9.9，不是 {TAG}",
            "release 沒有標成 prerelease（prerelease 是 False）",
            f"release 的標題是「Mimiji {TAG}」，應該是「Mimiji {TAG} beta」",
            "release notes 沒有 beta 的提醒或「已知限制」一節",
        ]

    def test_missing_and_extra_assets_fail(self, tmp_path):
        directory = _assets(tmp_path / "a")
        release = _release(directory)
        release["assets"] = [a for a in release["assets"] if a["name"] != PINS.ffmpeg_archive]
        release["assets"].append({"name": "notes.md", "state": "uploaded", "size": 1, "digest": None})
        assert release_assets.verify_release(release, TAG, directory, EXPECTED, draft=True) == [
            f"release 缺少附件：{PINS.ffmpeg_archive}", "release 多出附件：notes.md"]

    def test_unfinished_wrong_size_or_wrong_digest_fails(self, tmp_path):
        directory = _assets(tmp_path / "a")
        release = _release(directory)
        release["assets"][0]["state"] = "starter"
        release["assets"][1]["size"] = 1
        release["assets"][2]["digest"] = "sha256:" + "0" * 64
        assert release_assets.verify_release(release, TAG, directory, EXPECTED, draft=True) == [
            f"附件 {EXPECTED[0]} 沒有上傳完成（state 是 starter）",
            f"附件 {EXPECTED[1]} 的大小是 1，本機是 {(directory / EXPECTED[1]).stat().st_size}",
            f"附件 {EXPECTED[2]} 的 SHA-256 和本機不同（GitHub 算的是 sha256:{'0' * 64}）",
        ]

    def test_asset_without_digest_is_checked_by_size(self, tmp_path):
        directory = _assets(tmp_path / "a")
        release = _release(directory)
        release["assets"][0]["digest"] = None
        assert release_assets.verify_release(release, TAG, directory, EXPECTED, draft=True) == []


class TestCli:
    def test_check_fails_with_problems(self, tmp_path, capsys):
        directory = _assets(tmp_path / "a", release_assets.expected_assets("ci", PINS))
        (directory / "extra.txt").write_text("x", encoding="utf-8")
        assert release_assets.main(["check", "ci", str(directory)]) == 1
        assert "多出不該上傳的檔案：extra.txt" in capsys.readouterr().err

    def test_check_passes(self, tmp_path, capsys):
        directory = _assets(tmp_path / "a", release_assets.expected_assets("ci", PINS))
        assert release_assets.main(["check", "ci", str(directory)]) == 0
        assert "5 個附件都在" in capsys.readouterr().out

    def test_notes_writes_the_file(self, tmp_path):
        out = tmp_path / "notes.md"
        assert release_assets.main(["notes", TAG, REPO, str(out)]) == 0
        assert "## 已知限制" in out.read_text(encoding="utf-8")

    def test_bad_tag_fails(self, capsys):
        assert release_assets.main(["title", "vfoo"]) == 1
        assert "不是發版的格式" in capsys.readouterr().err

    def test_verify_release_reads_the_api_response(self, tmp_path):
        directory = _assets(tmp_path / "a")
        response = tmp_path / "release.json"
        response.write_text(json.dumps(_release(directory)), encoding="utf-8")
        assert release_assets.main(["verify-release", TAG, str(directory), str(response), "--draft"]) == 0
        assert release_assets.main(["verify-release", TAG, str(directory), str(response), "--published"]) == 1
