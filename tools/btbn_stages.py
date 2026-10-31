"""BtbN/FFmpeg-Builds 的 scripts.d：我們用的 build 建了哪些函式庫、各自的原始碼在哪（#274）。

ffmpeg.exe 是靜態 build，scripts.d 的每個 stage 建一個函式庫，裝進同一個 prefix 給 FFmpeg 連結。這裡照
BtbN 的 generate.sh 的規則，算出 win64、lgpl、9.0 這個組合建了哪些 stage：

- 從最後一個 stage（zz-final）的 ffbuild_depends 一路展開；ffbuild_enabled 不成立的 stage 不建，
  它的依賴也不算。
- 資料夾 stage（例如 45-fonts）：最後一個腳本成立，整個 stage 才建；裡面每個腳本再各自看 ffbuild_enabled。

只解析、不執行 BtbN 的腳本：ffbuild_enabled、ffbuild_depends 只認得目前用到的幾種寫法，下載步驟
（ffbuild_dockerdl）也只認得已知的指令。BtbN 改了寫法時直接停下來，要人看過再更新這裡，不猜。

建了不代表連進 ffmpeg.exe（例如 openssl 在 Windows 上只給 libssh、srt 用），所以清單只會多、不會少。
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

TARGET = "win64"
VARIANT = "lgpl"
ADDINS_STR = "9.0"
_FFVER = {"4.3": 403, "4.4": 404, "5.0": 500, "5.1": 501, "6.0": 600, "6.1": 601, "7.0": 700,
          "7.1": 701, "8.0": 800, "8.1": 801, "9.0": 900}
_VARS = {"TARGET": TARGET, "VARIANT": VARIANT, "ADDINS_STR": ADDINS_STR}

_SCRIPT_VAR = re.compile(r'^SCRIPT_(\w+)="([^"]*)"', re.M)
_RETURN = re.compile(r"^return\s+(-?\d+)$")
_GUARD = re.compile(r"^(?P<cond>.+?)\s*(?P<op>&&|\|\|)\s*return\s+(?P<code>-?\d+)$")
_TEST = re.compile(r"^\$(\w+)\s*(==|!=)\s*(\S+)$")
_ARITH = re.compile(r"^\(\(\s*\$\(ffbuild_ffver\)\s*(>=|<=|>|<|==|!=)\s*(\d+)\s*\)\)$")
_SUBSHELL = re.compile(r"^\(\s*source\s+(\S+)\s*&&\s*ffbuild_enabled\s*\)$")

# 下載步驟裡認得的指令。值是這一行代表的額外來源；None 表示不影響授權（例如產生 configure）。
_DL_LINES: list[tuple[re.Pattern[str], str | None]] = [
    (re.compile(r'^default_dl \S+$'), None),
    (re.compile(r'^return 0$|^true$'), None),
    (re.compile(r'^echo "git-mini-clone \\"\$SCRIPT_REPO\d\\" \\"\$SCRIPT_COMMIT\d\\" [\w-]+"$'), None),
    (re.compile(r'^echo "git submodule update --init --recursive(?P<args>[^"]*)"$'), "submodules"),
    (re.compile(r'^echo "meson subprojects download (?P<args>[\w-]+)"$'), "meson"),
    (re.compile(r'^echo "\./utils/git-sync-deps \|\| exit \$\?"$'), "git-sync-deps"),
    (re.compile(r"^echo 'mkdir \.cargo && .*cargo vendor .*'$"), None),
    (re.compile(r'^echo "git fetch --unshallow( --filter=blob:none)?"$'), None),
    (re.compile(r'^echo "autoreconf -i"$|^echo "\./autogen\.sh"$'), None),
    (re.compile(r'^echo "rm -rf \.git(?P<args>( \w+)*)"$'), "removed"),
    (re.compile(r'^echo "git clone (--filter=blob:none )?\\"\$SCRIPT_REPO\\" \. && '
                r'git checkout \\"\$SCRIPT_COMMIT\\""$'), None),
    (re.compile(r"""^echo "retry-tool sh -c \\"rm -rf \w+ && git clone '\$SCRIPT_REPO' \w+\\" && """
                r"""cd \w+ && git checkout \\"\$SCRIPT_COMMIT\\""$"""), None),
    (re.compile(r"""^echo "retry-tool sh -c \\"rm -rf \w+ && git clone '\$SCRIPT_MIRROR' \w+\\" && """
                r"""git -C \w+ checkout \\"\$SCRIPT_COMMIT\\""$"""), None),
    (re.compile(r"""^echo "cd \w+ && retry-tool sh -c \\"rm -rf \w+ && git clone --filter=blob:none """
                r"""'\$SCRIPT_MIRROR2' \w+\\" && git -C \w+ checkout \\"\$SCRIPT_COMMIT2\\" && """
                r"""rm -rf \w+/\.git"$"""), None),
    (re.compile(r"""^echo "retry-tool sh -c \\"rm -rf \w+ && svn (--non-interactive )?checkout """
                r"""(--username 'anonymous' --password '' )?'\$\{SCRIPT_REPO\}@\$\{SCRIPT_REV\}' \w+\\" && """
                r"""cd \w+"$"""), None),
]


