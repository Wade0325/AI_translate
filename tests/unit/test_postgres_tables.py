"""Docker 模式的 Postgres 也由自動建表建立每張表（init_db 的 create_all，#116）。

CI 沒有 Postgres：SQLite 由 test_sqlite_upgrade.py 實際建表、和升級前的資料庫比對；這裡確認
models.py 的每張表與索引都編得出 Postgres 的 DDL，沒有 Postgres 不認得的型別或約束。
"""
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.database.models import Base


@pytest.mark.parametrize("table", Base.metadata.sorted_tables, ids=lambda table: table.name)
def test_table_compiles_for_postgres(table):
    dialect = postgresql.dialect()

    ddl = str(CreateTable(table).compile(dialect=dialect))

    assert ddl.strip().startswith(f"CREATE TABLE {table.name} (")
    for index in table.indexes:
        assert index.name in str(CreateIndex(index).compile(dialect=dialect))


def test_batch_files_rows_belong_to_their_batch():
    # 每個檔案一列，記在批次底下：批次紀錄刪掉時一起刪
    ddl = str(CreateTable(Base.metadata.tables["batch_files"]).compile(dialect=postgresql.dialect()))

    assert "FOREIGN KEY(batch_id) REFERENCES batch_jobs (batch_id) ON DELETE CASCADE" in ddl
