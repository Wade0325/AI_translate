"""Cargo.lock 列的 Rust 套件（crate）與它們的授權檔（#274）。

uv.exe 與 ffmpeg.exe 裡的 rav1e、librsvg 是 Rust 寫的，靜態連入 Cargo.lock 列的套件。這裡：

- crates()：讀 Cargo.lock，列出 crates.io 的套件與它的 checksum（.crate 檔的 SHA-256）。workspace
  自己的套件（沒有 source）不列；其他來源（git、別的 registry）直接停下來，要人看過再支援。
- component()：從 .crate 檔取出授權檔，連同子資料夾裡的（-sys 套件內含的 C 函式庫有自己的授權檔）。
  套件沒附任何授權檔時，依 Cargo.toml 的 license 欄位附上 SPDX 的標準全文，並寫明著作權人（authors）。

Cargo.lock 也列了只在其他平台、測試或建置時才用到的套件，所以清單只會比實際連入的多、不會少。
"""

from __future__ import annotations

import hashlib
import io
import re
import tarfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from tools.license_texts import Component, LicenseFile, decode, is_license_file, skipped

CRATES_IO = "registry+https://github.com/rust-lang/crates.io-index"
DOWNLOAD = "https://static.crates.io/crates/{name}/{name}-{version}.crate"
_SPDX_TOKEN = re.compile(r"[A-Za-z0-9.+-]+")
_OPERATORS = {"AND", "OR", "WITH"}


@dataclass(frozen=True)
class Crate:
    name: str
    version: str
    checksum: str

    @property
    def url(self) -> str:
        return DOWNLOAD.format(name=self.name, version=self.version)


def crates(lock_text: str) -> list[Crate]:
    """Cargo.lock 裡 crates.io 的套件，照名稱與版本排序。"""
    found: dict[tuple[str, str], Crate] = {}
    for pkg in tomllib.loads(lock_text).get("package", []):
        source = pkg.get("source")
        if source is None:
            continue
        name, version = pkg["name"], pkg["version"]
        if source != CRATES_IO:
            raise ValueError(f"{name} {version} 的來源 {source} 不是 crates.io，cargo_crates.py 還不支援")
        checksum = pkg.get("checksum", "")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError(f"Cargo.lock 裡 {name} {version} 沒有 checksum")
        found[(name, version)] = Crate(name, version, checksum)
    return [found[key] for key in sorted(found)]


def spdx_ids(expression: str) -> tuple[list[str], list[str]]:
    """SPDX 運算式裡的授權與例外條款：("MIT OR Apache-2.0 WITH LLVM-exception") → (["MIT", "Apache-2.0"], ["LLVM-exception"])。"""
    licenses: list[str] = []
    exceptions: list[str] = []
    tokens = _SPDX_TOKEN.findall(expression.replace("/", " OR "))
    for previous, token in zip(["", *tokens], tokens, strict=False):
        if token in _OPERATORS:
            continue
        target = exceptions if previous == "WITH" else licenses
        if token not in target:
            target.append(token)
    return licenses, exceptions


def component(crate: Crate, data: bytes, spdx_text: Callable[[str], str]) -> Component:
    """.crate 檔（已驗過 checksum）的授權檔。spdx_text(識別碼) 回傳 SPDX 的標準全文。"""
    if hashlib.sha256(data).hexdigest() != crate.checksum:
        raise ValueError(f"{crate.name}-{crate.version}.crate 的 SHA-256 和 Cargo.lock 的 checksum 不符")
    top = f"{crate.name}-{crate.version}"
    files: list[LicenseFile] = []
    manifest: dict = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = {m.name: m for m in tar.getmembers() if m.isfile()}
        cargo_toml = members.get(f"{top}/Cargo.toml")
        if cargo_toml is not None:
            manifest = tomllib.loads(_read(tar, cargo_toml).decode("utf-8")).get("package", {})
        named = manifest.get("license-file")
        for name in sorted(members):
            rel = PurePosixPath(name).relative_to(top).as_posix() if name.startswith(f"{top}/") else None
            if rel is None or skipped(rel) or not (is_license_file(rel) or rel == named):
                continue
            text = decode(_read(tar, members[name]))
            if text:
                files.append(LicenseFile(rel, text))
    expression = manifest.get("license", "")
    if expression == "" and not files:
        raise ValueError(f"{crate.name} {crate.version} 沒有授權檔，Cargo.toml 也沒有 license 欄位")
    notes = []
    if not files:
        licenses, exceptions = spdx_ids(expression)
        files = [LicenseFile(f"SPDX：{spdx}", spdx_text(spdx)) for spdx in [*licenses, *exceptions]]
        authors = "、".join(manifest.get("authors", [])) or "（Cargo.toml 沒有寫）"
        notes = [f"套件沒有附授權檔：依 Cargo.toml 的 license 附上 SPDX 的標準全文；著作權人：{authors}"]
    return Component(crate.name, crate.version, files, license=expression, notes=notes)


def _read(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    f = tar.extractfile(member)
    if f is None:
        raise ValueError(f"讀不到 {member.name}")
    return f.read()