@dataclass(frozen=True)
class GitSource:
    repo: str
    ref: str  # commit 或 tag
    mirrors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SvnSource:
    repo: str
    rev: str


@dataclass
class Script:
    path: str  # scripts.d/50-aom.sh
    text: str
    variables: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.variables = dict(_SCRIPT_VAR.findall(self.text))

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name[3:].removesuffix(".sh")

    def body(self, function: str) -> list[str] | None:
        """函式的每一行（去掉空白與註解）；腳本沒定義這個函式時是 None。"""
        match = re.search(rf"^{function}\(\)\s*\{{\n(.*?)^\}}", self.text, re.M | re.S)
        if match is None:
            return None
        lines = (line.strip() for line in match.group(1).split("\n"))
        return [line for line in lines if line and not line.startswith("#")]


@dataclass
class Stage:
    """建進 prefix 的一個函式庫：腳本、原始碼，以及下載步驟帶進來的其他原始碼。"""

    script: Script
    sources: list[GitSource | SvnSource]
    submodules: tuple[str, ...] | None = None  # None 不抓子模組；() 全部；否則只抓這些路徑
    meson_wraps: tuple[str, ...] = ()
    git_sync_deps: bool = False  # shaderc：utils/git-sync-deps 依 DEPS 檔抓其他 repo
    cargo: bool = False  # 用 cargo 建置：Cargo.lock 的套件也連進去
    removed: tuple[str, ...] = ()  # 下載後刪掉、沒有用到的資料夾

    @property
    def name(self) -> str:
        return self.script.name


class Scripts:
    """scripts.d 的所有腳本：{相對路徑: 內容}，例如 {"scripts.d/50-aom.sh": "..."}。"""

    def __init__(self, files: Mapping[str, str]):
        self.files = {path: Script(path, text) for path, text in files.items()
                      if path.startswith("scripts.d/") and path.endswith(".sh")}
        self._enabled: dict[str, bool] = {}

    def resolve(self, name: str) -> list[Script]:
        """stage 名稱對到的腳本：一般 stage 是一個檔案，資料夾 stage 是裡面的每個腳本（照檔名排序）。"""
        # generate.sh 用 scripts.d/??-<名稱>：前兩個字元是排序用的
        folder = [p for p in self.files if re.fullmatch(rf"scripts\.d/[^/]{{2}}-{re.escape(name)}/[^/]+", p)]
        single = [p for p in self.files if re.fullmatch(rf"scripts\.d/[^/]{{2}}-{re.escape(name)}\.sh", p)]
        paths = sorted(folder) or single
        if not paths:
            raise ValueError(f"scripts.d 裡找不到 stage「{name}」")
        return [self.files[p] for p in paths]

    def enabled(self, script: Script) -> bool:
        if script.path not in self._enabled:
            body = script.body("ffbuild_enabled")
            self._enabled[script.path] = True if body is None else self._run_enabled(script, body)
        return self._enabled[script.path]

    def stage_enabled(self, name: str) -> bool:
        return self.enabled(self.resolve(name)[-1])

    def depends(self, script: Script) -> list[str]:
        if not self.enabled(script):
            return []
        body = script.body("ffbuild_depends")
        if body is None:
            return ["base"]  # util/vars.sh 的預設
        names = []
        for line in body:
            if line == "return 0":
                continue
            match = re.fullmatch(r"echo ([\w-]+)", line)
            if match is None:
                raise ValueError(f"{script.path} 的 ffbuild_depends 有看不懂的一行：{line}")
            names.append(match.group(1))
        return names

    def closure(self) -> list[str]:
        """從最後一個 stage（zz-final）展開的所有 stage 名稱，照第一次遇到的順序。"""
        # generate.sh 的 ENTRYSCRIPT：scripts.d 最上層照名稱排序的最後一個
        entry = max(PurePosixPath(p).parts[1] for p in self.files)
        seen: list[str] = []

        def visit(scripts: list[Script]) -> None:
            for script in scripts:
                for dep in self.depends(script):
                    if dep not in seen:
                        seen.append(dep)
                        visit(self.resolve(dep))

        visit([self.files[f"scripts.d/{entry}"]])
        return seen

    def stages(self) -> list[Stage]:
        """這個 build 建了的函式庫（stage 裡 ffbuild_enabled 成立的腳本），照名稱排序。"""
        built = []
        for name in self.closure():
            if not self.stage_enabled(name):
                continue
            for script in self.resolve(name):
                if self.enabled(script) and script.variables.get("SKIP") != "1":
                    built.append(_stage(script))
        return sorted(built, key=lambda s: s.script.path)

    def configure_flags(self, script: Script) -> set[str]:
        """ffbuild_configure 會輸出的 --enable-xxx（有條件的也算進來，只用來交叉檢查）。"""
        body = script.body("ffbuild_configure") or []
        return {flag for line in body for flag in re.findall(r"--enable-[\w-]+", line)}

    # --- ffbuild_enabled 的解析 ---

    def _run_enabled(self, script: Script, body: list[str]) -> bool:
        status = 0
        for line in body:
            if match := _RETURN.match(line):
                return int(match.group(1)) == 0
            if match := _GUARD.match(line):
                ok = self._chain(script, match.group("cond"))
                if ok == (match.group("op") == "&&"):
                    return int(match.group("code")) == 0
                status = 0 if ok else 1
                continue
            status = 0 if self._chain(script, line) else 1
        return status == 0

    def _chain(self, script: Script, text: str) -> bool:
        return all(self._atom(script, atom) for atom in _split_and(text))

    def _atom(self, script: Script, atom: str) -> bool:
        if atom.startswith("[[") and atom.endswith("]]"):
            inner = atom[2:-2].strip()
            return all(_test(script, part) for part in _split_and(inner))
        if match := _ARITH.match(atom):
            return _compare(_FFVER[ADDINS_STR], match.group(1), int(match.group(2)))
        if match := _SUBSHELL.match(atom):
            return self.enabled(self.files[match.group(1)])
        raise ValueError(f"{script.path} 的 ffbuild_enabled 有看不懂的條件：{atom}")


