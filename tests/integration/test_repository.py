"""
整合測試：Repository 層
測試範圍：
  ModelSettingsRepository  — model_manager_repository.py
  HistoryRepository        — history_repository.py
使用 SQLite 測試資料庫（tests/conftest.py 的 test_engine），透過 db_session fixture 確保每個測試後回滾。
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import TranscriptionLog
from app.repositories.model_manager_repository import ModelSettingsRepository
from app.repositories.history_repository import HistoryRepository
from app.schemas.schemas import ModelConfigurationSchema


# ─── 輔助函數 ────────────────────────────────────────────────────────────────

def _create_transcription_log(db: Session, **kwargs) -> TranscriptionLog:
    defaults = {
        "task_uuid": uuid.uuid4(),
        "status": "COMPLETED",
        "original_filename": "audio.m4a",
        "audio_duration_seconds": 60.0,
        "processing_time_seconds": 10.0,
        "model_used": "gemini-2.5-flash",
        "provider": "Google",
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


@pytest.fixture
def empty_db(tmp_path):
    """只給一個測試用的空資料庫：共用的測試資料庫留著別的測試 commit 的紀錄，算不出確切的統計。"""
    from app.database.models import Base
    from app.database.session import _create_engine

    engine = _create_engine(f"sqlite:///{(tmp_path / 'stats.db').as_posix()}")
    Base.metadata.create_all(bind=engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


# ─── ModelSettingsRepository ─────────────────────────────────────────────────

class TestModelSettingsRepository:
    def setup_method(self):
        self.repo = ModelSettingsRepository()

    def test_save_new_config(self, db_session: Session):
        """儲存新設定應能在資料庫中查到"""
        schema = ModelConfigurationSchema(
            provider="TestSaveProvider",
            api_keys='["key1", "key2"]',
            model="gemini-2.5-flash",
            prompt="Test prompt",
        )
        result = self.repo.save(db_session, schema)
        assert result.provider == "TestSaveProvider"
        assert result.model == "gemini-2.5-flash"

    def test_get_by_name_existing(self, db_session: Session):
        """get_by_name 應回傳已存在的設定"""
        schema = ModelConfigurationSchema(
            provider="TestGetProvider",
            api_keys='["key"]',
            model="test-model",
        )
        self.repo.save(db_session, schema)
        result = self.repo.get_by_name(db_session, "TestGetProvider")
        assert result is not None
        assert result.provider == "TestGetProvider"
        assert result.model == "test-model"

    def test_get_by_name_nonexistent_returns_none(self, db_session: Session):
        """不存在的 provider 應回傳 None"""
        result = self.repo.get_by_name(db_session, "NonExistentXYZ999")
        assert result is None

    def test_update_existing_config(self, db_session: Session):
        """重複儲存相同 provider 應更新現有記錄"""
        initial = ModelConfigurationSchema(
            provider="TestUpdateRepo",
            api_keys='["old_key"]',
            model="old-model",
        )
        self.repo.save(db_session, initial)

        updated = ModelConfigurationSchema(
            provider="TestUpdateRepo",
            api_keys='["new_key"]',
            model="new-model",
            prompt="Updated prompt",
        )
        self.repo.save(db_session, updated)

        result = self.repo.get_by_name(db_session, "TestUpdateRepo")
        assert result.model == "new-model"
        assert result.prompt == "Updated prompt"

    def test_save_with_null_prompt(self, db_session: Session):
        """prompt 可以為 None"""
        schema = ModelConfigurationSchema(
            provider="TestNullPrompt",
            api_keys='["k"]',
            model="m",
            prompt=None,
        )
        result = self.repo.save(db_session, schema)
        assert result.prompt is None

    def test_save_returns_model_configuration_schema(self, db_session: Session):
        """save 應回傳 ModelConfigurationSchema"""
        schema = ModelConfigurationSchema(
            provider="TestReturnType",
            api_keys='["k"]',
            model="m",
        )
        result = self.repo.save(db_session, schema)
        assert isinstance(result, ModelConfigurationSchema)


# ─── HistoryRepository ────────────────────────────────────────────────────────

class TestHistoryRepository:
    def setup_method(self):
        self.repo = HistoryRepository()

    def test_get_log_by_uuid_existing(self, db_session: Session):
        """get_log_by_uuid 應回傳對應的紀錄（傳入 UUID 物件）"""
        log = _create_transcription_log(db_session, original_filename="repo_uuid_test.mp3")
        result = self.repo.get_log_by_uuid(db_session, log.task_uuid)
        assert result is not None
        assert str(result.task_uuid) == str(log.task_uuid)

    def test_get_log_by_uuid_with_string(self, db_session: Session):
        """get_log_by_uuid 應同時支援字串 UUID"""
        log = _create_transcription_log(db_session, original_filename="repo_uuid_str_test.mp3")
        result = self.repo.get_log_by_uuid(db_session, str(log.task_uuid))
        assert result is not None

    def test_get_log_by_uuid_nonexistent_returns_none(self, db_session: Session):
        result = self.repo.get_log_by_uuid(db_session, uuid.uuid4())
        assert result is None

    def test_delete_log_existing(self, db_session: Session):
        """delete_log 應回傳 True 並真正刪除（傳入 UUID 物件）"""
        log = _create_transcription_log(db_session, original_filename="repo_del_test.mp3")
        result = self.repo.delete_log(db_session, log.task_uuid)
        assert result is True

        after = self.repo.get_log_by_uuid(db_session, log.task_uuid)
        assert after is None

    def test_delete_log_nonexistent_returns_false(self, db_session: Session):
        result = self.repo.delete_log(db_session, uuid.uuid4())
        assert result is False

    def test_get_logs_paginated_returns_tuple(self, db_session: Session):
        """get_logs_paginated 應回傳 (list, int) tuple"""
        logs, total = self.repo.get_logs_paginated(db_session)
        assert isinstance(logs, list)
        assert isinstance(total, int)

    def test_get_logs_paginated_respects_page_size(self, db_session: Session):
        """page_size 應限制回傳的筆數"""
        for i in range(5):
            _create_transcription_log(db_session, original_filename=f"ps_test_{i}.mp3")
        logs, total = self.repo.get_logs_paginated(db_session, page=1, page_size=2)
        assert len(logs) <= 2

    def test_get_logs_paginated_filter_by_status(self, db_session: Session):
        """status 篩選應只回傳對應狀態"""
        _create_transcription_log(db_session, status="COMPLETED",
                                  original_filename="filter_c.mp3")
        _create_transcription_log(db_session, status="FAILED",
                                  original_filename="filter_f.mp3")
        logs, total = self.repo.get_logs_paginated(db_session, status="COMPLETED")
        assert all(log.status == "COMPLETED" for log in logs)

    def test_get_logs_paginated_filter_by_is_batch(self, db_session: Session):
        _create_transcription_log(db_session, is_batch=True,
                                  original_filename="batch_f.mp3",
                                  batch_id="b-001")
        _create_transcription_log(db_session, is_batch=False,
                                  original_filename="single_f.mp3")
        logs, _ = self.repo.get_logs_paginated(db_session, is_batch=True)
        assert all(log.is_batch is True for log in logs)

    def test_get_logs_paginated_keyword_search(self, db_session: Session):
        _create_transcription_log(db_session, original_filename="special_kw_audio.mp3")
        logs, total = self.repo.get_logs_paginated(db_session, keyword="special_kw_audio")
        assert total >= 1
        assert any("special_kw_audio" in log.original_filename for log in logs)

    def test_get_logs_paginated_keyword_no_match(self, db_session: Session):
        logs, total = self.repo.get_logs_paginated(
            db_session, keyword="IMPOSSIBLE_KW_ZZZZ999"
        )
        assert total == 0

    def test_get_stats_structure(self, db_session: Session):
        """get_stats 應回傳所有必要欄位，且值型別正確"""
        stats = self.repo.get_stats(db_session)
        required_keys = [
            "total_tasks", "completed_tasks", "failed_tasks",
            "success_rate", "total_cost", "total_tokens",
            "total_audio_duration_seconds", "avg_processing_time_seconds",
        ]
        for key in required_keys:
            assert key in stats, f"Missing key: {key}"
        assert stats["total_tasks"] >= 0
        assert 0 <= stats["success_rate"] <= 100
        assert stats["total_cost"] >= 0

    def test_get_stats_with_data(self, db_session: Session):
        """有資料時統計應正確加總"""
        _create_transcription_log(
            db_session, status="COMPLETED", cost=0.001, total_tokens=1000,
            audio_duration_seconds=60.0, processing_time_seconds=10.0,
            original_filename="stats1.mp3",
        )
        _create_transcription_log(
            db_session, status="FAILED", cost=0.002, total_tokens=2000,
            audio_duration_seconds=30.0, processing_time_seconds=5.0,
            original_filename="stats2.mp3",
        )
        stats = self.repo.get_stats(db_session)
        assert stats["total_tasks"] >= 2
        assert stats["completed_tasks"] >= 1
        assert stats["failed_tasks"] >= 1
        assert stats["total_cost"] >= 0.001

    def test_success_rate_counts_only_finished_tasks(self, empty_db: Session):
        """成功率 = 完成 /（完成＋失敗）：處理中與已取消的任務沒有成敗，不算進分母（#18）"""
        for status in ["COMPLETED"] * 3 + ["FAILED", "PROCESSING", "CANCELLED", "CANCELLED"]:
            _create_transcription_log(empty_db, status=status)

        stats = self.repo.get_stats(empty_db)

        assert stats["total_tasks"] == 7
        assert stats["success_rate"] == 75.0

    def test_success_rate_is_zero_before_any_task_finishes(self, empty_db: Session):
        _create_transcription_log(empty_db, status="PROCESSING")

        assert self.repo.get_stats(empty_db)["success_rate"] == 0

    def test_get_logs_ordered_by_timestamp_desc(self, db_session: Session):
        """結果應依 request_timestamp 降序排列"""
        import time
        log1 = _create_transcription_log(db_session, original_filename="old.mp3")
        time.sleep(0.01)
        _create_transcription_log(db_session, original_filename="new.mp3")

        logs, _ = self.repo.get_logs_paginated(db_session, keyword="old.mp3")
        # 確認回傳結果中包含正確的紀錄
        uuids = [str(log.task_uuid) for log in logs]
        assert str(log1.task_uuid) in uuids

    def test_pagination_second_page(self, db_session: Session):
        """第二頁應回傳不同的紀錄"""
        for i in range(4):
            _create_transcription_log(db_session,
                                      original_filename=f"page_test_{i}.mp3",
                                      task_uuid=uuid.uuid4())
        page1_logs, _ = self.repo.get_logs_paginated(db_session, page=1, page_size=2)
        page2_logs, _ = self.repo.get_logs_paginated(db_session, page=2, page_size=2)
        page1_uuids = {str(log.task_uuid) for log in page1_logs}
        page2_uuids = {str(log.task_uuid) for log in page2_logs}
        # 兩頁的紀錄不應重疊
        assert len(page1_uuids & page2_uuids) == 0


