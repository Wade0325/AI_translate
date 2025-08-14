
import pytest
from fastapi.testclient import TestClient
from backend.main import app  # 從您的主應用程式導入 app


@pytest.fixture(scope="module")
def client():
    """
    為測試提供一個 TestClient 實例。
    scope="module" 表示這個 fixture 在整個測試模組（檔案）中只會被建立一次。
    """
    with TestClient(app) as c:
        yield c
