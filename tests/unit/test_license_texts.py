"""tools/license_texts.py：認授權檔、統一換行、相同的授權全文只收一次（#274）。"""
import pytest

from tools import license_texts
from tools.license_texts import Component, LicenseFile


@pytest.mark.parametrize("path", [
    "LICENSE", "COPYING", "COPYING.LGPLv3", "LICENSE-MIT", "LICENSE.md", "license.txt", "LICENCE",
    "NOTICE", "PATENTS", "UNLICENSE", "third_party/libyuv/LICENSE", "LICENSES/LGPL-2.1-or-later.txt",
    "COPYING.MinGW-w64/COPYING.MinGW-w64.txt",
])
def test_license_files(path):
    assert license_texts.is_license_file(path)


@pytest.mark.parametrize("path", [
    "README.md", "src/license.c", "include/copyright.h", "tools/license.py", "LICENSE.json",
    "licenses.md", "docs/licensing.rst",
    # 只認最上層的 LICENSES；更深的是程式要用的資料（例如 spdx 套件內含的各種授權全文）
    "src/text/licenses/APL-1.0",
])
def test_not_license_files(path):
    assert not license_texts.is_license_file(path)


def test_decode_normalizes_line_endings_and_trailing_spaces():
    assert license_texts.decode(b"\xef\xbb\xbf\r\nMIT  \r\n\r\nCopyright\r") == "MIT\n\nCopyright"


def test_decode_falls_back_to_latin1_and_rejects_binary():
    assert license_texts.decode("Copyright © A".encode("latin-1")) == "Copyright © A"
    assert license_texts.decode(b"\x00\x01binary") is None


def test_render_numbers_identical_texts_once():
    apache = "Apache License 2.0 full text"
    components = [
        Component("a", "1.0", [LicenseFile("LICENSE-APACHE", apache), LicenseFile("LICENSE-MIT", "MIT A")],
                  license="MIT OR Apache-2.0"),
        Component("b", "2.0", [LicenseFile("LICENSE", apache)], source="https://example.com/b",
                  notes=["備註"]),
    ]

    text = license_texts.render(["標題", "版本：1"], components)

    assert text.split(f"\n{license_texts.TEXTS_START}\n")[0] == (
        "標題\n版本：1\n\n" + license_texts.LISTING_START + "\n\n"
        "a 1.0 MIT OR Apache-2.0\n"
        "    授權檔：LICENSE-APACHE [1]、LICENSE-MIT [2]\n\n"
        "b 2.0\n"
        "    來源：https://example.com/b\n"
        "    備註\n"
        "    授權檔：LICENSE [1]\n\n"
        "共 2 個元件，2 份不同的授權全文。\n")
    assert text.count(apache) == 1
    assert "[1] a 1.0 的 LICENSE-APACHE（另有 1 處相同）" in text
    assert text.endswith("MIT A\n")


def test_header_value_only_reads_the_header():
    text = license_texts.render(["標題", "uv：0.1.0"], [Component("uv：9", "1", [LicenseFile("L", "x")])])

    assert license_texts.header_value(text, "uv") == "0.1.0"
    assert license_texts.header_value(text, "沒有") is None


@pytest.mark.parametrize(("path", "expected"), [
    ("LICENSE", False),
    ("third_party/libyuv/LICENSE", False),
    ("tests/data/LICENSE", True),
    ("src/Examples/LICENSE", True),
    ("third_party/googletest/LICENSE", True),
    ("Thirdparty/x/LICENSE", "removed"),
])
def test_skipped(path, expected):
    if expected == "removed":
        assert not license_texts.skipped(path)
        assert license_texts.skipped(path, removed=["Thirdparty"])
    else:
        assert license_texts.skipped(path) is expected