class TestTranscriptionLogRepositoryStaleSweep:
    """mark_stale_processing_failed — 孤兒 PROCESSING 紀錄的啟動清掃"""

    def setup_method(self):
        from app.repositories.transcription_log_repository import TranscriptionLogRepository
        self.repo = TranscriptionLogRepository()

    def test_stale_processing_marked_failed(self, db_session: Session):
        """超過時限的單檔 PROCESSING 紀錄應標記為 FAILED 並附錯誤訊息"""
        stale = _create_transcription_log(
            db_session, status="PROCESSING",
            request_timestamp=datetime.now() - timedelta(hours=13))

        swept = self.repo.mark_stale_processing_failed(db_session, max_age_hours=12)

        assert swept == 1
        db_session.refresh(stale)
        assert stale.status == "FAILED"
        assert stale.error_message
        assert stale.completed_at is not None

    def test_recent_processing_untouched(self, db_session: Session):
        """未超過時限的 PROCESSING 紀錄不應被動到"""
        recent = _create_transcription_log(
            db_session, status="PROCESSING",
            request_timestamp=datetime.now() - timedelta(hours=1))

        swept = self.repo.mark_stale_processing_failed(db_session, max_age_hours=12)

        assert swept == 0
        db_session.refresh(recent)
        assert recent.status == "PROCESSING"

    def test_batch_processing_untouched(self, db_session: Session):
        """批次紀錄有自己的 recover 機制，不應被清掃"""
        batch = _create_transcription_log(
            db_session, status="PROCESSING", is_batch=True,
            request_timestamp=datetime.now() - timedelta(hours=48))

        swept = self.repo.mark_stale_processing_failed(db_session, max_age_hours=12)

        assert swept == 0
        db_session.refresh(batch)
        assert batch.status == "PROCESSING"

    def test_completed_untouched(self, db_session: Session):
        """已完成的舊紀錄不應被清掃"""
        done = _create_transcription_log(
            db_session, status="COMPLETED",
            request_timestamp=datetime.now() - timedelta(hours=48))

        swept = self.repo.mark_stale_processing_failed(db_session, max_age_hours=12)

        assert swept == 0
        db_session.refresh(done)
        assert done.status == "COMPLETED"

    def test_null_is_batch_treated_as_single_file(self, db_session: Session):
        """is_batch 為 NULL 的舊紀錄應視為單檔、納入清掃"""
        legacy = _create_transcription_log(
            db_session, status="PROCESSING", is_batch=None,
            request_timestamp=datetime.now() - timedelta(hours=13))

        swept = self.repo.mark_stale_processing_failed(db_session, max_age_hours=12)

        assert swept == 1
        db_session.refresh(legacy)
        assert legacy.status == "FAILED"

class TestTranscriptionLogRepositoryFinishing:
    """任務收尾的條件式更新：已經結束的紀錄不再改寫；狀態一律從資料庫讀。"""

    def setup_method(self):
        from app.repositories.transcription_log_repository import TranscriptionLogRepository
        self.repo = TranscriptionLogRepository()

    def test_finished_record_is_not_overwritten(self, db_session: Session):
        log = _create_transcription_log(db_session, status="CANCELLED")

        assert self.repo.update_log_if_processing(
            db_session, log.task_uuid, {"status": "COMPLETED"}) is False
        assert self.repo.current_status(db_session, log.task_uuid) == "CANCELLED"

    def test_status_is_read_from_the_database_not_the_session(
            self, db_session: Session, test_engine):
        # 任務的 session 已經載入這筆紀錄；取消端點用另一個 session 把它改成已取消
        log = _create_transcription_log(db_session, status="PROCESSING")
        with sessionmaker(bind=test_engine)() as endpoint:
            assert self.repo.mark_cancelled_if_processing(endpoint, log.task_uuid)

        assert self.repo.current_status(db_session, log.task_uuid) == "CANCELLED"
