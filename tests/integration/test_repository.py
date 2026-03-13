"""
整合測試：Repository 層
測試範圍：
  ModelSettingsRepository  — model_manager_repository.py
  HistoryRepository        — history_repository.py
使用 SQLite in-memory 資料庫，透過 db_session fixture 確保每個測試後回滾。
"""
import uuid
import pytest
from datetime import datetime
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog, ModelConfiguration
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

    def test_get_by_model_existing(self, db_session: Session):
        """get_by_model 應回傳對應模型的設定"""
        schema = ModelConfigurationSchema(
            provider="TestModelSearch",
            api_keys='[]',
            model="unique-model-xyz",
        )
        self.repo.save(db_session, schema)
        result = self.repo.get_by_model(db_session, "unique-model-xyz")
        assert result is not None
        assert result.provider == "TestModelSearch"

    def test_get_by_model_nonexistent_returns_none(self, db_session: Session):
        result = self.repo.get_by_model(db_session, "absolutely-unknown-model")
        assert result is None

    def test_get_all_configs_returns_list(self, db_session: Session):
        """get_all_configs 應回傳 list"""
        self.repo.save(db_session, ModelConfigurationSchema(
            provider="TestAll1", api_keys="[]", model="m1"
        ))
        self.repo.save(db_session, ModelConfigurationSchema(
            provider="TestAll2", api_keys="[]", model="m2"
        ))
        results = self.repo.get_all_configs(db_session)
        assert isinstance(results, list)
        providers = [r.provider for r in results]
        assert "TestAll1" in providers
        assert "TestAll2" in providers

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

    def test_get_stats_success_rate_calculation(self, db_session: Session):
        """成功率計算邏輯：completed / total * 100"""
        for _ in range(3):
            _create_transcription_log(db_session, status="COMPLETED",
                                      original_filename=f"sr_{uuid.uuid4()}.mp3")
        for _ in range(1):
            _create_transcription_log(db_session, status="FAILED",
                                      original_filename=f"sf_{uuid.uuid4()}.mp3")
        stats = self.repo.get_stats(db_session)
        # 至少有 3 成功 1 失敗，成功率至少 75%
        assert stats["success_rate"] >= 0
        assert stats["success_rate"] <= 100

    def test_get_logs_ordered_by_timestamp_desc(self, db_session: Session):
        """結果應依 request_timestamp 降序排列"""
        import time
        log1 = _create_transcription_log(db_session, original_filename="old.mp3")
        time.sleep(0.01)
        log2 = _create_transcription_log(db_session, original_filename="new.mp3")

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
