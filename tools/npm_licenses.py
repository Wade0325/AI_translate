"""免安裝版附的前端第三方授權（#274）：frontend\\dist 打包的 npm 套件，連同授權全文。

用法（在哪個目錄執行都可以，一律以 repo 根目錄為基準）：

    npm ci --prefix frontend          # 授權全文從 frontend/node_modules 讀
    python tools/npm_licenses.py      # 重新產生 tools/portable/licenses/frontend/npm-packages.txt

清單從 frontend/package-lock.json 產生：
- 不是開發用的套件（lockfile 沒標 ``"dev": true``），也就是 dependencies 與它們的依賴。建置時沒用到的
  部分會被剔除，所以清單只會比 frontend/dist 裡的多、不會少（前提是介面的程式只 import dependencies 裡的
  套件，tests/unit/test_npm_licenses.py 檢查）。
- 建置工具注入 dist 的程式碼（INJECTED）：vite 是開發用的套件，但 production build 會把它的
  modulepreload polyfill 與 @rollup/plugin-commonjs 的輔助函式放進 dist。

tests/unit/test_npm_licenses.py 拿 package-lock.json 比對已 commit 的清單（stale_listing()，不需要
node_modules）：新增、移除或升級前端依賴而沒有重新產生時紅燈。

授權全文依序找：套件根目錄的 LICENSE、COPYING 等檔案；LICENSE_FROM 指定的同一個 repo 的套件；README 裡
帶著著作權聲明的 License 一節；套件附的其他授權檔（例如內含的第三方程式碼）。都找不到就停下來，
要人決定，不寫一份空的。

只用標準函式庫。
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LOCKFILE = FRONTEND / "package-lock.json"
OUTPUT = ROOT / "tools" / "portable" / "licenses" / "frontend" / "npm-packages.txt"


@dataclass(frozen=True)
class Injected:
    """開發用的套件，但 production build 會把它的一部分程式碼放進 dist。"""

    reason: str
    # 授權檔裡要收的段落：以這些字串開頭的標題（# 或 ##）底下的內容
    sections: tuple[str, ...]
    license_file: str


INJECTED = {
    "vite": Injected(
        reason="建置工具注入 dist 的程式碼：modulepreload polyfill 與 CommonJS 轉換的輔助函式",
        sections=("# Vite core license", "## @rollup/plugin-alias, @rollup/plugin-commonjs"),
        license_file="LICENSE.md",
    ),
}

# 套件沒有附授權檔，但和同一個 repo 的另一個套件共用授權時，從那個套件取（產生時檢查兩者的 repo 相同）
LICENSE_FROM = {
    # ant-design/ant-design-icons 這個 monorepo 的兩個套件；icons-svg 的 npm 套件沒有附 LICENSE
    "@ant-design/icons-svg": "@ant-design/icons",
}

LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|unlicense)([.\-_].*)?$", re.I)
README_FILE = re.compile(r"^readme(\.(md|markdown|txt))?$", re.I)
LICENSE_HEADING = re.compile(r"^(#{1,6})\s*licen[cs]es?\b", re.I)

LISTING_START = "套件清單（名稱、版本、授權）"
TEXTS_START = "授權全文"
RULE = "=" * 80
THIN_RULE = "-" * 80


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    license: str
    # package-lock.json 裡的路徑（node_modules/...），相對於 frontend/
    path: str
    injected: Injected | None = None

    def listing_line(self) -> str:
        line = f"{self.name} {self.version} {self.license}"
        return f"{line}（{self.injected.reason}）" if self.injected else line


def _name(path: str, entry: dict) -> str:
    # 別名安裝的套件，lockfile 的 name 是真正的套件名稱；其他的從路徑最後一段 node_modules/ 之後取
    return entry.get("name") or path.rsplit("node_modules/", 1)[-1]


def packages(lock: dict) -> list[Package]:
    """要列進清單的套件，依名稱與版本排序；同一個名稱與版本只列一次。"""
    entries = lock.get("packages")
    if not isinstance(entries, dict):
        raise ValueError("package-lock.json 沒有 packages（要 lockfileVersion 2 以上）")
    found: dict[tuple[str, str], Package] = {}
    for path, entry in entries.items():
        if not path or entry.get("link"):
            continue  # "" 是專案本身
        name = _name(path, entry)
        injected = INJECTED.get(name) if path == f"node_modules/{name}" else None
        if entry.get("dev") and not injected:
            continue
        version = entry.get("version")
        license_id = entry.get("license")
        if not version or not license_id:
            raise ValueError(f"package-lock.json 的 {path} 沒有 version 或 license")
        found.setdefault((name, version), Package(name, version, license_id, path, injected))
    missing = sorted(set(INJECTED) - {p.name for p in found.values() if p.injected})
    if missing:
        raise ValueError(f"package-lock.json 裡沒有 INJECTED 的套件：{'、'.join(missing)}")
    return [found[key] for key in sorted(found)]


def listing(pkgs: Sequence[Package]) -> list[str]:
    return [p.listing_line() for p in pkgs]


def committed_listing(text: str) -> list[str]:
    """已產生的檔案裡的套件清單（每個套件一行）。"""
    lines = text.splitlines()
    try:
        start = lines.index(LISTING_START) + 2  # 標題下面是一行 ---
    except ValueError as e:
        raise ValueError(f"{OUTPUT.name} 的格式不對：找不到「{LISTING_START}」") from e
    # 清單一個套件一行，到第一個空行為止
    end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
    return lines[start:end]


def stale_listing(lock: dict, committed: str) -> list[str]:
    """已產生的清單和 package-lock.json 對不上的地方；對得上時是空的。"""
    expected = listing(packages(lock))
    actual = committed_listing(committed)
    problems = [f"清單少了：{line}" for line in expected if line not in actual]
    problems += [f"清單多了：{line}" for line in actual if line not in expected]
    if not problems and expected != actual:
        problems.append("清單的順序和產生的不同")
    return problems


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _repo(pkg_json: dict) -> str | None:
    """package.json 的 repository（或 homepage）指向的 GitHub repo，寫成 owner/name。"""
    repository = pkg_json.get("repository")
    urls = [repository.get("url", "") if isinstance(repository, dict) else repository or "",
            pkg_json.get("homepage") or ""]
    for url in urls:
        match = re.search(r"github\.com[/:]([^/]+)/([^/#?]+?)(?:\.git)?(?:[/#?]|$)", url)
        if match:
            return f"{match.group(1)}/{match.group(2)}".lower()
    return None


def _readme_license_section(package_dir: Path) -> str | None:
    """README 裡 License 一節的內容，只收帶著著作權聲明的（只寫「MIT」一個字的不算授權全文）。"""
    for readme in sorted(p for p in package_dir.iterdir() if p.is_file() and README_FILE.match(p.name)):
        lines = _read_text(readme).splitlines()
        for i, line in enumerate(lines):
            heading = LICENSE_HEADING.match(line)
            if not heading:
                continue
            level = len(heading.group(1))
            body = []
            for following in lines[i + 1:]:
                deeper = re.match(r"^(#{1,6})\s", following)
                if deeper and len(deeper.group(1)) <= level:
                    break
                body.append(following)
            text = "\n".join(body).strip("\n")
            if re.search(r"copyright", text, re.I):
                return f"{readme.name} 的「{line.lstrip('#').strip()}」一節\n\n{text}"
    return None


def _license_files(package_dir: Path, *, nested: bool) -> list[Path]:
    if not nested:
        return sorted(p for p in package_dir.iterdir() if p.is_file() and LICENSE_FILE.match(p.name))
    return sorted(p for p in package_dir.rglob("*")
                  if p.is_file() and LICENSE_FILE.match(p.name) and p.parent != package_dir
                  and "node_modules" not in p.relative_to(package_dir).parts)


def _join(package_dir: Path, files: Sequence[Path]) -> str:
    parts = []
    for path in files:
        rel = path.relative_to(package_dir).as_posix()
        parts.append(f"[{rel}]\n\n{_read_text(path)}" if len(files) > 1 else _read_text(path))
    return "\n\n".join(parts)


def _sections(text: str, starts: Sequence[str]) -> str:
    """text 裡以 starts 開頭的每一個標題，連同它底下到下一個同級或更高的標題（或 --- 分隔線）為止。"""
    lines = text.splitlines()
    picked = []
    for start in starts:
        index = next((i for i, line in enumerate(lines) if line.startswith(start)), None)
        if index is None:
            raise ValueError(f"授權檔裡找不到「{start}」這一節：套件升版後格式變了，更新 INJECTED")
        level = len(start) - len(start.lstrip("#"))
        body = [lines[index]]
        for line in lines[index + 1:]:
            heading = re.match(r"^(#{1,6})\s", line)
            if (heading and len(heading.group(1)) <= level) or re.fullmatch(r"-{3,}", line.strip()):
                break
            body.append(line)
        picked.append("\n".join(body).strip("\n"))
    return "\n\n".join(picked)


def license_text(node_modules_root: Path, pkg: Package) -> tuple[str, str]:
    """一個套件的授權全文：回傳（取自哪裡，全文）。找不到時丟 ValueError。"""
    package_dir = node_modules_root / pkg.path
    if not (package_dir / "package.json").is_file():
        raise ValueError(f"{package_dir} 不存在：先執行 npm ci --prefix frontend")

    if pkg.injected:
        source = package_dir / pkg.injected.license_file
        return (f"{pkg.injected.license_file} 裡的相關段落",
                _sections(_read_text(source), pkg.injected.sections))

    files = _license_files(package_dir, nested=False)
    if files:
        return "、".join(p.name for p in files), _join(package_dir, files)

    donor_name = LICENSE_FROM.get(pkg.name)
    if donor_name:
        donor_dir = node_modules_root / "node_modules" / donor_name
        own = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        donor = json.loads((donor_dir / "package.json").read_text(encoding="utf-8"))
        if _repo(own) is None or _repo(own) != _repo(donor):
            raise ValueError(f"LICENSE_FROM：{pkg.name}（{_repo(own)}）和 {donor_name}"
                             f"（{_repo(donor)}）不是同一個 repo")
        donor_files = _license_files(donor_dir, nested=False)
        if not donor_files:
            raise ValueError(f"LICENSE_FROM：{donor_name} 也沒有授權檔")
        return (f"套件沒有附授權檔，取自同一個 repo（{_repo(own)}）的 {donor_name}："
                f"{'、'.join(p.name for p in donor_files)}", _join(donor_dir, donor_files))

    readme = _readme_license_section(package_dir)
    if readme:
        where, text = readme.split("\n\n", 1)
        return where, text

    nested = _license_files(package_dir, nested=True)
    if nested:
        return (f"套件根目錄沒有授權檔（package.json 寫 {pkg.license}），以下是它附的授權檔",
                _join(package_dir, nested))

    raise ValueError(f"找不到 {pkg.name} {pkg.version} 的授權全文：確認套件真的沒有附之後，"
                     "在 LICENSE_FROM 指定同一個 repo 的套件，或換掉這個依賴")


def render(pkgs: Sequence[Package], texts: Sequence[tuple[str, str]]) -> str:
    out = [
        "Mimiji 介面（frontend\\dist）打包的 npm 套件",
        "=" * 40,
        "",
        "這份檔案由 tools/npm_licenses.py 從 frontend/package-lock.json 產生，不要手改。",
        "清單列出所有執行期的依賴（不含開發用的套件），以及建置工具注入的程式碼；建置時沒用到的",
        "部分會被剔除，所以這份清單只會比 frontend\\dist 裡實際打包的多、不會少。",
        "",
        LISTING_START,
        "-" * 20,
        *listing(pkgs),
        "",
        f"共 {len(pkgs)} 個。",
        "",
        TEXTS_START,
        "-" * 8,
    ]
    for pkg, (source, text) in zip(pkgs, texts, strict=True):
        out += [
            "",
            RULE,
            f"{pkg.name} {pkg.version}",
            f"授權：{pkg.license}",
            f"授權全文取自：{source}",
            THIN_RULE,
            "",
            text,
        ]
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        print("用法：python tools/npm_licenses.py（不接參數）", file=sys.stderr)
        return 2
    lock = json.loads(LOCKFILE.read_text(encoding="utf-8"))
    pkgs = packages(lock)
    try:
        texts = [license_text(FRONTEND, pkg) for pkg in pkgs]
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write(render(pkgs, texts))
    print(f"寫入 {OUTPUT.relative_to(ROOT).as_posix()}：{len(pkgs)} 個套件")
    return 0


if __name__ == "__main__":
    # 輸出到管線時用的是系統碼頁；印不出的字元改用跳脫，不讓腳本自己因為編碼而失敗
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    sys.exit(main(sys.argv[1:]))
