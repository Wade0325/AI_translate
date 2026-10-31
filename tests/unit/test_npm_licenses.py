"""前端打包的 npm 套件清單（#274）：tools/npm_licenses.py 從 frontend/package-lock.json 產生。

新增、移除或升級前端依賴而沒有重新產生清單時，這裡紅燈；重新產生要先 npm ci（授權全文從
node_modules 讀），CI 的 python job 沒有 node_modules，所以這裡只比對清單，不讀 node_modules。
"""
import copy
import json
import re
from pathlib import Path

import pytest

from tools import npm_licenses

ROOT = Path(__file__).resolve().parents[2]
REGENERATE = "清單過期：npm ci --prefix frontend 之後執行 python tools/npm_licenses.py 重新產生"


def _lock() -> dict:
    return json.loads(npm_licenses.LOCKFILE.read_text(encoding="utf-8"))


def _committed() -> str:
    return npm_licenses.OUTPUT.read_text(encoding="utf-8")


class TestCommittedListing:
    def test_matches_package_lock(self):
        assert npm_licenses.stale_listing(_lock(), _committed()) == [], REGENERATE

    def test_every_listed_package_has_its_license_text(self):
        text = _committed()
        sections = re.split(rf"^{npm_licenses.RULE}$", text, flags=re.M)[1:]
        headers = [section.strip("\n").splitlines()[0] for section in sections]

        assert headers == [f"{p.name} {p.version}" for p in npm_licenses.packages(_lock())]
        for section in sections:
            body = section.split(npm_licenses.THIN_RULE, 1)[1]
            assert len(body.strip()) > 100, section[:200]

    def test_lists_what_the_interface_imports(self):
        listed = {line.split()[0] for line in npm_licenses.committed_listing(_committed())}
        dependencies = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        assert set(dependencies["dependencies"]) <= listed


class TestStaleListing:
    """新增前端依賴而沒更新清單時變紅（#274 的驗收）。"""

    def test_new_dependency_without_regenerating_is_reported(self):
        lock = copy.deepcopy(_lock())
        lock["packages"]["node_modules/left-pad"] = {"version": "1.3.0", "license": "WTFPL"}

        assert npm_licenses.stale_listing(lock, _committed()) == ["清單少了：left-pad 1.3.0 WTFPL"]

    def test_upgraded_dependency_is_reported(self):
        lock = copy.deepcopy(_lock())
        lock["packages"]["node_modules/react"]["version"] = "99.0.0"

        problems = npm_licenses.stale_listing(lock, _committed())

        assert "清單少了：react 99.0.0 MIT" in problems
        assert any(p.startswith("清單多了：react 19.") for p in problems)

    def test_removed_dependency_is_reported(self):
        lock = copy.deepcopy(_lock())
        del lock["packages"]["node_modules/jszip"]

        assert npm_licenses.stale_listing(lock, _committed()) == [
            "清單多了：jszip 3.10.1 (MIT OR GPL-3.0-or-later)"]

    def test_new_dev_dependency_is_not_listed(self):
        # 開發用的套件不會打包進 dist（建置工具注入的程式碼另外列）
        lock = copy.deepcopy(_lock())
        lock["packages"]["node_modules/some-linter"] = {
            "version": "1.0.0", "license": "MIT", "dev": True}

        assert npm_licenses.stale_listing(lock, _committed()) == []


class TestPackages:
    def _lock(self, **entries) -> dict:
        base = {"node_modules/vite": {"version": "6.0.0", "license": "MIT", "dev": True}}
        return {"lockfileVersion": 3, "packages": {"": {"name": "app"}, **base, **entries}}

    def test_runtime_packages_and_injected_build_code(self):
        lock = self._lock(**{
            "node_modules/react": {"version": "19.0.0", "license": "MIT"},
            "node_modules/eslint": {"version": "9.0.0", "license": "MIT", "dev": True},
            "node_modules/a/node_modules/react": {"version": "18.0.0", "license": "MIT"},
            "node_modules/b/node_modules/react": {"version": "18.0.0", "license": "MIT"},
        })

        listed = npm_licenses.listing(npm_licenses.packages(lock))

        # 不同版本各列一次，同一個版本只列一次；巢狀安裝的用路徑最後一段當名稱
        assert listed == [
            "react 18.0.0 MIT",
            "react 19.0.0 MIT",
            f"vite 6.0.0 MIT（{npm_licenses.INJECTED['vite'].reason}）",
        ]

    def test_aliased_package_uses_its_real_name(self):
        lock = self._lock(**{
            "node_modules/my-react": {"name": "react", "version": "19.0.0", "license": "MIT"}})

        assert "react 19.0.0 MIT" in npm_licenses.listing(npm_licenses.packages(lock))

    def test_package_without_license_is_an_error(self):
        lock = self._lock(**{"node_modules/mystery": {"version": "1.0.0"}})

        with pytest.raises(ValueError, match="mystery"):
            npm_licenses.packages(lock)

    def test_injected_package_missing_from_lockfile_is_an_error(self):
        lock = {"packages": {"": {}, "node_modules/react": {"version": "1.0.0", "license": "MIT"}}}

        with pytest.raises(ValueError, match="vite"):
            npm_licenses.packages(lock)


