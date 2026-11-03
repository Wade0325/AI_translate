"""發版附件與 release notes（#278）：.github/workflows/release.yml 呼叫，判斷寫在這裡才能用 pytest 測。

推 v* tag 之後，release.yml 把下列檔案上傳到同一個 GitHub Release：

- Mimiji-<tag>-win64.zip：免安裝版（build_release.ps1 產生）。
- FFmpeg 的原始碼取得方式（#274，tools/ffmpeg_sources.py 準備並驗證）：BtbN 的 build zip、
  FFmpeg-<commit>.tar.gz、FFmpeg-Builds-<commit>.tar.gz。
- SHA256SUMS：以上每個檔案的 SHA-256（sha256sum -c 的格式）。

流程：Windows 的建置 job 只有讀取權限，執行 prepare 與 check，把附件交給發布的 job；發布的 job
（唯一有 contents: write 的 job）再 check 一次，建草稿、上傳，用 verify-release 確認草稿上的附件齊全、
大小與 SHA-256 相同，才以 prerelease 公開。任何一步失敗都只留下草稿（workflow 會刪掉），不會半發布。

用法（在 repo 根目錄執行；CI 的 portable job 用版本 ci 跑 prepare 與 check）：

    python -m tools.release_assets title <tag>                          # 印出 release 的標題
    python -m tools.release_assets prepare <版本> <outdir>               # 放進 zip、抓 FFmpeg 原始碼、寫 SHA256SUMS
    python -m tools.release_assets check <版本> <dir>                    # 附件剛好是該有的那幾個，SHA256SUMS 對得上
    python -m tools.release_assets notes <tag> <owner/repo> <輸出檔>      # 寫 release notes（beta、下載、已知限制）
    python -m tools.release_assets verify-release <tag> <dir> <release.json> (--draft | --published)

release notes 的「已知限制」取自 README.md 的「已知限制」一節，那裡是唯一來源（#281 定稿時只改 README）；
其中的相對連結改成指向這個 tag 的 README 與檔案。只用標準函式庫：發布的 job 用 runner 內建的 Python 執行。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from tools import ffmpeg_sources, portable_zip

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
SUMS = "SHA256SUMS"

# 發版的 tag：v<主>.<次>.<修補>，可以接 -rc.1 之類的預發布標記（SemVer）。其他寫法在建置之前就擋下，
# 不會以奇怪的名稱公開發布
TAG = re.compile(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?")
# 目前每一版都是測試版（#24）：標題與 release notes 都標 beta，以 prerelease 發布。之後要發正式版時，
# 改這裡與 release.yml 建草稿時的 prerelease=true，並回頭看 #24 的決定
BETA = "beta"
KNOWN_LIMITATIONS = "已知限制"
_LIMITATIONS_HEADING = re.compile(rf"^##\s+(?:\S+\s+)?{KNOWN_LIMITATIONS}\s*$")
_SECTION_END = re.compile(r"^(##\s|---\s*$)")
# Markdown 連結的目標（[文字](目標) 與 ![圖](目標)）；有 scheme 的（https:、mailto: 等）不動
_LINK_TARGET = re.compile(r"\]\((?![a-zA-Z][a-zA-Z0-9+.-]*:)([^)\s]+)\)")
_SUMS_LINE = re.compile(r"([0-9a-f]{64})  (\S.*)")


def check_tag(tag: str) -> str:
    """tag 符合發版的格式就原樣回傳，不符合時丟 ValueError。"""
    if not TAG.fullmatch(tag):
        raise ValueError(f"tag「{tag}」不是發版的格式：要寫成 v<主>.<次>.<修補>，例如 v0.1.0 或 v0.1.0-rc.1")
    return tag


def title(tag: str) -> str:
    """release 的標題，例如「Mimiji v0.1.0 beta」。"""
    return f"{portable_zip.PRODUCT} {check_tag(tag)} {BETA}"


def zip_name(version: str) -> str:
    """build_release.ps1 -Version <version> 產生的 zip 的檔名。"""
    return f"{portable_zip.PRODUCT}-{version}-win64.zip"


def expected_assets(version: str, pins: ffmpeg_sources.Pins) -> tuple[str, ...]:
    """要上傳的附件：發布包、FFmpeg 的三個檔案，SHA256SUMS 放最後。"""
    return (zip_name(version), *pins.release_assets)


def _pins() -> ffmpeg_sources.Pins:
    return ffmpeg_sources.pins(ffmpeg_sources.BUILD_SCRIPT.read_text(encoding="utf-8-sig"))


def prepare(version: str, outdir: Path, build_dir: Path = ROOT / "build", *,
            fetch: Callable[[Path, str], list[Path]] = ffmpeg_sources.fetch) -> list[Path]:
    """把 build_dir 裡的發布包、FFmpeg 的原始碼附件放進 outdir，寫涵蓋全部的 SHA256SUMS；回傳附件的路徑。

    fetch 準備並驗證 FFmpeg 的附件（ffmpeg_sources.fetch，它也寫一份只有 FFmpeg 的 SHA256SUMS，
    這裡換成涵蓋發布包的那一份）。
    """
    package = build_dir / zip_name(version)
    if not package.is_file():
        raise ValueError(f"找不到發布包 {package}：先執行 build_release.ps1 -Version {version}")
    outdir = outdir.resolve()
    ffmpeg = fetch(outdir, ffmpeg_sources.BUILD_SCRIPT.read_text(encoding="utf-8-sig"))
    shutil.copyfile(package, outdir / package.name)
    names = [package.name, *(path.name for path in ffmpeg if path.name != SUMS)]
    ffmpeg_sources.write_sums(outdir, names)
    return [outdir / name for name in (*names, SUMS)]


def parse_sums(text: str) -> tuple[dict[str, str], list[str]]:
    """SHA256SUMS 的內容 → （檔名 → SHA-256，格式的問題）。"""
    sums: dict[str, str] = {}
    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        match = _SUMS_LINE.fullmatch(line)
        if match is None:
            problems.append(f"{SUMS} 第 {number} 行不是「SHA-256、兩個空白、檔名」：{line!r}")
        elif match[2] in sums:
            problems.append(f"{SUMS} 重複列了 {match[2]}")
        else:
            sums[match[2]] = match[1]
    return sums, problems


def check(directory: Path, expected: Sequence[str]) -> list[str]:
    """directory 裡剛好是 expected 這些檔案、都不是空檔，SHA256SUMS 列出其他每一個且雜湊相符；回傳問題。"""
    if not directory.is_dir():
        return [f"找不到附件的資料夾 {directory}"]
    present = {path.name: path for path in directory.iterdir()}
    problems = [f"缺少附件：{name}" for name in expected if name not in present]
    problems += [f"多出不該上傳的檔案：{name}" for name in sorted(set(present) - set(expected))]
    problems += [f"{name} 不是檔案" for name in expected if name in present and not present[name].is_file()]
    problems += [f"附件是空的：{name}" for name in expected
                 if name in present and present[name].is_file() and present[name].stat().st_size == 0]
    if problems:
        return problems

    sums, problems = parse_sums(present[SUMS].read_text(encoding="ascii", errors="replace"))
    listed = [name for name in expected if name != SUMS]
    problems += [f"{SUMS} 沒有列出 {name}" for name in listed if name not in sums]
    problems += [f"{SUMS} 列了不是附件的 {name}" for name in sorted(set(sums) - set(listed))]
    for name in listed:
        if name in sums and ffmpeg_sources.sha256_of(present[name]) != sums[name]:
            problems.append(f"{name} 的 SHA-256 和 {SUMS} 寫的不同")
    return problems


def known_limitations(readme: str, repo: str, tag: str) -> str:
    """README 的「已知限制」一節的內容（不含標題），相對連結改成指向這個 tag。找不到或是空的時丟 ValueError。"""
    lines = readme.replace("\r\n", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if _LIMITATIONS_HEADING.match(line)), None)
    if start is None:
        raise ValueError(f"README.md 裡找不到「## {KNOWN_LIMITATIONS}」這一節")
    body = []
    for line in lines[start + 1:]:
        if _SECTION_END.match(line):
            break
        body.append(line)
    text = "\n".join(body).strip()
    if not text:
        raise ValueError(f"README.md 的「{KNOWN_LIMITATIONS}」是空的")
    return absolute_links(text, repo, tag)


def absolute_links(markdown: str, repo: str, tag: str) -> str:
    """把 README 裡的相對連結改成這個 tag 的網址：#錨點 指向 README.md，其他路徑指向 repo 裡的檔案。"""
    blob = f"https://github.com/{repo}/blob/{tag}"

    def absolute(match: re.Match[str]) -> str:
        target = match[1]
        if target.startswith("#"):
            return f"]({blob}/README.md{target})"
        return f"]({blob}/{target.removeprefix('./')})"

    return _LINK_TARGET.sub(absolute, markdown)


