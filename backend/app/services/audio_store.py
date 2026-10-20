"""保留音檔的保管。

校正介面必須能重播保留音檔。任務生命週期收尾時（``app.tasks.lifecycle``）先把
``temp_uploads`` 裡的上傳檔**搬**到 audio_store，沒保留下來的才刪掉；檔名以 task_uuid
命名，之後靠 ``TranscriptionLog.audio_filename`` 找回來。

失敗與取消的任務也保留：刪掉不可逆（使用者手機上的原檔可能已經清掉），而且
暫時性錯誤的重試會回來找同一個檔案。

搬移而非複製：同一份音檔不會同時存在兩個地方。
保留期限由 ``audio_retention_days`` 控制，啟動時清掃一次。

只搬 temp_uploads 裡的上傳檔（以及重試時已經在 audio_store 的保留檔），
來源路徑異常時寧可不保留，也不能把任意檔案搬走。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.utils.logger import setup_logger
from app.utils.paths import is_within

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
