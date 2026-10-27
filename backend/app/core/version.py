"""app 的版本號（#85）。

版本號只在建置時注入：build_release.ps1 把發布的 tag（例如 v0.1.0-beta.1）寫進發布包的
backend/VERSION。repo 裡沒有這個檔案，所以從原始碼執行（Docker 模式、開發）時版本號是 dev。

app 不會自己檢查更新（#85）：設定頁顯示這個版本號，旁邊放 GitHub Releases 的連結，使用者
點了才連外。
"""
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"

DEV_VERSION = "dev"


def read_version(path: Path = VERSION_FILE) -> str:
    """讀建置時寫進去的版本號；沒有檔案或是空白時是 dev。

    PowerShell 寫的檔案可能帶 BOM 與 CRLF，一併去掉。
    """
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
    except FileNotFoundError:
        return DEV_VERSION
    return text or DEV_VERSION


APP_VERSION = read_version()
