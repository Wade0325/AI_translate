"""資料庫出錯的模擬：測試期間用 SQLite 的 trigger 擋下某張表的 INSERT 或 UPDATE。"""

from __future__ import annotations

from contextlib import contextmanager

DISK_FULL = "database or disk is full"


@contextmanager
def writes_fail(engine, table: str, statement: str, message: str = DISK_FULL):
    """這段期間資料庫擋下 table 的 INSERT 或 UPDATE（statement），回報 message。"""
    trigger = f"{table}_{statement.lower()}_fails"
    literal = message.replace("'", "''")
    _change_schema(engine, f"CREATE TRIGGER {trigger} BEFORE {statement} ON {table} "
                           f"BEGIN SELECT RAISE(ABORT, '{literal}'); END")
    try:
        yield
    finally:
        _change_schema(engine, f"DROP TRIGGER {trigger}")


def _change_schema(engine, ddl: str) -> None:
    with engine.begin() as conn:
        # 連線池裡的連線記著自己上次讀到的 schema，SQLite 解析 CREATE／DROP 時就照它判斷
        # trigger 在不在：用過這條連線之後別條連線才拿掉的 trigger，在這裡還「已經存在」。
        # 先讀一次，讓它重新載入 schema
        conn.exec_driver_sql("SELECT count(*) FROM sqlite_master")
        conn.exec_driver_sql(ddl)
