"""免安裝版的 zip 檢查（#256）：CI 的 portable job 在 Windows 上建置之後呼叫，不上傳、不發布。

用法（在哪個目錄執行都可以，一律以 repo 根目錄為基準）：

    python tools/portable_zip.py plant          # 建置前：放進用過的開發環境會有的執行期資料
    python tools/portable_zip.py check <zip>    # 建置後：檢查 zip

- ``plant``：CI 的 checkout 是乾淨的，沒有執行期資料可以漏；先在 backend/ 與 data/ 放一份
  （PLANTED），build_release.ps1 取後端檔案的那一步才真的被考到。只新增檔案，已經存在的
  不覆寫，所以不會蓋掉本機的 .env 或資料庫；但檔案會留在工作目錄裡，本機不必執行。
- ``check``：
  1. zip 的最上層剛好一個資料夾：解壓後是一個資料夾，不會把檔案散在解壓的位置。
  2. build_release.ps1 第 7 步的清單（``$required``）每一個都在，而且不是空檔。清單直接讀
     build_release.ps1，那裡是唯一來源；改清單時這裡不必跟著改。
  3. backend/ 底下只有後端白名單（build_release.ps1 的 ``$BackendPaths``，#266）裡的路徑，
     加上建置時寫的 VERSION。
  4. 沒有執行期資料：使用者的音檔、資料庫、環境變數檔（可能有 API 金鑰）、日誌檔，以及開發環境
     的殘留（runtime_data()）。檢查的是 zip 本身，和 build_release.ps1 怎麼挑檔案無關：取檔的
     方式出錯或被改掉時，一樣抓得到。
  5. 批次檔（start.bat，#267）cmd 讀得對：開頭沒有 BOM（cmd 會把它當成第一行指令的一部分），
     換行一律是 CRLF（batch_file_problems()）。
  檢查完列出 zip 裡的每一個檔案與大小：改到打包的 PR 可以拿 main 與 PR 的 CI 日誌比對發布包的內容。

只用標準函式庫：CI 的 runner 不必安裝依賴。
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "build_release.ps1"

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


def batch_file_problems(data: bytes) -> list[str]:
    """批次檔的內容 cmd 會讀錯的地方；沒有問題時是空的。"""
    problems = []
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append("開頭有 BOM，cmd 會把它當成第一行指令的一部分")
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


def check(zip_path: Path, required: Sequence[str], backend: Sequence[str]) -> list[str]:
    """檢查免安裝版的 zip；回傳每一個問題的說明，沒有問題時是空的。

    required 是必要的檔案，backend 是後端白名單；兩者都是最上層資料夾以下的路徑，用 /。
    """
    entries = contents(zip_path)
    if not entries:
        return ["zip 是空的"]

    tops = sorted({name.split("/", 1)[0] for name in entries})
    loose = sorted(name for name, (is_dir, _) in entries.items() if "/" not in name and not is_dir)
    if len(tops) != 1 or loose:
        return [f"zip 的最上層應該剛好是一個資料夾，實際是：{'、'.join(tops)}"]
    top = tops[0]

    problems = []
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
    problems = check(args.zip, required, backend_paths(script))
    files = sorted((name, size) for name, (is_dir, size) in contents(args.zip).items() if not is_dir)
    print(f"{args.zip} 的內容（{len(files)} 個檔案，位元組）：")
    for name, size in files:
        print(f"  {size:>12}  {name}")
    if problems:
        print(f"{args.zip} 有 {len(problems)} 個問題：")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"{args.zip}：必要的 {len(required)} 個檔案都在，後端只有白名單裡的檔案，沒有執行期資料")
    return 0


if __name__ == "__main__":
    # 輸出到管線時用的是系統碼頁；印不出的字元改用跳脫，不讓腳本自己因為編碼而失敗
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.exit(main())
