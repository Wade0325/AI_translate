"""免安裝版 SQLite 的升級測試（#48）。

免安裝版的 app.db 會跨版本保留，新版程式要接手舊版建立的資料庫，而 init_db() 的自動
遷移只會補缺少的欄位（不帶 NOT NULL 與預設值）與索引（不帶 UNIQUE）。這裡對
tests/fixtures/sqlite_schema/ 的每一份凍結 schema，在暫存資料夾建 SQLite、跑
init_db()，再和用目前 models.py 新建的資料庫比對欄位、型別、可空性與唯一約束。

凍結檔：
  * 每一份是某一版 models.py 在 SQLite 建出的 DDL，檔頭註明來源 commit。還沒發布過
    免安裝版，第一份取自 #48 開工時的 main。
  * 每次發布免安裝版之前另存一份：在 repo 根目錄把環境變數 PYTHONPATH 設成 backend，用
    裝了 backend/requirements-dev.txt 的 python 執行
    ``python tests/unit/test_sqlite_upgrade.py <名稱> <commit>``，寫進
    tests/fixtures/sqlite_schema/<名稱>.sql；檔名依發布順序排序。
  * 既有的凍結檔一律不改。之後的 PR 改到資料表結構、讓這個測試變紅時，要把 SQLite 的
    升級步驟做進程式，不能靠改寫凍結檔讓它變綠（docs/agents/merging.md 的資料表結構
    例外）。代理在 check 綠燈後就自己合併，這條規則沒有人工把關，所以寫在這裡。

測試把 session.py 模組層級的 engine 與 SessionLocal 換成暫存資料夾裡的 SQLite，不碰
資料目錄的 app.db 或任何既有的資料庫。
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, String, Table, UniqueConstraint, inspect

from app.database import models, session

FROZEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sqlite_schema"
FROZEN_SCHEMAS = sorted(FROZEN_DIR.glob("*.sql"))


def _snapshot(engine) -> dict:
    """{表名: {"columns": {欄名: (型別, 可空)}, "unique": {(欄名, ...)}}}"""
    inspector = inspect(engine)
    snapshot = {}
    for table in inspector.get_table_names():
        columns = {
            c["name"]: (str(c["type"]), c["nullable"])
            for c in inspector.get_columns(table)
        }
        unique = {
            tuple(sorted(u["column_names"]))
            for u in inspector.get_unique_constraints(table)
        } | {
            tuple(sorted(i["column_names"]))
            for i in inspector.get_indexes(table) if i["unique"]
        }
        snapshot[table] = {"columns": columns, "unique": unique}
    return snapshot


def _schema_diff(upgraded_engine, fresh_engine) -> list[str]:
    """升級後與新建的資料庫逐項比對，回傳差異；一致時回傳空清單。"""
    upgraded, fresh = _snapshot(upgraded_engine), _snapshot(fresh_engine)
    diff = []
    for table in sorted(fresh.keys() - upgraded.keys()):
        diff.append(f"{table}：升級後少了這張表")
    for table in sorted(upgraded.keys() - fresh.keys()):
        diff.append(f"{table}：升級後多了這張表")
    for table in sorted(fresh.keys() & upgraded.keys()):
        old_cols, new_cols = upgraded[table]["columns"], fresh[table]["columns"]
        for name in sorted(new_cols.keys() - old_cols.keys()):
            diff.append(f"{table}.{name}：升級後少了這個欄位")
        for name in sorted(old_cols.keys() - new_cols.keys()):
            diff.append(f"{table}.{name}：升級後多了這個欄位（models.py 已刪除）")
        for name in sorted(new_cols.keys() & old_cols.keys()):
            (old_type, old_null), (new_type, new_null) = old_cols[name], new_cols[name]
            if old_type != new_type:
                diff.append(f"{table}.{name}：型別是 {old_type}，新建的是 {new_type}")
            if old_null != new_null:
                diff.append(f"{table}.{name}：可空性是 {_nullable(old_null)}，"
                            f"新建的是 {_nullable(new_null)}")
        old_unique, new_unique = upgraded[table]["unique"], fresh[table]["unique"]
        for cols in sorted(new_unique - old_unique):
            diff.append(f"{table}：升級後少了唯一約束 ({', '.join(cols)})")
        for cols in sorted(old_unique - new_unique):
            diff.append(f"{table}：升級後多了唯一約束 ({', '.join(cols)})")
    return diff


def _nullable(value: bool) -> str:
    return "NULL" if value else "NOT NULL"


@pytest.fixture
def sqlite_engine(tmp_path):
    """在 tmp_path 建 SQLite 檔的 engine（和免安裝模式同一個工廠）；測試結束時釋放檔案。"""
    engines = []

    def make(name: str):
        engine = session._create_engine(f"sqlite:///{(tmp_path / name).as_posix()}")
        engines.append(engine)
        return engine

    yield make
    for engine in engines:
        engine.dispose()


def _upgrade(engine, monkeypatch, build_old):
    """build_old 在 engine 建出舊版資料庫，換掉 session 的 engine 後跑 init_db()。"""
    build_old(engine)
    monkeypatch.setattr(session, "engine", engine)
    monkeypatch.setattr(session, "SessionLocal", session.sessionmaker(bind=engine))
    session.init_db()
    return engine


def _fresh(engine):
    models.Base.metadata.create_all(engine)
    return engine


def _run_ddl(ddl: str):
    def build(engine):
        connection = engine.raw_connection()
        try:
            connection.executescript(ddl)
        finally:
            connection.close()
    return build


def _dump_ddl(engine) -> str:
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
            "ORDER BY type = 'index', name"
        ).all()
    return "".join(f"{row[0]};\n\n" for row in rows)


def test_there_is_a_frozen_schema():
    assert FROZEN_SCHEMAS, f"{FROZEN_DIR} 底下沒有凍結的 schema"


@pytest.mark.parametrize("frozen", FROZEN_SCHEMAS, ids=lambda path: path.stem)
def test_upgraded_database_matches_fresh_one(frozen, sqlite_engine, monkeypatch):
    ddl = frozen.read_text(encoding="utf-8")
    upgraded = _upgrade(sqlite_engine("old.db"), monkeypatch, _run_ddl(ddl))

    diff = _schema_diff(upgraded, _fresh(sqlite_engine("fresh.db")))

    assert not diff, (
        f"用 {frozen.name} 建的資料庫跑過 init_db() 之後和新建的不一致，"
        "自動遷移補不了這些差異：\n  " + "\n  ".join(diff) + "\n"
        "要把 SQLite 的升級步驟做進程式（見 backend/app/database/models.py 檔頭的"
        "遷移說明），不要改寫凍結檔。"
    )


def _legacy_metadata(*, omit=(), retype=None, extra=(), unique=True) -> MetaData:
    """模擬舊版：目前的 models.py，只有 transcript_segments 照參數改過。

    omit 是舊版還沒有的欄位、retype 是舊版的型別、extra 是舊版有而現在刪掉的欄位、
    unique=False 是舊版還沒有 (task_uuid, seg_key) 的唯一約束。
    """
    retype = retype or {}
    metadata = MetaData()
    for table in models.Base.metadata.sorted_tables:
        if table.name != "transcript_segments":
            table.to_metadata(metadata)
    current = models.Base.metadata.tables["transcript_segments"]
    columns = [
        Column(c.name, retype.get(c.name, c.type), primary_key=c.primary_key,
               nullable=c.nullable)
        for c in current.columns if c.name not in omit
    ]
    constraints = [UniqueConstraint("task_uuid", "seg_key")] if unique else []
    Table("transcript_segments", metadata, *columns, *extra, *constraints)
    return metadata


def test_dropped_column_is_reported(sqlite_engine, monkeypatch):
    legacy = _legacy_metadata(extra=[Column("legacy_note", String)])
    old = _upgrade(sqlite_engine("old.db"), monkeypatch, legacy.create_all)

    diff = _schema_diff(old, _fresh(sqlite_engine("fresh.db")))

    assert "transcript_segments.legacy_note：升級後多了這個欄位（models.py 已刪除）" in diff, diff


def test_new_not_null_column_is_reported(sqlite_engine, monkeypatch):
    # 舊版還沒有 seg_key：自動遷移補上的欄位不帶 NOT NULL
    legacy = _legacy_metadata(omit={"seg_key"}, unique=False)
    old = _upgrade(sqlite_engine("old.db"), monkeypatch, legacy.create_all)

    diff = _schema_diff(old, _fresh(sqlite_engine("fresh.db")))

    assert "transcript_segments.seg_key：可空性是 NULL，新建的是 NOT NULL" in diff, diff


def test_changed_type_is_reported(sqlite_engine, monkeypatch):
    legacy = _legacy_metadata(retype={"seq": String()})
    old = _upgrade(sqlite_engine("old.db"), monkeypatch, legacy.create_all)

    diff = _schema_diff(old, _fresh(sqlite_engine("fresh.db")))

    assert "transcript_segments.seq：型別是 VARCHAR，新建的是 INTEGER" in diff, diff


def test_new_unique_constraint_is_reported(sqlite_engine, monkeypatch):
    legacy = _legacy_metadata(unique=False)
    old = _upgrade(sqlite_engine("old.db"), monkeypatch, legacy.create_all)

    diff = _schema_diff(old, _fresh(sqlite_engine("fresh.db")))

    assert "transcript_segments：升級後少了唯一約束 (seg_key, task_uuid)" in diff, diff


if __name__ == "__main__":
    # 凍結目前 models.py 的 SQLite schema；用法見檔頭
    name, commit = sys.argv[1:3]
    engine = session._create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    target = FROZEN_DIR / f"{name}.sql"
    if target.exists():
        sys.exit(f"{target} 已存在：既有的凍結檔一律不改")
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    header = f"-- 凍結的 SQLite schema：models.py @ {commit}。既有的凍結檔一律不改，見 tests/unit/test_sqlite_upgrade.py。\n\n"
    target.write_text(header + _dump_ddl(engine), encoding="utf-8", newline="\n")
    print(f"寫入 {target}")