def release_notes(tag: str, repo: str, readme: str, pins: ffmpeg_sources.Pins) -> str:
    """release notes：beta 的提醒、下載哪個檔案、附件的說明與「已知限制」。

    GitHub 自動產生的變更清單（generate_release_notes）接在這段後面。
    """
    check_tag(tag)
    blob = f"https://github.com/{repo}/blob/{tag}"
    package = zip_name(tag)
    limitations = known_limitations(readme, repo, tag)
    return f"""\
> **這是測試版（{BETA}）**：可能還有沒發現的問題。遇到問題請到 [Issues](https://github.com/{repo}/issues/new/choose) 回報；Issue 是公開的，回報前先看 README 的[回報問題]({blob}/README.md#-回報問題)，不要附私人錄音或轉錄內容。

## 下載

一般使用者只要下載 **`{package}`**：Windows 免安裝版，解壓縮後雙擊 `{portable_zip.PRODUCT}.exe`。系統需求與安裝步驟見 [README]({blob}/README.md#-安裝)。

其他附件：

- `{SUMS}`：每個附件的 SHA-256。要確認下載的檔案完整，在 PowerShell 執行 `Get-FileHash .\\{package}`，印出的 Hash 和 `{SUMS}` 裡同一個檔名的那一行相同就對了（不分大小寫）。
- 免安裝版隨附的 FFmpeg（`bin\\ffmpeg.exe` 與 `bin\\ffprobe.exe`）的原始碼。依 FFmpeg 的授權（LGPL 第 3 版）和發布包放在同一個地方，一般使用者不用下載；說明見發布包裡的 `THIRD_PARTY_NOTICES.txt`。
  - `{pins.asset}`：這兩個檔案取自的 BtbN build 原檔。
  - `{pins.ffmpeg_archive}`：這個 build 的 FFmpeg 原始碼。
  - `{pins.btbn_archive}`：產生這個 build 的 BtbN 建置腳本。

## {KNOWN_LIMITATIONS}

{limitations}
"""


