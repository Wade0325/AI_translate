"""透過 API 跑完任務的整合測試共用的骨架。

供應商由各測試檔換上（假供應商，或接上假 google-genai 用戶端的 Gemini 轉接器），其他都走真的：
TestClient、sqlite、行程內執行模式與 WebSocket 狀態廣播。
"""
import pytest

from tests.support.api_client import api_client


@pytest.fixture
def api(test_engine, data_dir, task_db, in_process_run_mode):
    """啟動時選行程內執行模式、啟動 WebSocket 狀態監聽器的 TestClient。

    上傳檔、保留音檔與去靜音產物都寫進暫存資料夾（``data_dir``），任務寫進測試的 sqlite。結束時先等
    任務跑完，再換回執行模式與資料庫：任務的取消檢查與收尾還會用到它們。
    """
    with api_client(test_engine) as client:
        yield client
    in_process_run_mode.close(wait=True)


@pytest.fixture
def log_file(tmp_path):
    """像免安裝模式啟動時一樣把 log 寫進日誌檔（#231 Q5），放在暫存資料夾的 logs；回傳讀出全部內容的函式。"""
    from app.utils.logger import start_log_file, stop_log_file

    folder = tmp_path / "logs"
    start_log_file(folder)
    yield lambda: "".join(path.read_text(encoding="utf-8") for path in sorted(folder.iterdir()))
    stop_log_file()


@pytest.fixture
def saved_prompt_template(db_session):
    """設定頁存的提示詞範本：``saved_prompt_template(供應商, 範本)`` 直接寫進資料庫，像使用者先前在
    設定頁存好的；測試結束後還原（原本沒有這個供應商的設定列就刪掉）。"""
    from app.database.models import ModelConfiguration

    saved = []

    def save(provider: str, template: str) -> None:
        row = db_session.get(ModelConfiguration, provider)
        if row is None:
            row = ModelConfiguration(provider=provider)
            db_session.add(row)
            saved.append((row, None, True))
        else:
            saved.append((row, row.prompt, False))
        row.prompt = template
        db_session.commit()

    yield save
    for row, prompt, created in reversed(saved):
        if created:
            db_session.delete(row)
        else:
            row.prompt = prompt
    db_session.commit()
