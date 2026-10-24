"""保留音檔：成功給校正介面重播，失敗／取消留給再開任務與診斷。

暫時錯誤重試時從保留區找回輸入音檔，這條路徑透過 API 測試
（tests/integration/test_provider_seam.py 的暫時錯誤）。
"""
import os
import time

import pytest

from app.services import audio_store

TASK_UUID = "3f2a1b4c-0000-4000-8000-000000000001"


class _StubSettings:
    retain_audio = True
    audio_retention_days = 30
    temp_uploads_max_age_hours = 24


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把 audio_store 指向 tmp_path、temp_uploads 指向 tmp_path/uploads，並用假設定避開 .env 影響。"""
    settings = _StubSettings()
    settings.temp_uploads_path = tmp_path / "uploads"
    monkeypatch.setattr(audio_store, "store_path", lambda: tmp_path)
    monkeypatch.setattr(audio_store, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def upload(tmp_path):
    """模擬 temp_uploads 裡的上傳檔。"""
    src = tmp_path / "uploads"
    src.mkdir()
    path = src / "meeting.M4A"
    path.write_bytes(b"audio-bytes")
    return path


class TestRetain:
    def test_moves_file_and_returns_name(self, store, upload, tmp_path):
        name = audio_store.retain(upload, TASK_UUID)
        # 副檔名一律小寫，之後的 fallback 查找才對得上
        assert name == f"{TASK_UUID}.m4a"
        assert not upload.exists()
        assert (tmp_path / name).read_bytes() == b"audio-bytes"

    def test_already_retained_is_noop(self, store, upload, tmp_path):
        name = audio_store.retain(upload, TASK_UUID)
        again = audio_store.retain(tmp_path / name, TASK_UUID)
        assert again == name
        assert (tmp_path / name).read_bytes() == b"audio-bytes"

    def test_disabled_keeps_file_in_place(self, store, upload):
        store.retain_audio = False
        assert audio_store.retain(upload, TASK_UUID) is None
        assert upload.exists()

    def test_missing_source_returns_none(self, store, tmp_path):
        assert audio_store.retain(tmp_path / "gone.m4a", TASK_UUID) is None


class TestRetainSourceGuard:
    """retain() 只搬 temp_uploads 內的檔案；其他來源一律不動。"""

    @pytest.fixture
    def outside(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        path = elsewhere / "secret.m4a"
        path.write_bytes(b"not-an-upload")
        return path

    @pytest.fixture
    def warnings(self, monkeypatch):
        messages = []
        monkeypatch.setattr(audio_store.logger, "warning", messages.append)
        return messages

    def test_refuses_file_outside_temp_uploads(self, store, outside, tmp_path, warnings):
        assert audio_store.retain(outside, TASK_UUID) is None
        assert outside.read_bytes() == b"not-an-upload"
        assert not (tmp_path / f"{TASK_UUID}.m4a").exists()
        assert any("temp_uploads" in m for m in warnings)

    def test_refuses_dotdot_escape_from_temp_uploads(self, store, upload, outside, tmp_path):
        """字面上以 temp_uploads 開頭、實際落在外面的路徑也不能搬。"""
        sneaky = upload.parent / ".." / "elsewhere" / outside.name
        assert audio_store.retain(sneaky, TASK_UUID) is None
        assert outside.exists()
        assert not (tmp_path / f"{TASK_UUID}.m4a").exists()

    def test_retry_with_retained_file_still_works(self, store, upload, tmp_path, warnings):
        """重試時來源本身就是 audio_store 裡的保留檔：照舊回傳檔名，不警告。"""
        name = audio_store.retain(upload, TASK_UUID)
        assert audio_store.retain(tmp_path / name, TASK_UUID) == name
        assert (tmp_path / name).read_bytes() == b"audio-bytes"
        assert warnings == []


class TestResolveAndDelete:
    def test_rejects_path_separators(self, store, tmp_path):
        (tmp_path / "keep.m4a").write_bytes(b"x")
        assert audio_store.resolve("../keep.m4a") is None
        assert audio_store.resolve("sub/keep.m4a") is None

    def test_delete_removes_file(self, store, upload, tmp_path):
        name = audio_store.retain(upload, TASK_UUID)
        assert audio_store.delete(name) is True
        assert not (tmp_path / name).exists()
        # 已不存在時回傳 False 而不是拋錯
        assert audio_store.delete(name) is False


class TestPurgeExpired:
    def test_removes_only_expired(self, store, tmp_path):
        old = tmp_path / "old.m4a"
        new = tmp_path / "new.m4a"
        old.write_bytes(b"x")
        new.write_bytes(b"x")
        aged = time.time() - 31 * 86400
        os.utime(old, (aged, aged))

        assert audio_store.purge_expired() == 1
        assert not old.exists() and new.exists()

    def test_zero_days_disables_purge(self, store, tmp_path):
        store.audio_retention_days = 0
        old = tmp_path / "old.m4a"
        old.write_bytes(b"x")
        aged = time.time() - 999 * 86400
        os.utime(old, (aged, aged))

        assert audio_store.purge_expired() == 0
        assert old.exists()


class TestPurgeStaleUploads:
    """啟動清掃：沒機會收尾的任務（例如應用程式被直接關掉時還在排隊）留在暫存區的上傳檔。"""

    def test_removes_only_files_older_than_the_limit(self, store, upload):
        fresh = upload.parent / "fresh.wav"
        fresh.write_bytes(b"x")
        aged = time.time() - 25 * 3600
        os.utime(upload, (aged, aged))

        assert audio_store.purge_stale_uploads() == 1
        assert not upload.exists() and fresh.exists()

    def test_zero_hours_disables_the_sweep(self, store, upload):
        store.temp_uploads_max_age_hours = 0
        aged = time.time() - 999 * 3600
        os.utime(upload, (aged, aged))

        assert audio_store.purge_stale_uploads() == 0
        assert upload.exists()
