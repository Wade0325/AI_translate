"""透過 API 跑任務的整合測試用的 TestClient：任務寫進測試的 sqlite，啟動時開始轉送狀態廣播。"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import Iterator

from fastapi.testclient import TestClient


@contextmanager
def api_client(test_engine) -> Iterator[TestClient]:
    """啟動 WebSocket 狀態監聽器的 TestClient，結束時換回 app 原本的 lifespan 與資料庫。

    執行模式要先換上：監聽器在啟動時向當時的執行模式訂閱狀態廣播。
    """
    from sqlalchemy.orm import sessionmaker

    from app.database.session import get_db
    from app.websocket.manager import manager
    from main import app

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    @asynccontextmanager
    async def lifespan(_app):
        manager.start()
        yield
        await manager.shutdown()

    original = app.router.lifespan_context
    app.router.lifespan_context = lifespan
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.router.lifespan_context = original
        app.dependency_overrides.clear()