class TestLicenseText:
    """授權全文的來源：從 tmp_path 做的假 node_modules 讀。"""

    def _package(self, root: Path, name: str, files: dict[str, str], **package_json) -> npm_licenses.Package:
        directory = root / "node_modules" / name
        directory.mkdir(parents=True)
        (directory / "package.json").write_text(json.dumps({"name": name, **package_json}),
                                                encoding="utf-8")
        for rel, text in files.items():
            (directory / rel).parent.mkdir(parents=True, exist_ok=True)
            (directory / rel).write_text(text, encoding="utf-8")
        return npm_licenses.Package(name, "1.0.0", "MIT", f"node_modules/{name}")

    def test_license_file_at_package_root(self, tmp_path):
        pkg = self._package(tmp_path, "a", {"LICENSE": "MIT License\r\n\r\nCopyright (c) A\r\n"})

        assert npm_licenses.license_text(tmp_path, pkg) == ("LICENSE", "MIT License\n\nCopyright (c) A")

    def test_readme_license_section_with_copyright(self, tmp_path):
        readme = "# a\n\n## License\n\n(MIT)\n\nCopyright (c) A\n\n## Other\n\nnot this\n"
        pkg = self._package(tmp_path, "a", {"README.md": readme})

        where, text = npm_licenses.license_text(tmp_path, pkg)

        assert where == "README.md 的「License」一節"
        assert text == "(MIT)\n\nCopyright (c) A"

    def test_readme_that_only_names_the_license_is_not_enough(self, tmp_path):
        pkg = self._package(tmp_path, "a", {"README.md": "## License\n\nMIT\n"})

        with pytest.raises(ValueError, match="找不到 a 1.0.0 的授權全文"):
            npm_licenses.license_text(tmp_path, pkg)

    def test_license_from_package_in_the_same_repo(self, tmp_path, monkeypatch):
        repo = {"type": "git", "url": "git+https://github.com/org/mono.git"}
        self._package(tmp_path, "donor", {"LICENSE": "Copyright (c) Org"},
                      repository="https://github.com/org/mono/tree/master/packages/donor")
        pkg = self._package(tmp_path, "taker", {}, repository=repo)
        monkeypatch.setattr(npm_licenses, "LICENSE_FROM", {"taker": "donor"})

        where, text = npm_licenses.license_text(tmp_path, pkg)

        assert "org/mono" in where and "donor" in where
        assert text == "Copyright (c) Org"

    def test_license_from_another_repo_is_refused(self, tmp_path, monkeypatch):
        self._package(tmp_path, "donor", {"LICENSE": "x"}, repository="https://github.com/org/other")
        pkg = self._package(tmp_path, "taker", {}, repository="https://github.com/org/mono")
        monkeypatch.setattr(npm_licenses, "LICENSE_FROM", {"taker": "donor"})

        with pytest.raises(ValueError, match="不是同一個 repo"):
            npm_licenses.license_text(tmp_path, pkg)

    def test_vendored_license_files(self, tmp_path):
        pkg = self._package(tmp_path, "a", {"lib-vendor/d3/LICENSE": "Copyright Mike",
                                            "node_modules/x/LICENSE": "not vendored"})

        where, text = npm_licenses.license_text(tmp_path, pkg)

        assert "根目錄沒有授權檔" in where
        assert text == "Copyright Mike"

    def test_injected_package_keeps_only_the_named_sections(self, tmp_path):
        license_md = ("# Vite core license\nMIT, Copyright Vite\n\n# Licenses of bundled dependencies\n\n"
                      "## @rollup/plugin-alias, @rollup/plugin-commonjs\nMIT, Copyright Rollup\n\n"
                      "---------------------------------------\n\n## anymatch\nISC\n")
        self._package(tmp_path, "vite", {"LICENSE.md": license_md})
        pkg = npm_licenses.Package("vite", "6.0.0", "MIT", "node_modules/vite",
                                   npm_licenses.INJECTED["vite"])

        _, text = npm_licenses.license_text(tmp_path, pkg)

        assert text == ("# Vite core license\nMIT, Copyright Vite\n\n"
                        "## @rollup/plugin-alias, @rollup/plugin-commonjs\nMIT, Copyright Rollup")

    def test_missing_node_modules_says_how_to_install(self, tmp_path):
        pkg = npm_licenses.Package("a", "1.0.0", "MIT", "node_modules/a")

        with pytest.raises(ValueError, match="npm ci"):
            npm_licenses.license_text(tmp_path, pkg)


def _bare_imports(source: str) -> set[str]:
    """import 的套件名稱（不含相對路徑與 @/ 別名）：@scope/name 或 name。"""
    specifiers = re.findall(
        r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\(\s*)['"]([^'"]+)['"]""", source)
    names = set()
    for spec in specifiers:
        if spec.startswith((".", "/", "@/")):
            continue
        parts = spec.split("/")
        names.add("/".join(parts[:2]) if spec.startswith("@") else parts[0])
    return names


def test_interface_imports_only_runtime_dependencies():
    """介面的程式只 import dependencies 裡的套件：開發用的套件不在清單裡，被打包進 dist 就漏列了。"""
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    runtime = set(package["dependencies"])
    src = ROOT / "frontend" / "src"
    tests = re.compile(r"\.(test|spec)\.[jt]sx?$")
    offending = {}
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"} or tests.search(path.name):
            continue
        if rel.parts[0] == "test":  # vitest 的 setup（frontend/src/test/）
            continue
        extra = _bare_imports(path.read_text(encoding="utf-8")) - runtime
        if extra:
            offending[rel.as_posix()] = sorted(extra)

    assert offending == {}, "把這些套件移到 package.json 的 dependencies，再重新產生清單"


def test_bare_imports_parser():
    source = """
        import React from 'react'
        import { a } from "@ant-design/icons/lib/x"
        import './style.css'
        import x from '@/utils/x'
        const y = await import('jszip')
        export { b } from 'react-router-dom'
    """
    assert _bare_imports(source) == {"react", "@ant-design/icons", "jszip", "react-router-dom"}
