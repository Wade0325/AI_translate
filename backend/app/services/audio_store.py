"""保留音檔的保管。

校正介面必須能重播保留音檔。任務生命週期收尾時（``app.tasks.lifecycle``）先把
``temp_uploads`` 裡的上傳檔**搬**到 audio_store，沒保留下來的才刪掉；檔名以 task_uuid
命名，之後靠 ``TranscriptionLog.audio_filename`` 找回來。

失敗與取消的任務也保留：刪掉不可逆（使用者手機上的原檔可能已經清掉），而且
暫時性錯誤的重試會回來找同一個檔案。

搬移而非複製：同一份音檔不會同時存在兩個地方。
保留期限由 ``audio_retention_days`` 控制，啟動時清掃一次。使用者也能在設定頁看到留了多少，
一次刪掉全部（:func:`usage`、:func:`delete_all`，#231 Q1）。

沒有任務可以收尾的上傳檔也不留在暫存區：請求被拒絕時直接刪掉（:func:`discard_upload`）；
沒機會收尾的任務（例如應用程式被直接關掉時還在排隊）留下的，啟動時清掉超過
``temp_uploads_max_age_hours`` 的（:func:`purge_stale_uploads`）。

只搬 temp_uploads 裡的上傳檔（以及重試時已經在 audio_store 的保留檔），
來源路徑異常時寧可不保留，也不能把任意檔案搬走。
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.utils.logger import setup_logger
from app.utils.paths import UnsafeUploadFilenameError, is_within, resolve_upload_path

logger = setup_logger(__name__)


def store_path() -> Path:
    return get_settings().audio_store_path


def enabled() -> bool:
    """使用者有沒有開保留音檔。"""
    return get_settings().retain_audio


def retain(source: Path, task_uuid) -> Optional[str]:
    """把音檔搬進 audio_store，回傳保存後的檔名；未啟用或失敗時回傳 None。

    開著卻回 None 時，來源檔還在原處：呼叫端不能把它當成可以刪的副本。
    """
    settings = get_settings()
    if not enabled():
        return None
    try:
        source = Path(source)
        if not source.exists():
            logger.warning(f"音檔保留失敗：來源不存在 {source}")
            return None
        dest_dir = store_path()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{task_uuid}{source.suffix.lower()}"
        if source.resolve() == dest.resolve():
            return dest.name  # 重試時輸入本身就是保留檔，不用再搬
        in_store = source.resolve().parent == dest_dir.resolve()
        if not in_store and not is_within(source, settings.temp_uploads_path):
            logger.warning(f"音檔保留略過：來源不在 temp_uploads 內，不搬移 {source}")
            return None
        shutil.move(str(source), str(dest))
        logger.info(f"已保留原始音檔: {dest.name}")
        return dest.name
    except Exception as e:
        # 保留音檔失敗不該讓整個任務失敗
        logger.warning(f"音檔保留失敗 ({source}): {e}")
        return None


def resolve(filename: Optional[str]) -> Optional[Path]:
    """檔名 → 實際路徑；不存在或檔名可疑（含路徑分隔）時回傳 None。"""
    if not filename:
        return None
    name = Path(filename).name
    if name != filename:
        logger.warning(f"拒絕可疑的音檔名: {filename}")
        return None
    path = store_path() / name
    return path if path.exists() else None


def delete(filename: Optional[str]) -> bool:
    path = resolve(filename)
    if path is None:
        return False
    try:
        path.unlink()
        return True
    except OSError as e:
        logger.warning(f"刪除保留音檔失敗 ({path}): {e}")
        return False


def discard_upload(filename: str, base_dir: Optional[Path] = None) -> None:
    """刪掉不會變成任務的上傳檔（請求被拒絕）：沒有任務紀錄可以掛保留音檔，不留在電腦上。

    只刪 temp_uploads（``base_dir``，預設照設定）裡的單純檔名；檔名不合法時不動，
    刪不掉只記 log。
    """
    try:
        path = resolve_upload_path(filename, base_dir)
        if path.is_file():
            path.unlink()
            logger.info(f"已刪除被拒絕的請求的上傳檔: {path.name}")
    except UnsafeUploadFilenameError:
        return
    except OSError as e:
        logger.warning(f"刪除上傳檔失敗 ({filename}): {e}")


@dataclass(frozen=True)
class Usage:
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class Deleted:
    deleted: int
    failed: int
    """刪不掉的數量，例如 Windows 上正被開著的檔案。"""


def _stored_files() -> list[Path]:
    """保留區裡的音檔；保留區還沒建立時是空的。"""
    directory = store_path()
    if not directory.is_dir():
        return []
    return [path for path in directory.iterdir() if path.is_file()]


def usage() -> Usage:
    """保留區裡目前有幾個音檔、共多少位元組。"""
    count = total = 0
    for path in _stored_files():
        try:
            total += path.stat().st_size
        except OSError:
            continue  # 數的同時被刪掉了
        count += 1
    return Usage(file_count=count, total_bytes=total)


def delete_all() -> Deleted:
    """立即刪除全部保留音檔（設定頁的按鈕，#231 Q1）。

    和過期清掃一樣不動資料庫：``audio_filename`` 指向已刪除的檔案時，端點回 404。
    刪不掉的只記 log，其他照刪。
    """
    deleted = failed = 0
    for path in _stored_files():
        try:
            path.unlink()
            deleted += 1
        except OSError as e:
            failed += 1
            logger.warning(f"刪除保留音檔失敗 ({path.name}): {e}")
    logger.info(f"使用者刪除全部保留音檔：刪掉 {deleted} 個，{failed} 個刪不掉")
    return Deleted(deleted=deleted, failed=failed)


def purge_expired() -> int:
    """刪除超過保留天數的音檔，回傳刪除數量。

    只看檔案 mtime，不動資料庫：``audio_filename`` 指向已刪除的檔案時，
    端點會回 404，前端據此顯示「音檔已過期」。
    """
    settings = get_settings()
    directory = store_path()
    if not directory.is_dir() or settings.audio_retention_days <= 0:
        return 0
    cutoff = time.time() - settings.audio_retention_days * 86400
    removed = 0
    for path in directory.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as e:
            logger.warning(f"清理過期音檔失敗 ({path}): {e}")
    if removed:
        logger.info(f"已清理 {removed} 個超過 {settings.audio_retention_days} 天的音檔")
    return removed


def purge_stale_uploads() -> int:
    """刪除暫存上傳區裡超過 ``temp_uploads_max_age_hours`` 小時的檔案，回傳刪除數量。

    任務結束時會自己保留或清理上傳檔；這裡收的是沒機會收尾的：應用程式被直接關掉時還在
    排隊或執行的任務、中途被終止的 worker 留下的上傳檔與分段轉錄的暫存檔。只看檔案 mtime。
    """
    settings = get_settings()
    directory = settings.temp_uploads_path
    hours = settings.temp_uploads_max_age_hours
    if not directory.is_dir() or hours <= 0:
        return 0
    cutoff = time.time() - hours * 3600
    removed = 0
    for path in directory.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as e:
            logger.warning(f"清理暫存上傳檔失敗 ({path}): {e}")
    if removed:
        logger.info(f"已清理暫存區裡 {removed} 個超過 {hours} 小時的上傳檔")
    return removed
