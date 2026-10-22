"""執行期路徑安全判斷。"""

import re
from pathlib import Path
from typing import Iterable

from app.core.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# 磁碟機代號開頭（C:\x、C:/x、磁碟機相對路徑 C:x）
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")

UNSAFE_UPLOAD_FILENAME_MESSAGE = "檔案名稱不合法（不可包含路徑），請重新上傳檔案後再試。"


class UnsafeUploadFilenameError(ValueError):
    """前端送來的上傳檔名不是單純檔名；訊息可直接顯示給使用者。"""

    def __init__(self, filename):
        self.filename = filename
        super().__init__(UNSAFE_UPLOAD_FILENAME_MESSAGE)


def is_within(path, root) -> bool:
    """path 是否位於 root 目錄之下（任意層級，不含 root 本身）。

    以 resolve 後的目錄階層比對（而非檔名字串比對），相對路徑與 ``..`` 都會先展開。
    """
    try:
        return Path(root).resolve() in Path(path).resolve().parents
    except (OSError, ValueError):
        return False


def is_temp_upload(path) -> bool:
    """path 是否位於 temp_uploads 目錄下。

    刪除暫存檔前的安全鎖：防止路徑異常時誤刪其他位置的檔案。
    temp 目錄改到 data/ 下（免安裝模式）時仍然有效。
    """
    return is_within(path, get_settings().temp_uploads_path)


def delete_temp_files(paths: Iterable[Path]) -> None:
    """刪掉自己產生的暫存檔；只刪 temp_uploads 裡的，路徑異常時寧可不刪。刪不掉只記 log。"""
    for path in dict.fromkeys(paths):
        try:
            if not path.exists():
                continue
            if is_temp_upload(path):
                path.unlink()
                logger.info(f"已清理暫存檔案: {path.name}")
            else:
                logger.warning(f"已跳過清理不在 temp_uploads 目錄中的檔案: {path}")
        except Exception as e:
            logger.warning(f"清理本地檔案 {path} 失敗: {e}")


def resolve_upload_path(filename, base_dir=None) -> Path:
    """把 upload API 回傳的伺服器檔名轉成 temp_uploads 內的路徑。

    只接受單純檔名：不得含路徑分隔符（``/`` 與 ``\\`` 都擋，與作業系統無關）、
    磁碟機代號或 ``.`` / ``..``。``base / name`` 遇到絕對路徑會丟掉 base，
    所以不能直接拼接；檢查完再以 resolve() 確認結果就在 temp_uploads 底下，
    擋掉符號連結與 Windows 路徑正規化（如結尾的 ``.``）的漏網之魚。

    回傳 ``base_dir / filename``，保留 base_dir 原本的相對形式：Docker 模式的
    API 與主機端 GPU worker 靠 cwd 相對路徑共享上傳檔，不能換成容器內的絕對路徑。
    檔案是否存在由呼叫端判斷。

    Raises:
        UnsafeUploadFilenameError: 檔名不合法。
    """
    base = Path(base_dir) if base_dir is not None else get_settings().temp_uploads_path
    if (not isinstance(filename, str)
            or filename in ("", ".", "..")
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
            or _DRIVE_PREFIX.match(filename)):
        raise UnsafeUploadFilenameError(filename)

    try:
        root = base.resolve()
        resolved = (root / filename).resolve()
    except (OSError, ValueError) as e:
        raise UnsafeUploadFilenameError(filename) from e
    if resolved.parent != root:
        raise UnsafeUploadFilenameError(filename)
    return base / filename
