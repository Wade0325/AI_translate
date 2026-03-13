"""
整合測試：歷史紀錄 API
測試範圍：
  GET    /api/v1/history/stats
  GET    /api/v1/history
  GET    /api/v1/history/{task_uuid}
  DELETE /api/v1/history/{task_uuid}
"""
import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog


# ─── 測試資料輔助函數 ─────────────────────────────────────────────────────────

def _create_log(db: Session, **kwargs) -> TranscriptionLog:
    """在資料庫中建立一筆測試用的 TranscriptionLog。"""
    defaults = {
        "task_uuid": uuid.uuid4(),
        "status": "COMPLETED",
        "original_filename": "test_audio.m4a",
        "audio_duration_seconds": 60.0,
        "processing_time_seconds": 10.0,
        "model_used": "gemini-2.5-flash",
        "provider": "Google",
        "source_language": "ja-JP",
        "target_language": None,
        "total_tokens": 5000,
        "cost": 0.005,
        "is_batch": False,
    }
    defaults.update(kwargs)
    log = TranscriptionLog(**defaults)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ─── 統計 API ─────────────────────────────────────────────────────────────────

class TestHistoryStats:
    def test_stats_returns_200(self, client: TestClient):
        response = client.get("/api/v1/history/stats")
        assert response.status_code == 200

    def test_stats_has_required_fields(self, client: TestClient):
        response = client.get("/api/v1/history/stats")
        data = response.json()
        required_fields = [
            "total_tasks", "completed_tasks", "failed_tasks",
            "success_rate", "total_cost", "total_tokens",
            "total_audio_duration_seconds", "avg_processing_time_seconds",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_stats_numeric_fields_non_negative(self, client: TestClient):
        response = client.get("/api/v1/history/stats")
        data = response.json()
        assert data["total_tasks"] >= 0
        assert data["completed_tasks"] >= 0
        assert data["failed_tasks"] >= 0
        assert data["success_rate"] >= 0
        assert data["total_cost"] >= 0


# ─── 分頁查詢 API ─────────────────────────────────────────────────────────────

class TestHistoryList:
    def test_empty_history_returns_200(self, client: TestClient):
        response = client.get("/api/v1/history")
        assert response.status_code == 200

    def test_history_response_structure(self, client: TestClient):
        response = client.get("/api/v1/history")
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data

    def test_default_pagination(self, client: TestClient):
        """預設應回傳第 1 頁，每頁 20 筆"""
        response = client.get("/api/v1/history")
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_custom_pagination(self, client: TestClient):
        response = client.get("/api/v1/history?page=2&page_size=5")
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 5

    def test_page_size_must_be_at_least_1(self, client: TestClient):
        response = client.get("/api/v1/history?page_size=0")
        assert response.status_code == 422

    def test_page_must_be_at_least_1(self, client: TestClient):
        response = client.get("/api/v1/history?page=0")
        assert response.status_code == 422

    def test_page_size_max_100(self, client: TestClient):
        response = client.get("/api/v1/history?page_size=101")
        assert response.status_code == 422

    def test_filter_by_status_completed(self, client: TestClient, db_session: Session):
        """status 篩選應只回傳指定狀態的紀錄"""
        _create_log(db_session, status="COMPLETED", original_filename="completed.mp3")
        _create_log(db_session, status="FAILED", original_filename="failed.mp3")

        response = client.get("/api/v1/history?status=COMPLETED")
        data = response.json()
        for item in data["items"]:
            assert item["status"] == "COMPLETED"

    def test_filter_by_status_failed(self, client: TestClient, db_session: Session):
        _create_log(db_session, status="FAILED", original_filename="err.mp3")
        response = client.get("/api/v1/history?status=FAILED")
        data = response.json()
        for item in data["items"]:
            assert item["status"] == "FAILED"

    def test_filter_by_is_batch_false(self, client: TestClient, db_session: Session):
        _create_log(db_session, is_batch=False, original_filename="single.mp3")
        _create_log(db_session, is_batch=True, original_filename="batch.mp3",
                    batch_id="batch-001")
        response = client.get("/api/v1/history?is_batch=false")
        data = response.json()
        for item in data["items"]:
            assert item.get("is_batch") is False or item.get("is_batch") is None

    def test_keyword_search_by_filename(self, client: TestClient, db_session: Session):
        _create_log(db_session, original_filename="unique_keyword_xyzabc.mp3")
        response = client.get("/api/v1/history?keyword=unique_keyword_xyzabc")
        data = response.json()
        assert data["total"] >= 1
        filenames = [item["original_filename"] for item in data["items"]]
        assert any("unique_keyword_xyzabc" in fn for fn in filenames)

    def test_keyword_no_match_returns_empty(self, client: TestClient):
        response = client.get("/api/v1/history?keyword=IMPOSSIBLE_MATCH_ZZZZZ9999")
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_items_is_list(self, client: TestClient):
        response = client.get("/api/v1/history")
        data = response.json()
        assert isinstance(data["items"], list)

    def test_total_pages_calculation(self, client: TestClient, db_session: Session):
        """建立 5 筆紀錄，每頁 2 筆，應有 3 頁"""
        for i in range(5):
            _create_log(db_session, original_filename=f"pages_test_{i}.mp3",
                       task_uuid=uuid.uuid4())

        response = client.get("/api/v1/history?page_size=2")
        data = response.json()
        assert data["total_pages"] >= 3


# ─── 查詢單筆紀錄 ─────────────────────────────────────────────────────────────

class TestHistoryDetail:
    def test_get_existing_log(self, client: TestClient, db_session: Session):
        """取得已存在的紀錄應回傳完整資料"""
        log = _create_log(db_session, original_filename="detail_test.mp3")
        task_uuid = str(log.task_uuid)

        response = client.get(f"/api/v1/history/{task_uuid}")
        assert response.status_code == 200
        data = response.json()
        assert data["task_uuid"] == task_uuid
        assert data["original_filename"] == "detail_test.mp3"
        assert data["status"] == "COMPLETED"

    def test_get_nonexistent_log_returns_404(self, client: TestClient):
        """取得不存在的紀錄應回傳 404"""
        fake_uuid = str(uuid.uuid4())
        response = client.get(f"/api/v1/history/{fake_uuid}")
        assert response.status_code == 404

    def test_response_contains_model_used(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, model_used="gemini-2.5-flash")
        response = client.get(f"/api/v1/history/{log.task_uuid}")
        data = response.json()
        assert data["model_used"] == "gemini-2.5-flash"

    def test_response_contains_cost(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, cost=0.00123)
        response = client.get(f"/api/v1/history/{log.task_uuid}")
        data = response.json()
        assert abs(data["cost"] - 0.00123) < 1e-6

    def test_response_contains_audio_duration(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, audio_duration_seconds=180.5)
        response = client.get(f"/api/v1/history/{log.task_uuid}")
        data = response.json()
        assert abs(data["audio_duration_seconds"] - 180.5) < 0.01


# ─── 刪除紀錄 ─────────────────────────────────────────────────────────────────

class TestHistoryDelete:
    def test_delete_existing_log(self, client: TestClient, db_session: Session):
        """刪除已存在的紀錄應回傳 success=True"""
        log = _create_log(db_session, original_filename="to_delete.mp3")
        task_uuid = str(log.task_uuid)

        response = client.delete(f"/api/v1/history/{task_uuid}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_delete_nonexistent_log_returns_404(self, client: TestClient):
        """刪除不存在的紀錄應回傳 404"""
        fake_uuid = str(uuid.uuid4())
        response = client.delete(f"/api/v1/history/{fake_uuid}")
        assert response.status_code == 404

    def test_delete_then_get_returns_404(self, client: TestClient, db_session: Session):
        """刪除後再查詢應回傳 404"""
        log = _create_log(db_session, original_filename="delete_then_get.mp3")
        task_uuid = str(log.task_uuid)

        client.delete(f"/api/v1/history/{task_uuid}")
        response = client.get(f"/api/v1/history/{task_uuid}")
        assert response.status_code == 404

    def test_delete_reduces_total_count(self, client: TestClient, db_session: Session):
        """刪除後統計數量應減少"""
        log = _create_log(db_session, original_filename="count_test.mp3")
        task_uuid = str(log.task_uuid)

        before = client.get("/api/v1/history").json()["total"]
        client.delete(f"/api/v1/history/{task_uuid}")
        after = client.get("/api/v1/history").json()["total"]
        assert after == before - 1
