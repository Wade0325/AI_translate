"""LocalExecutor（standalone 行程內任務執行器）單元測試。"""
import threading
import time

import pytest

from app.runtime.executor import (
    FAILURE,
    LocalExecutor,
    REVOKED,
    SUCCESS,
)


class TransientError(Exception):
    pass


@pytest.fixture
def executor():
    ex = LocalExecutor(default_concurrency=2)
    yield ex
    ex.shutdown()


def test_submit_runs_and_reports_success(executor):
    done = threading.Event()
    results = []

    def work(value):
        results.append(value)
        done.set()
        return value

    executor.submit(work, args=("ok",), task_id="t1")
    assert done.wait(5)
    # 等 wrapper 寫入結束狀態
    for _ in range(50):
        if executor.state("t1") == SUCCESS:
            break
        time.sleep(0.05)
    assert executor.state("t1") == SUCCESS
    assert results == ["ok"]
    assert executor.is_alive("t1") is False


def test_local_asr_queue_is_serialized(executor):
    """local_asr 佇列 max_workers=1：任務不可並發（對齊 GPU worker solo -c 1）。"""
    running = []
    max_parallel = []
    lock = threading.Lock()

    def work(_):
        with lock:
            running.append(1)
            max_parallel.append(len(running))
        time.sleep(0.1)
        with lock:
            running.pop()

    for i in range(2):
        executor.submit(work, args=(i,), task_id=f"gpu-{i}", queue="local_asr")

    deadline = time.time() + 5
    while time.time() < deadline:
        if all(executor.state(f"gpu-{i}") == SUCCESS for i in range(2)):
            break
        time.sleep(0.05)
    assert max(max_parallel) == 1


def test_retry_on_transient_error(executor, monkeypatch):
    monkeypatch.setattr("app.runtime.executor.time.sleep", lambda _: None)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise TransientError("boom")
        return "recovered"

    executor.submit(
        flaky, task_id="t-retry", retry_on=(TransientError,), max_retries=3)

    deadline = time.time() + 5
    while time.time() < deadline and executor.state("t-retry") not in (SUCCESS, FAILURE):
        time.sleep(0.05)
    assert executor.state("t-retry") == SUCCESS
    assert len(attempts) == 3


def test_retry_exhausted_marks_failure(executor, monkeypatch):
    monkeypatch.setattr("app.runtime.executor.time.sleep", lambda _: None)

    def always_fail():
        raise TransientError("boom")

    executor.submit(
        always_fail, task_id="t-fail", retry_on=(TransientError,), max_retries=2)

    deadline = time.time() + 5
    while time.time() < deadline and executor.state("t-fail") != FAILURE:
        time.sleep(0.05)
    assert executor.state("t-fail") == FAILURE
    assert executor.is_alive("t-fail") is False


def test_revoke_before_start_skips_execution(executor):
    blocker_release = threading.Event()
    ran = []

    def blocker():
        blocker_release.wait(5)

    def victim():
        ran.append(1)

    # local_asr 只有一個 worker：blocker 佔住後 victim 停在佇列中
    executor.submit(blocker, task_id="blocker", queue="local_asr")
    executor.submit(victim, task_id="victim", queue="local_asr")
    executor.revoke("victim")
    blocker_release.set()

    deadline = time.time() + 5
    while time.time() < deadline and executor.state("blocker") != SUCCESS:
        time.sleep(0.05)
    time.sleep(0.2)
    assert ran == []
    assert executor.state("victim") == REVOKED
    assert executor.is_alive("victim") is False


def test_unknown_task_id_is_not_alive(executor):
    assert executor.is_alive("nope") is False
    assert executor.state("nope") is None
