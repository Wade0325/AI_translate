"""執行模式的選擇：依設定選一次轉接器，測試不必 reload 模組。"""
import pytest

from app.core.config import Settings
from app.runtime import run_mode
from app.runtime.celery_redis import CeleryRedisRunMode
from app.runtime.in_process import InProcessRunMode


@pytest.fixture
def restore_current():
    previous = run_mode.use(None)
    yield
    run_mode.close()
    run_mode.use(previous)


def test_standalone_selects_in_process(tmp_path):
    mode = run_mode.select(Settings(_env_file=None, app_mode="standalone",
                                    data_dir=str(tmp_path)))
    try:
        assert isinstance(mode, InProcessRunMode)
    finally:
        mode.close()


def test_docker_selects_celery_redis():
    mode = run_mode.select(Settings(_env_file=None, app_mode="docker"))
    try:
        assert isinstance(mode, CeleryRedisRunMode)
    finally:
        mode.close()


def test_get_selects_once(restore_current):
    first = run_mode.get()
    assert run_mode.get() is first


def test_use_swaps_the_current_mode(restore_current):
    mode = InProcessRunMode(concurrency=1)
    run_mode.use(mode)
    assert run_mode.get() is mode
