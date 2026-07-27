"""執行期路徑安全判斷。"""

from pathlib import Path

from app.core.config import get_settings


def is_temp_upload(path) -> bool:
    """path 是否位於 temp_uploads 目錄下。

    刪除暫存檔前的安全鎖：防止路徑異常時誤刪其他位置的檔案。
    以 resolve 後的目錄階層比對（而非檔名字串比對），
    temp 目錄改到 data/ 下（standalone 模式）時仍然有效。
    """
    try:
        root = get_settings().temp_uploads_path.resolve()
        return root in Path(path).resolve().parents
    except OSError:
        return False
