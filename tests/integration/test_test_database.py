"""測試用的資料庫要和真的一樣：每個 session 各用自己的連線。

背景任務（行程內執行模式的執行緒）和 API 請求同時開著 session。請求收尾時關掉
自己的 session，連線歸還連線池時會 rollback；如果兩邊共用同一條連線，這個 rollback
會把背景任務還沒 commit 的寫入一起丟掉，任務明明廣播了完成，紀錄卻停在舊狀態。
真的 Postgres 與免安裝版的 SQLite 檔案每個 session 都有自己的連線，測試也要如此。
"""
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database.models import BatchJob

BATCH_ID = "test-database-isolation"


def test_closing_one_session_keeps_another_sessions_pending_write(test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    worker, request = Session(), Session()
    try:
        worker.add(BatchJob(batch_id=BATCH_ID, status="COMPLETED"))
        worker.flush()  # 背景任務的寫入，還沒 commit

        request.execute(select(BatchJob.batch_id).limit(1)).all()
        request.close()  # 請求收尾：連線歸還連線池時 rollback

        worker.commit()
    finally:
        worker.close()
        request.close()

    with Session() as check:
        stored = check.get(BatchJob, BATCH_ID)
        assert stored is not None and stored.status == "COMPLETED"
        check.delete(stored)
        check.commit()