def _sha256_digest(path: Path) -> str:
    return f"sha256:{ffmpeg_sources.sha256_of(path)}"


def verify_release(release: Mapping[str, object], tag: str, directory: Path, expected: Sequence[str],
                   *, draft: bool) -> list[str]:
    """GitHub API 回傳的 release（GET /repos/{owner}/{repo}/releases/{id}）和這次要發布的相符；回傳問題。

    draft=True 是上傳後、公開前的檢查，False 是公開後的檢查。附件要剛好是 expected、都上傳完成、
    大小與本機相同；GitHub 有算 SHA-256（digest）時也要相同。
    """
    problems = []
    if release.get("tag_name") != tag:
        problems.append(f"release 的 tag 是 {release.get('tag_name')}，不是 {tag}")
    if release.get("draft") is not draft:
        problems.append(f"release 應該{'還是草稿' if draft else '已經公開'}，draft 是 {release.get('draft')}")
    if release.get("prerelease") is not True:
        problems.append(f"release 沒有標成 prerelease（prerelease 是 {release.get('prerelease')}）")
    if release.get("name") != title(tag):
        problems.append(f"release 的標題是「{release.get('name')}」，應該是「{title(tag)}」")
    body = release.get("body")
    if not isinstance(body, str) or f"## {KNOWN_LIMITATIONS}" not in body or BETA not in body:
        problems.append(f"release notes 沒有 beta 的提醒或「{KNOWN_LIMITATIONS}」一節")

    raw_assets = release.get("assets")
    assets: dict[str, Mapping[str, object]] = {}
    for asset in raw_assets if isinstance(raw_assets, list) else []:
        if isinstance(asset, Mapping) and isinstance(asset.get("name"), str):
            assets[str(asset["name"])] = asset
    problems += [f"release 缺少附件：{name}" for name in expected if name not in assets]
    problems += [f"release 多出附件：{name}" for name in sorted(set(assets) - set(expected))]
    for name in expected:
        asset = assets.get(name)
        if asset is None:
            continue
        local = directory / name
        if not local.is_file():
            problems.append(f"本機沒有附件 {name}，無法比對")
            continue
        if asset.get("state") != "uploaded":
            problems.append(f"附件 {name} 沒有上傳完成（state 是 {asset.get('state')}）")
        if asset.get("size") != local.stat().st_size:
            problems.append(f"附件 {name} 的大小是 {asset.get('size')}，本機是 {local.stat().st_size}")
        digest = asset.get("digest")
        if digest is not None and digest != _sha256_digest(local):
            problems.append(f"附件 {name} 的 SHA-256 和本機不同（GitHub 算的是 {digest}）")
    return problems


