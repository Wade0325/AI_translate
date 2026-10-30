import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional, TextIO

# 抑制 httpx / httpcore 的底層 HTTP 請求 log（避免檔案上傳分塊時產生大量雜訊）
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_FORMAT = '%(asctime)s - %(levelname)s - [%(path_aligned)s] - %(message)s'
_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


# 自訂 formatter 以實現路徑顯示和對齊
class PathAlignedFormatter(logging.Formatter):
    def __init__(self):
        super().__init__(_FORMAT, datefmt=_DATE_FORMAT)

    def format(self, record):
        # 從 logger name 中提取路徑資訊
        if hasattr(record, 'name') and record.name:
            # 例如: app.services.vad.flows -> vad/flows.py
            name_parts = record.name.split('.')
            if len(name_parts) >= 3 and name_parts[0] == 'app':
                # 取最後兩層: services.vad.flows -> vad/flows
                if len(name_parts) >= 4:
                    path_display = f"{name_parts[-2]}/{record.filename}"
                else:
                    path_display = f"{name_parts[-1]}/{record.filename}"
            else:
                path_display = record.filename
        else:
            path_display = record.filename

        # 建立 path:lineno 字串並左對齊到 25 字元
        file_line = f"{path_display}:{record.lineno}"
        record.path_aligned = f"{file_line:<25}"
        return super().format(record)


def _home_pattern(home: str) -> Optional[re.Pattern]:
    """比對路徑裡的使用者家目錄：``/`` 與 ``\\`` 都算分隔符號，也比對 repr 裡變成兩個的 ``\\``
    （例如 OSError 的訊息），不分大小寫（Windows 的路徑不分）。

    家目錄是根目錄（例如 ``/`` 或 ``C:\\``）時不比對，否則每個路徑都會被換掉。
    """
    parts = [part for part in re.split(r"[\\/]", home) if part]
    rooted = home[:1] in ("/", "\\")
    if not parts or (len(parts) == 1 and not rooted):
        return None
    separator = r"[\\/]+"
    return re.compile((separator if rooted else "") + separator.join(map(re.escape, parts)),
                      re.IGNORECASE)


class _DeidentifyingFormatter(PathAlignedFormatter):
    """日誌檔的格式：和主控台相同，但使用者家目錄寫成 ``~``（路徑裡常有帳號名稱）。"""

    def __init__(self, home: str):
        super().__init__()
        self._home = _home_pattern(home)

    def format(self, record):
        text = super().format(record)
        return self._home.sub("~", text) if self._home else text


class DailyLogFile(logging.Handler):
    """免安裝模式的日誌檔（#231 Q5、ADR-0005）：每天一個檔 ``app-YYYY-MM-DD.log``，保留最近 7 天。

    每個 app 的 logger 都接著同一個實例（:data:`LOG_FILE`），:meth:`start` 之前什麼都不寫，所以
    Docker 模式與測試不會留下日誌檔。寫進去的 log 先去識別：使用者家目錄寫成 ``~``。原檔名與轉錄
    內容不在這裡過濾，而是一開始就不寫進 log：上傳檔在磁碟上是隨機名稱（app/api/upload.py），
    狀態廣播只記狀態碼（app/websocket/manager.py），ffmpeg 只輸出錯誤、不列音檔的標籤
    （app/utils/audio.py 的 FFMPEG_ERRORS_ONLY）。
    """

    PREFIX = "app-"
    SUFFIX = ".log"

    def __init__(self, keep_days: int = 7, today: Callable[[], date] = date.today,
                 home: Optional[str] = None):
        super().__init__()
        self._keep_days = keep_days
        self._today = today
        self._home = home
        self._folder: Optional[Path] = None
        self._day: Optional[date] = None
        self._stream: Optional[TextIO] = None

    def start(self, folder: Path) -> None:
        """開始寫進 ``folder``（不存在就建立），並刪掉超過保留天數的日誌檔。"""
        self.acquire()
        try:
            self._close_stream()
            folder.mkdir(parents=True, exist_ok=True)
            if self.formatter is None:
                self.setFormatter(_DeidentifyingFormatter(
                    self._home if self._home is not None else str(Path.home())))
            self._folder = folder
            self._open(self._today())
        finally:
            self.release()

    def stop(self) -> None:
        """不再寫，關掉日誌檔。"""
        self.acquire()
        try:
            self._close_stream()
            self._folder = None
        finally:
            self.release()

    def emit(self, record: logging.LogRecord) -> None:
        if self._folder is None:
            return
        try:
            today = self._today()
            # 過了午夜：換到新的一天的檔
            stream = self._stream if today == self._day and self._stream else self._open(today)
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self.stop()
        super().close()

    def _open(self, day: date) -> TextIO:
        assert self._folder is not None
        self._close_stream()
        self._remove_expired(self._folder, day)
        self._stream = (self._folder / f"{self.PREFIX}{day.isoformat()}{self.SUFFIX}").open(
            "a", encoding="utf-8")
        self._day = day
        return self._stream

    def _remove_expired(self, folder: Path, today: date) -> None:
        """刪掉超過保留天數的日誌檔：今天和前 ``keep_days - 1`` 天的留著。名稱不是日誌檔的不動。"""
        oldest_kept = today - timedelta(days=self._keep_days - 1)
        for path in folder.glob(f"{self.PREFIX}*{self.SUFFIX}"):
            try:
                day = date.fromisoformat(path.name[len(self.PREFIX):-len(self.SUFFIX)])
            except ValueError:
                continue
            if day < oldest_kept:
                try:
                    path.unlink()
                except OSError:
                    pass  # 刪不掉（例如被別的程式開著）下次再刪

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
        self._stream = None
        self._day = None


LOG_FILE = DailyLogFile()
"""每個 app 的 logger 共用的日誌檔；免安裝模式啟動時由 :func:`start_log_file` 開始寫。"""

_SERVER_LOGGER = "uvicorn.error"
"""uvicorn 自己的 log：啟動、連線，以及端點沒接住的例外。"""


def start_log_file(folder: Path) -> None:
    """開始把 app 與 uvicorn 的 log 寫進 ``folder`` 的日誌檔。"""
    LOG_FILE.start(folder)
    server = logging.getLogger(_SERVER_LOGGER)
    if LOG_FILE not in server.handlers:
        server.addHandler(LOG_FILE)


def stop_log_file() -> None:
    logging.getLogger(_SERVER_LOGGER).removeHandler(LOG_FILE)
    LOG_FILE.stop()


def setup_logger(name: str = None) -> logging.Logger:
    """
    設定統一的 logger 配置

    Args:
        name: logger 名稱，如果為 None 則使用呼叫模組的名稱

    Returns:
        配置好的 logger 實例
    """
    logger = logging.getLogger(name)

    # 如果 logger 已經有 handlers，直接返回（避免重複設定）
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(PathAlignedFormatter())
    logger.addHandler(handler)
    # 免安裝模式另外寫進日誌檔；開始寫之前這個 handler 什麼都不做
    logger.addHandler(LOG_FILE)

    # 防止向上傳播，避免重複輸出
    logger.propagate = False

    return logger
