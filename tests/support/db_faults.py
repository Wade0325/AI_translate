"""資料庫出錯的模擬：測試期間用 SQLite 的 trigger 擋下某張表的 INSERT、UPDATE 或 DELETE。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

DISK_FULL = "database or disk is full"
NOT_NULL = "violates not-null constraint"


def rejected_row(table: str, row: str) -> str:
    """Postgres 回報違反約束的訊息：第一行是原因，之後的 DETAIL 是寫不進去的那一整列。

    SQLite 不會附上資料列，用 trigger 的錯誤訊息模擬。
    """
    return (f'null value in column "created_at" of relation "{table}" {NOT_NULL}\n'
            f'DETAIL:  Failing row contains ({row}).')


@contextmanager
def writes_fail(engine, table: str, statement: str, message: str = DISK_FULL,
                when: Optional[str] = None):
    """這段期間資料庫擋下 table 的 INSERT、UPDATE 或 DELETE（statement），回報 message。

    ``when`` 是 trigger 的條件（SQLite 的 WHEN 子句，例如 ``NEW.text LIKE '%秘密%'``）：只擋下符合的
    列；沒給時每一列都擋。
    """
    trigger = f"{table}_{statement.lower()}_fails"
    literal = message.replace("'", "''")
    condition = f" WHEN {when}" if when else ""
    _change_schema(engine, f"CREATE TRIGGER {trigger} BEFORE {statement} ON {table}{condition} "
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
