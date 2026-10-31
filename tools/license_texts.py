"""第三方授權清單共用的部分（#274）：認授權檔、統一換行、把相同的授權全文只收一次。

tools/third_party_licenses.py 用它產生 ffmpeg 靜態連入的函式庫與 Rust 套件的清單。清單分兩段：

    套件清單：每個元件的名稱、版本、來源，以及它的每個授權檔對到第幾份全文
    授權全文：每份不同的全文只出現一次，以 [編號] 標示

同一份全文（例如沒改過的 Apache-2.0）常被幾百個 Rust 套件共用，只收一次可以讓檔案小很多；
內容有任何不同（例如 MIT 的著作權人）就是不同的一份。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

RULE = "=" * 80
THIN_RULE = "-" * 80
LISTING_START = "元件清單（名稱、版本、來源、授權檔與全文的編號）"
TEXTS_START = "授權全文"

# 檔名（不分大小寫）：LICENSE、COPYING、NOTICE 等，可以接 -MIT、.txt、.LGPLv3 之類的後綴
_LICENSE_NAME = re.compile(
    r"^(licen[cs]e|copying|copyright|notice|unlicense|patents)([-._ ].*)?$", re.IGNORECASE)
# 名字像授權檔，但其實是程式碼或建置檔
_NOT_TEXT = {
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".inc", ".rs", ".py", ".pyc", ".js", ".mjs",
    ".ts", ".go", ".java", ".kt", ".swift", ".m", ".mm", ".cs", ".sh", ".bat", ".ps1", ".pl", ".pm",
    ".rb", ".php", ".lua", ".m4", ".in", ".am", ".ac", ".cmake", ".mk", ".json", ".yml", ".yaml",
    ".toml", ".xml", ".html", ".htm", ".css", ".svg", ".png", ".jpg", ".gif", ".ico", ".pdf", ".gz",
    ".xz", ".zip", ".tar", ".bz2", ".o", ".a", ".so", ".dll", ".exe", ".tmpl", ".template", ".spdx",
}


# 不會編進程式的資料夾（路徑裡任何一層叫這個名字就略過）：測試、範例、效能測試
SKIP_DIRS = {
    "test", "tests", "testing", "testdata", "test-data", "test_data", "unittest", "unittests",
    "fuzz", "fuzzing", "fuzzer", "example", "examples", "sample", "samples", "bench", "benches",
    "benchmark", "benchmarks", "perf", "googletest", "gtest", "gmock",
}


def is_license_file(path: str) -> bool:
    """path（以 / 分隔）是不是授權文件：檔名像 LICENSE、COPYING，或放在最上層的 LICENSES 資料夾裡。"""
    p = PurePosixPath(path)
    if p.suffix.lower() in _NOT_TEXT:
        return False
    if _LICENSE_NAME.match(p.name):
        return True
    # REUSE 的慣例：最上層的 LICENSES/<SPDX 識別碼>.txt（更深的 licenses 資料夾常是程式要用的資料）
    return len(p.parts) == 2 and p.parts[0].lower() == "licenses"


def skipped(path: str, removed: Iterable[str] = ()) -> bool:
    """path 在不會編進程式的資料夾（SKIP_DIRS），或在下載後被刪掉的資料夾（removed）裡。"""
    parts = PurePosixPath(path).parts[:-1]
    return any(p.lower() in SKIP_DIRS for p in parts) or any(
        path == r or path.startswith(f"{r}/") for r in removed)


def decode(data: bytes) -> str | None:
    """授權檔的內容轉成文字：換行一律 LF、去掉行尾空白與前後的空行；看起來不是文字檔時回傳 None。"""
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


@dataclass(frozen=True)
class LicenseFile:
    path: str  # 在元件原始碼裡的路徑，以 / 分隔
    text: str


@dataclass
class Component:
    name: str
    version: str
    files: list[LicenseFile]
    source: str = ""  # 原始碼的位置（網址）
    license: str = ""  # 元件宣告的授權（SPDX 運算式）；沒有宣告時留空
    notes: list[str] = field(default_factory=list)


class TextPool:
    """授權全文的編號：同一份全文只編一次，編號照第一次出現的順序。"""

    def __init__(self) -> None:
        self.numbers: dict[str, int] = {}
        self.first_seen: dict[int, str] = {}
        self.uses: dict[int, int] = {}

    def add(self, text: str, where: str) -> int:
        number = self.numbers.get(text)
        if number is None:
            number = self.numbers[text] = len(self.numbers) + 1
            self.first_seen[number] = where
            self.uses[number] = 0
        self.uses[number] += 1
        return number

    def texts(self) -> list[tuple[int, str]]:
        return sorted(((n, t) for t, n in self.numbers.items()))


def render(title: Sequence[str], components: Iterable[Component], unit: str = "個元件") -> str:
    """元件清單與授權全文。components 照傳入的順序列出；全文照第一次出現的順序編號。"""
    pool = TextPool()
    listing: list[str] = []
    count = 0
    for c in components:
        count += 1
        head = f"{c.name} {c.version}" + (f" {c.license}" if c.license else "")
        refs = "、".join(f"{f.path} [{pool.add(f.text, f'{c.name} {c.version} 的 {f.path}')}]"
                        for f in c.files)
        listing += [head]
        if c.source:
            listing += [f"    來源：{c.source}"]
        listing += [f"    {note}" for note in c.notes]
        listing += [f"    授權檔：{refs}", ""]
    out = [*title, "", LISTING_START, "", *listing,
           f"共 {count} {unit}，{len(pool.numbers)} 份不同的授權全文。", "", TEXTS_START]
    for number, text in pool.texts():
        uses = pool.uses[number]
        also = f"（另有 {uses - 1} 處相同）" if uses > 1 else ""
        out += ["", RULE, f"[{number}] {pool.first_seen[number]}{also}", THIN_RULE, "", text]
    return "\n".join(out) + "\n"


def header_value(text: str, key: str) -> str | None:
    """產生的清單開頭「key：value」那一行的 value（測試拿來和 build_release.ps1 的釘版比對）。"""
    for line in text.split("\n"):
        if line == LISTING_START:
            break
        if line.startswith(f"{key}："):
            return line.split("：", 1)[1]
    return None
