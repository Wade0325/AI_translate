"""standalone 模式的 in-memory 取消旗標測試。

cancellation 模組在 import 時依 APP_MODE 選擇實作，
因此以 reload 切到 standalone 分支測試，結束後還原 docker 分支。
"""
import importlib

import pytest


@pytest.fixture
def standalone_cancellation(monkeypatch):
    monkeypatch.setenv("APP_MODE", "standalone")
    from app.core.config import get_settings
    get_settings.cache_clear()

    import app.celery.cancellation as cancellation
    importlib.reload(cancellation)
    assert get_settings().is_standalone

    yield cancellation

    monkeypatch.delenv("APP_MODE")
    get_settings.cache_clear()
    importlib.reload(cancellation)


def test_cancel_flag_lifecycle(standalone_cancellation):
    c = standalone_cancellation
    assert c.is_cancel_requested("f1") is False
    c.request_cancel("f1")
    assert c.is_cancel_requested("f1") is True
    # 其他檔案不受影響
    assert c.is_cancel_requested("f2") is False
    c.clear_cancel_flag("f1")
    assert c.is_cancel_requested("f1") is False
    # 重複清除不報錯
    c.clear_cancel_flag("f1")


def test_task_id_registry(standalone_cancellation):
    c = standalone_cancellation
    assert c.get_task_id("f1") is None
    c.register_task_id("f1", "task-a")
    assert c.get_task_id("f1") == "task-a"
    # 重跑同一檔案時覆蓋
    c.register_task_id("f1", "task-b")
    assert c.get_task_id("f1") == "task-b"
