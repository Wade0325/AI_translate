"""tools/cargo_crates.py：Cargo.lock 的 Rust 套件與它們的授權檔（#274）。"""
import hashlib
import io
import tarfile

import pytest

from tools import cargo_crates
from tools.cargo_crates import Crate

SUM = "a" * 64
LOCK = f"""
version = 4

[[package]]
name = "uv"
version = "0.1.0"

[[package]]
name = "serde"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "{SUM}"

[[package]]
name = "anyhow"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "{"b" * 64}"
"""


class TestCrates:
    def test_lists_crates_io_packages_sorted_without_workspace_members(self):
        assert cargo_crates.crates(LOCK) == [Crate("anyhow", "1.0.0", "b" * 64), Crate("serde", "1.0.0", SUM)]

    def test_download_url(self):
        assert Crate("serde", "1.0.0", SUM).url == "https://static.crates.io/crates/serde/serde-1.0.0.crate"

    def test_other_sources_stop_the_generation(self):
        lock = LOCK + '\n[[package]]\nname = "pubgrub"\nversion = "0.3.0"\nsource = "git+https://github.com/x/pubgrub?rev=1#1"\n'

        with pytest.raises(ValueError, match="pubgrub 0.3.0 的來源 git"):
            cargo_crates.crates(lock)

    def test_missing_checksum_is_an_error(self):
        lock = LOCK.replace(f'checksum = "{SUM}"\n', "")

        with pytest.raises(ValueError, match="serde 1.0.0 沒有 checksum"):
            cargo_crates.crates(lock)


@pytest.mark.parametrize(("expression", "expected"), [
    ("MIT", (["MIT"], [])),
    ("MIT OR Apache-2.0", (["MIT", "Apache-2.0"], [])),
    ("MIT/Apache-2.0", (["MIT", "Apache-2.0"], [])),
    ("(MIT OR Apache-2.0) AND Unicode-3.0", (["MIT", "Apache-2.0", "Unicode-3.0"], [])),
    ("Apache-2.0 WITH LLVM-exception OR MIT", (["Apache-2.0", "MIT"], ["LLVM-exception"])),
])
def test_spdx_ids(expression, expected):
    assert cargo_crates.spdx_ids(expression) == expected


def _crate_file(name: str, version: str, files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for rel, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{name}-{version}/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _component(files: dict[str, str], spdx=lambda i: f"<{i} 標準全文>"):
    data = _crate_file("zstd-sys", "2.0.0", files)
    crate = Crate("zstd-sys", "2.0.0", hashlib.sha256(data).hexdigest())
    return cargo_crates.component(crate, data, spdx)


class TestComponent:
    def test_collects_nested_license_files(self):
        # -sys 套件內含的 C 函式庫有自己的授權檔
        component = _component({
            "Cargo.toml": '[package]\nname = "zstd-sys"\nlicense = "MIT/Apache-2.0"\n',
            "LICENSE-MIT": "MIT\r\nCopyright (c) A\r\n",
            "zstd/LICENSE": "BSD Copyright Meta",
            "src/lib.rs": "// not a license",
        })

        assert component.license == "MIT/Apache-2.0"
        assert [(f.path, f.text) for f in component.files] == [
            ("LICENSE-MIT", "MIT\nCopyright (c) A"), ("zstd/LICENSE", "BSD Copyright Meta")]
        assert component.notes == []

    def test_license_file_field_is_included(self):
        component = _component({
            "Cargo.toml": '[package]\nlicense-file = "LEGAL.txt"\n',
            "LEGAL.txt": "Custom license",
        })

        assert [f.path for f in component.files] == ["LEGAL.txt"]

    def test_without_license_files_uses_spdx_texts_and_names_the_authors(self):
        component = _component({
            "Cargo.toml": '[package]\nlicense = "Apache-2.0 WITH LLVM-exception"\nauthors = ["A <a@x>", "B"]\n'})

        assert [(f.path, f.text) for f in component.files] == [
            ("SPDX：Apache-2.0", "<Apache-2.0 標準全文>"), ("SPDX：LLVM-exception", "<LLVM-exception 標準全文>")]
        assert component.notes == ["套件沒有附授權檔：依 Cargo.toml 的 license 附上 SPDX 的標準全文；著作權人：A <a@x>、B"]

    def test_no_license_at_all_is_an_error(self):
        with pytest.raises(ValueError, match="zstd-sys 2.0.0 沒有授權檔"):
            _component({"Cargo.toml": "[package]\n"})

    def test_checksum_mismatch_is_an_error(self):
        data = _crate_file("zstd-sys", "2.0.0", {"LICENSE": "x"})

        with pytest.raises(ValueError, match="checksum 不符"):
            cargo_crates.component(Crate("zstd-sys", "2.0.0", SUM), data, str)
