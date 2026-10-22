"""透過 API 跑完任務的整合測試共用的骨架。

供應商由各測試檔換上（假供應商，或接上假 google-genai 用戶端的 Gemini 轉接器），其他都走真的：
TestClient、sqlite、行程內執行模式與 WebSocket 狀態廣播。
"""
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(test_engine, data_dir, task_db, in_process_run_mode):
    """啟動時選行程內執行模式、啟動 WebSocket 狀態監聽器的 TestClient。

    上傳檔、保留音檔與去靜音產物都寫進暫存資料夾（``data_dir``），任務寫進測試的 sqlite。結束時先等
    任務跑完，再換回執行模式與資料庫：任務的取消檢查與收尾還會用到它們。
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
    with TestClient(app) as client:
        yield client
    in_process_run_mode.close(wait=True)
    app.router.lifespan_context = original
    app.dependency_overrides.clear()