def _report(problems: Sequence[str], what: str) -> int:
    if problems:
        print(f"{what}有 {len(problems)} 個問題：", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.release_assets",
                                     description="發版附件與 release notes（release.yml 用）。")
    commands = parser.add_subparsers(dest="command", required=True)
    title_parser = commands.add_parser("title", help="印出 release 的標題（tag 格式不對時失敗）")
    title_parser.add_argument("tag")
    prepare_parser = commands.add_parser("prepare", help="放進發布包、抓 FFmpeg 原始碼，寫 SHA256SUMS")
    prepare_parser.add_argument("version", help="build_release.ps1 的 -Version，發版時是 tag")
    prepare_parser.add_argument("outdir", type=Path)
    check_parser = commands.add_parser("check", help="附件剛好是該有的那幾個，SHA256SUMS 對得上")
    check_parser.add_argument("version")
    check_parser.add_argument("dir", type=Path)
    notes_parser = commands.add_parser("notes", help="寫 release notes")
    notes_parser.add_argument("tag")
    notes_parser.add_argument("repo", help="owner/repo")
    notes_parser.add_argument("out", type=Path)
    verify_parser = commands.add_parser("verify-release", help="GitHub 上的 release 和本機的附件相符")
    verify_parser.add_argument("tag")
    verify_parser.add_argument("dir", type=Path)
    verify_parser.add_argument("release_json", type=Path, help="GET /repos/{owner}/{repo}/releases/{id} 的回應")
    state = verify_parser.add_mutually_exclusive_group(required=True)
    state.add_argument("--draft", dest="draft", action="store_true", help="上傳後、公開前")
    state.add_argument("--published", dest="draft", action="store_false", help="公開後")
    args = parser.parse_args(argv)

    try:
        if args.command == "title":
            print(title(args.tag))
            return 0
        if args.command == "prepare":
            paths = prepare(args.version, args.outdir)
            print(f"附件（{args.outdir}）：")
            for path in paths:
                print(f"  {path.stat().st_size:>12}  {path.name}")
            print((args.outdir / SUMS).read_text(encoding="ascii"), end="")
            return 0
        if args.command == "check":
            expected = expected_assets(args.version, _pins())
            code = _report(check(args.dir, expected), f"{args.dir} 的附件")
            if code == 0:
                print(f"{args.dir}：{len(expected)} 個附件都在，{SUMS} 的雜湊都對：{'、'.join(expected)}")
            return code
        if args.command == "notes":
            notes = release_notes(args.tag, args.repo, README.read_text(encoding="utf-8"), _pins())
            args.out.write_text(notes, encoding="utf-8", newline="\n")
            print(notes)
            return 0
        release = json.loads(args.release_json.read_text(encoding="utf-8"))
        if not isinstance(release, dict):
            raise ValueError(f"{args.release_json} 不是單一 release 的 JSON 物件")
        expected = expected_assets(check_tag(args.tag), _pins())
        problems = verify_release(release, args.tag, args.dir, expected, draft=args.draft)
        code = _report(problems, f"{args.tag} 的 release ")
        if code == 0:
            print(f"{args.tag} 的 release：{'草稿' if args.draft else '已公開'}、prerelease、標題「{title(args.tag)}」，"
                  f"{len(expected)} 個附件都上傳完成，大小與 SHA-256 和本機相同")
        return code
    except ValueError as e:
        print(f"失敗：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # 輸出到管線時用的是系統碼頁；印不出的字元改用跳脫，不讓腳本自己因為編碼而失敗
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    sys.exit(main())
