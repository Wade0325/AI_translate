"""音檔保留：成功給校正介面重播，失敗／取消留給重跑與診斷。

重點是重試路徑：上一輪的 finally 已把檔案搬離 temp_uploads，
``resolve_input_path`` 沒有 fallback 的話，重試必定以「檔案不存在」收場。
"""
import os
import time
import uuid

import pytest

from app.services import audio_store
from app.tasks.transcribe_core import resolve_input_path

TASK_UUID = "3f2a1b4c-0000-4000-8000-000000000001"


class _StubSettings:
    retain_audio = True
    audio_retention_days = 30


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把 audio_store 指向 tmp_path，並用假設定避開 .env 影響。"""
    settings = _StubSettings()
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


class TestResolveInputPath:
    def test_prefers_existing_upload(self, store, upload):
        assert resolve_input_path(str(upload), TASK_UUID) == upload

    def test_falls_back_to_retained_file(self, store, upload, tmp_path):
        name = audio_store.retain(upload, TASK_UUID)
        # 重試時 file_path 仍指向已被搬走的 temp_uploads 路徑
        assert resolve_input_path(str(upload), TASK_UUID) == tmp_path / name

    def test_returns_original_when_nothing_found(self, store, upload):
        upload.unlink()
        assert resolve_input_path(str(upload), TASK_UUID) == upload

    def test_other_task_uuid_does_not_match(self, store, upload):
        audio_store.retain(upload, TASK_UUID)
        other = str(uuid.uuid4())
        assert resolve_input_path(str(upload), other) == upload


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