def _split_and(text: str) -> list[str]:
    """以最外層的 && 切開（[[ ]]、(( ))、( ) 裡的不切）。"""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        if text.startswith(("[[", "(("), i):
            depth += 1
            i += 2
            continue
        if text.startswith(("]]", "))"), i):
            depth -= 1
            i += 2
            continue
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        elif depth == 0 and text.startswith("&&", i):
            parts.append(text[start:i].strip())
            start = i + 2
            i += 2
            continue
        i += 1
    parts.append(text[start:].strip())
    return parts


def _test(script: Script, expr: str) -> bool:
    match = _TEST.match(expr)
    if match is None or match.group(1) not in _VARS:
        raise ValueError(f"{script.path} 的 ffbuild_enabled 有看不懂的條件：[[ {expr} ]]")
    same = fnmatch.fnmatchcase(_VARS[match.group(1)], match.group(3))
    return same if match.group(2) == "==" else not same


def _compare(left: int, op: str, right: int) -> bool:
    return {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right,
            "==": left == right, "!=": left != right}[op]


def _stage(script: Script) -> Stage:
    v = script.variables
    sources: list[GitSource | SvnSource] = []
    if "REV" in v:
        sources.append(SvnSource(v["REPO"], v["REV"]))
    else:
        for suffix in ("", "2", "3"):
            if f"REPO{suffix}" in v:
                mirrors = (v[f"MIRROR{suffix}"],) if f"MIRROR{suffix}" in v else ()
                sources.append(GitSource(v[f"REPO{suffix}"], v[f"COMMIT{suffix}"], mirrors))
    if not sources:
        raise ValueError(f"{script.path} 沒有 SCRIPT_REPO，也沒有標 SCRIPT_SKIP")
    stage = Stage(script, sources, cargo=bool(re.search(r"\bcargo\b", script.text)))
    body = script.body("ffbuild_dockerdl")
    for line in ["default_dl ."] if body is None else body:
        kind, args = _dl_line(script, line)
        if kind == "submodules":
            paths = [a for a in args.split() if not a.startswith("-") and not a.isdigit()]
            stage.submodules = tuple(paths)
        elif kind == "meson":
            stage.meson_wraps += (args,)
        elif kind == "git-sync-deps":
            stage.git_sync_deps = True
        elif kind == "removed":
            stage.removed += tuple(args.split())
    return stage


def _dl_line(script: Script, line: str) -> tuple[str | None, str]:
    for pattern, kind in _DL_LINES:
        if match := pattern.match(line):
            return kind, (match.groupdict().get("args") or "")
    raise ValueError(f"{script.path} 的下載步驟有看不懂的一行：{line}")
