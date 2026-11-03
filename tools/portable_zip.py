"""免安裝版的 zip 檢查（#256）：CI 的 portable job 在 Windows 上建置之後呼叫，不上傳、不發布。

用法（在哪個目錄執行都可以，一律以 repo 根目錄為基準）：

    python tools/portable_zip.py plant          # 建置前：放進用過的開發環境會有的執行期資料
    python tools/portable_zip.py check <zip>    # 建置後：檢查 zip

- ``plant``：CI 的 checkout 是乾淨的，沒有執行期資料可以漏；先在 backend/ 與 data/ 放一份
  （PLANTED），build_release.ps1 取後端檔案的那一步才真的被考到。只新增檔案，已經存在的
  不覆寫，所以不會蓋掉本機的 .env 或資料庫；但檔案會留在工作目錄裡，本機不必執行。
- ``check``：
  1. zip 的最上層剛好一個資料夾：解壓後是一個資料夾，不會把檔案散在解壓的位置。
  2. 名稱是產品名稱 Mimiji（#26、#277）：zip 的檔名是 ``Mimiji-<版本>-win64.zip``、最上層的資料夾是
     ``Mimiji``，檔名裡的版本和建置時寫的 backend/VERSION 相同。exe 的檔名在第 3 點的清單裡。
  3. build_release.ps1 第 7 步的清單（``$required``）每一個都在，而且不是空檔。清單直接讀
     build_release.ps1，那裡是唯一來源；改清單時這裡不必跟著改。
  4. backend/ 底下只有後端白名單（build_release.ps1 的 ``$BackendPaths``，#266）裡的路徑，
     加上建置時寫的 VERSION。
  5. 沒有執行期資料：使用者的音檔、資料庫、環境變數檔（可能有 API 金鑰）、日誌檔，以及開發環境
     的殘留（runtime_data()）。檢查的是 zip 本身，和 build_release.ps1 怎麼挑檔案無關：取檔的
     方式出錯或被改掉時，一樣抓得到。
  6. 批次檔（start.bat，#267）cmd 讀得對：只有 ASCII（cmd 遇到多位元組字元會算錯下一行的位置，
     把後面的字當成指令執行）、開頭沒有 BOM，換行一律是 CRLF（batch_file_problems()）。
  7. 只在 Windows：Mimiji.exe 的版本資訊與圖示（#277），也就是「內容 → 詳細資料」看到的：產品名稱與檔案
     描述是 Mimiji、產品版本是 backend/VERSION 的版本號、檔案版本是 4 個數字，而且至少有一個圖示
     （exe_problems()）。用 Windows 自己讀版本資訊的 API，和檔案總管看到的相同；其他平台跳過這一項。
  檢查完列出 zip 裡的每一個檔案與大小：改到打包的 PR 可以拿 main 與 PR 的 CI 日誌比對發布包的內容。

只用標準函式庫：CI 的 runner 不必安裝依賴。
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "build_release.ps1"

# 產品名稱（#26）：zip 是 Mimiji-<版本>-win64.zip，解壓後是 Mimiji 資料夾，啟動器是 Mimiji.exe。
# 刻意不從 build_release.ps1 讀：這裡是對照的一方。和 build_release.ps1 的 $ProductName、啟動器的
# AppName 相同（tests/unit/test_portable_zip.py 檢查）
PRODUCT = "Mimiji"
ZIP_NAME = re.compile(rf"{PRODUCT}-(?P<version>.+)-win64\.zip")

# 執行期資料夾：上傳暫存、去靜音的除錯產物、保留的音檔。名稱和 backend/app/core/config.py 的
# 預設值一致（tests/unit/test_portable_zip.py 檢查）；persistent_uploads 是舊版的名稱
RUNTIME_DIRS = ("temp_uploads", "vad_artifacts", "audio_store", "persistent_uploads")
# 開發環境的殘留：虛擬環境、Python 與 pytest 的快取、下載快取（可能有模型權重）
DEV_DIRS = (".venv", "__pycache__", ".pytest_cache", ".cache")
SQLITE_SUFFIXES = (".db", ".db-journal", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")

# plant 放的檔案（以 repo 根目錄為基準）：用過的開發環境裡會有的執行期資料。從原始碼執行 Docker
# 模式時，執行期資料夾以 backend/ 為 cwd 寫在它底下；免安裝模式寫在 data/。每一個都要被
# runtime_data() 判成不該打包（tests/unit/test_portable_zip.py 檢查），建置時沒排除掉就紅燈
PLANTED = (
    "backend/temp_uploads/planted.wav",
    "backend/vad_artifacts/planted.wav",
    "backend/audio_store/planted.wav",
    "backend/persistent_uploads/planted.wav",
    "backend/.env",
    "backend/app.db",
    "backend/.venv/planted.txt",
    "backend/__pycache__/planted.cpython-311.pyc",
    "backend/app/__pycache__/planted.cpython-311.pyc",
    "backend/.pytest_cache/planted.txt",
    "backend/.cache/planted.txt",
    "data/app.db",
    "data/.env",
    "data/audio_store/planted.wav",
)
PLANTED_CONTENT = b"planted by tools/portable_zip.py: must not end up in the portable zip\n"

# 一次最多列出幾個不該打包的檔案：整個 .venv 漏進去時有上萬個
MAX_LISTED = 30

# backend/ 底下白名單以外唯一可以有的檔案：建置時寫入的版本號（build_release.ps1 第 4 步）
BACKEND_GENERATED = ("backend/VERSION",)


def runtime_data(path: str) -> str | None:
    """發布包裡的一個路徑（最上層資料夾以下，用 /）不該打包時，回傳原因；可以打包時回傳 None。"""
    parts = PurePosixPath(path).parts
    if not parts:
        return None
    name = parts[-1]
    if parts[0] == "data":
        return "免安裝版的資料目錄（資料庫、設定、上傳檔與日誌）"
    for part in parts:
        if part in RUNTIME_DIRS:
            return f"執行期資料夾 {part}（使用者的音檔）"
        if part in DEV_DIRS:
            return f"開發環境的殘留 {part}"
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "環境變數檔（可能有 API 金鑰）"
    if name.endswith(SQLITE_SUFFIXES):
        return "SQLite 資料庫"
    if name.endswith(".log"):
        return "日誌檔"
    if name.endswith(".pyc"):
        return "Python 的快取"
    return None


def _string_list(script: str, variable: str, what: str) -> list[str]:
    """build_release.ps1 裡 ``$<variable> = @(...)`` 的雙引號字串，路徑改用 /。"""
    match = re.search(rf"^\${variable} = @\((.*?)\)", script, re.M | re.S)
    if not match:
        raise ValueError(f"build_release.ps1 裡找不到{what}（${variable} = @(...)）")
    items = [f.replace("\\", "/") for f in re.findall(r'"([^"]+)"', match.group(1))]
    if not items:
        raise ValueError(f"build_release.ps1 的{what}（${variable}）是空的")
    return items


def required_files(script: str) -> list[str]:
    """build_release.ps1 第 7 步的必要檔案清單（``$required = @(...)``），路徑改用 /。"""
    return _string_list(script, "required", "第 7 步的必要檔案清單")


def backend_paths(script: str) -> list[str]:
    """build_release.ps1 的後端白名單（``$BackendPaths = @(...)``）：檔案或資料夾，路徑用 /。"""
    return _string_list(script, "BackendPaths", "後端白名單")


def _in_backend_whitelist(rel: str, allowed: Sequence[str]) -> bool:
    """rel（最上層資料夾以下）是 backend/ 以外的路徑，或是白名單允許的路徑。"""
    if rel != "backend" and not rel.startswith("backend/"):
        return True
    if rel in BACKEND_GENERATED:
        return True
    # 白名單裡的檔案或資料夾本身、資料夾底下的東西，以及通往它們的上層資料夾（backend/）
    return any(rel == path or rel.startswith(f"{path}/") or path.startswith(f"{rel}/")
               for path in allowed)


@dataclass(frozen=True)
class ExeInfo:
    """exe 的版本資訊與圖示：檔案總管的「內容 → 詳細資料」顯示的那些。"""

    strings: dict[str, str]  # 版本資訊的字串：ProductName、ProductVersion、FileVersion、FileDescription…
    file_version: str  # 數字的檔案版本（VS_FIXEDFILEINFO），寫成 a.b.c.d
    icons: int


# 版本資訊裡要讀的字串
EXE_STRINGS = ("ProductName", "ProductVersion", "FileVersion", "FileDescription", "LegalCopyright",
               "OriginalFilename")


def read_exe_info(path: Path) -> ExeInfo | None:
    """用 Windows 的 API 讀 exe 的版本資訊與圖示的個數；沒有版本資訊時是 None。只能在 Windows 執行。"""
    import ctypes
    from ctypes import wintypes

    version = ctypes.WinDLL("version")
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    shell32 = ctypes.WinDLL("shell32")
    shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                       wintypes.UINT]
    shell32.ExtractIconExW.restype = wintypes.UINT

    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, data):
        return None

    def query(block: str) -> tuple[int, int] | None:
        """版本資訊裡一個區塊的（位址，長度）；字串的長度以字元計，含結尾的 NUL。"""
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not version.VerQueryValueW(data, block, ctypes.byref(pointer), ctypes.byref(length)):
            return None
        return (pointer.value, length.value) if pointer.value else None

    fixed = query("\\")
    translation = query("\\VarFileInfo\\Translation")
    if fixed is None or translation is None or translation[1] < 4:
        return None
    # VS_FIXEDFILEINFO：dwSignature、dwStrucVersion 之後是 dwFileVersionMS 與 dwFileVersionLS
    high, low = struct.unpack_from("<II", ctypes.string_at(fixed[0], 16), 8)
    language, codepage = struct.unpack("<HH", ctypes.string_at(translation[0], 4))
    strings = {}
    for key in EXE_STRINGS:
        found = query(f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{key}")
        if found is not None:
            strings[key] = ctypes.wstring_at(found[0], found[1]).rstrip("\0")
    # 圖示的索引給 -1、不給陣列時，回傳 exe 裡圖示的個數
    icons = shell32.ExtractIconExW(str(path), -1, None, None, 0)
    return ExeInfo(strings, f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}", icons)


def exe_problems(info: ExeInfo | None, name: str, version: str | None) -> list[str]:
    """exe 的版本資訊與圖示的問題（name 是 zip 裡的路徑，version 是 backend/VERSION）；沒有問題時是空的。"""
    if info is None:
        return [f"{name} 沒有版本資訊"]
    problems = []
    for key, label in (("ProductName", "產品名稱"), ("FileDescription", "檔案描述")):
        if info.strings.get(key) != PRODUCT:
            problems.append(f"{name} 的{label}是「{info.strings.get(key, '')}」，應該是 {PRODUCT}")
    if version is not None and info.strings.get("ProductVersion") != version:
        problems.append(f"{name} 的產品版本是「{info.strings.get('ProductVersion', '')}」，"
                        f"應該和 backend/VERSION 一樣是 {version}")
    file_version = info.strings.get("FileVersion", "")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", file_version) or file_version != info.file_version:
        problems.append(f"{name} 的檔案版本是「{file_version}」（數字的是 {info.file_version}），"
                        "應該是 4 個數字，兩者相同")
    if info.icons < 1:
        problems.append(f"{name} 沒有圖示")
    return problems


# main 用來讀 exe 的函式：只有 Windows 讀得到，其他平台不檢查 exe
EXE_READER: Callable[[Path], ExeInfo | None] | None = read_exe_info if sys.platform == "win32" else None


def batch_file_problems(data: bytes) -> list[str]:
    """批次檔的內容 cmd 會讀錯的地方；沒有問題時是空的。"""
    problems = []
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append("開頭有 BOM，cmd 會把它當成第一行指令的一部分")
    elif not data.isascii():
        problems.append("有 ASCII 以外的字元，cmd 會算錯下一行的位置、把後面的字當成指令執行")
    if data.replace(b"\r\n", b"").count(b"\n"):
        problems.append("換行不是 CRLF，cmd 可能讀錯行")
    return problems


def _batch_files(zip_path: Path) -> dict[str, bytes]:
    """zip 裡的批次檔：路徑（用 /）對應到內容。"""
    with zipfile.ZipFile(zip_path) as archive:
        return {info.filename.replace("\\", "/"): archive.read(info) for info in archive.infolist()
                if info.filename.lower().endswith(".bat")}


def contents(zip_path: Path) -> dict[str, tuple[bool, int]]:
    """zip 裡每一個項目：路徑（用 /，去掉結尾的 /）對應到（是不是資料夾，大小）。"""
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
    # Windows PowerShell 5.1 的 Compress-Archive 用 \ 當分隔符號（zip 規格是 /），兩種都認
    entries = {}
    for info in infos:
        name = info.filename.replace("\\", "/")
        entries[name.rstrip("/")] = (name.endswith("/"), info.file_size)
    return entries


def _read(zip_path: Path, name: str) -> bytes | None:
    """zip 裡一個檔案（路徑用 /）的內容；沒有這個檔案時是 None。"""
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.filename.replace("\\", "/") == name:
                return archive.read(info)
    return None


def _name_problems(zip_path: Path, top: str, version: str | None) -> list[str]:
    """zip 的檔名與最上層資料夾不是產品名稱，或檔名的版本和 backend/VERSION 不同。"""
    problems = []
    match = ZIP_NAME.fullmatch(zip_path.name)
    if match is None:
        problems.append(f"zip 的檔名應該是 {PRODUCT}-<版本>-win64.zip，實際是 {zip_path.name}")
    elif version is not None and match["version"] != version:
        problems.append(f"zip 檔名的版本 {match['version']} 和 {top}/backend/VERSION 的 {version} 不同")
    if top != PRODUCT:
        problems.append(f"zip 最上層的資料夾應該是 {PRODUCT}，實際是 {top}")
    return problems


def _exe_problems(zip_path: Path, top: str, version: str | None,
                  read_exe: Callable[[Path], ExeInfo | None]) -> list[str]:
    """把 zip 裡的 exe 解到暫存資料夾，交給 read_exe 讀版本資訊與圖示。exe 不在或是空的時，第 3 點已經報了。"""
    name = f"{top}/{PRODUCT}.exe"
    data = _read(zip_path, name)
    if not data:
        return []
    with tempfile.TemporaryDirectory() as folder:
        exe = Path(folder) / f"{PRODUCT}.exe"
        exe.write_bytes(data)
        return exe_problems(read_exe(exe), name, version)


def check(zip_path: Path, required: Sequence[str], backend: Sequence[str],
          read_exe: Callable[[Path], ExeInfo | None] | None = None) -> list[str]:
    """檢查免安裝版的 zip；回傳每一個問題的說明，沒有問題時是空的。

    required 是必要的檔案，backend 是後端白名單；兩者都是最上層資料夾以下的路徑，用 /。
    read_exe 讀 exe 的版本資訊與圖示（Windows 上是 read_exe_info）；None 時不檢查 exe。
    """
    entries = contents(zip_path)
    if not entries:
        return ["zip 是空的"]

    tops = sorted({name.split("/", 1)[0] for name in entries})
    loose = sorted(name for name, (is_dir, _) in entries.items() if "/" not in name and not is_dir)
    if len(tops) != 1 or loose:
        return [f"zip 的最上層應該剛好是一個資料夾，實際是：{'、'.join(tops)}"]
    top = tops[0]

    version_file = _read(zip_path, f"{top}/backend/VERSION")
    version = version_file.decode("utf-8-sig").strip() if version_file else None
    problems = _name_problems(zip_path, top, version)
    for rel in required:
        entry = entries.get(f"{top}/{rel}")
        if entry is None or entry[0]:
            problems.append(f"缺少必要的檔案：{top}/{rel}")
        elif entry[1] == 0:
            problems.append(f"必要的檔案是空的：{top}/{rel}")

    leaked = []
    for name in sorted(entries):
        if name == top:
            continue
        rel = name.split("/", 1)[1]
        reason = runtime_data(rel)
        if reason:
            leaked.append(f"不該打包：{name}（{reason}）")
        elif not _in_backend_whitelist(rel, backend):
            leaked.append(f"不該打包：{name}（不在後端白名單 $BackendPaths 裡）")
    problems += leaked[:MAX_LISTED]
    if len(leaked) > MAX_LISTED:
        problems.append(f"不該打包的還有 {len(leaked) - MAX_LISTED} 個，沒有列出")
    for name, data in sorted(_batch_files(zip_path).items()):
        problems += [f"批次檔 {name} {problem}" for problem in batch_file_problems(data)]
    if read_exe is not None:
        problems += _exe_problems(zip_path, top, version, read_exe)
    return problems


def plant(root: Path) -> list[Path]:
    """在 root 底下放 PLANTED 的檔案；已經存在的不覆寫。回傳這次新增的檔案。"""
    created = []
    for rel in PLANTED:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as f:
                f.write(PLANTED_CONTENT)
        except FileExistsError:
            continue
        created.append(path)
    return created


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/portable_zip.py",
        description="免安裝版的 zip 檢查（CI 的 portable job 用）。")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plant", help="建置前在 backend/ 與 data/ 放進執行期資料（只新增，不覆寫）")
    check_parser = commands.add_parser("check", help="檢查 zip 的結構，以及沒有執行期資料")
    check_parser.add_argument("zip", type=Path, help="build_release.ps1 產生的 zip")
    args = parser.parse_args(argv)

    if args.command == "plant":
        created = plant(ROOT)
        print(f"放進 {len(created)} 個執行期資料的檔案（已經存在的 {len(PLANTED) - len(created)} 個沒動）：")
        for path in created:
            print(f"  {path.relative_to(ROOT).as_posix()}")
        return 0

    script = BUILD_SCRIPT.read_text(encoding="utf-8-sig")
    required = required_files(script)
    read_exe = EXE_READER
    problems = check(args.zip, required, backend_paths(script), read_exe)
    files = sorted((name, size) for name, (is_dir, size) in contents(args.zip).items() if not is_dir)
    print(f"{args.zip} 的內容（{len(files)} 個檔案，位元組）：")
    for name, size in files:
        print(f"  {size:>12}  {name}")
    if problems:
        print(f"{args.zip} 有 {len(problems)} 個問題：")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"{args.zip}：名稱是 {PRODUCT}，必要的 {len(required)} 個檔案都在，後端只有白名單裡的檔案，"
          "沒有執行期資料")
    if read_exe is None:
        print(f"不是 Windows：沒有檢查 {PRODUCT}.exe 的版本資訊與圖示（CI 的 portable job 在 Windows 上檢查）")
    else:
        print(f"{PRODUCT}.exe 的產品名稱、產品版本、檔案版本與圖示都對")
    return 0


if __name__ == "__main__":
    # 輸出到管線時用的是系統碼頁；印不出的字元改用跳脫，不讓腳本自己因為編碼而失敗
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.exit(main())
