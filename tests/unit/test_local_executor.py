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
    abandoned = []

    def blocker():
        blocker_release.wait(5)

    def victim():
        ran.append(1)

    # local_asr 只有一個 worker：blocker 佔住後 victim 停在佇列中
    executor.submit(blocker, task_id="blocker", queue="local_asr")
    executor.submit(victim, task_id="victim", queue="local_asr", on_abandoned=abandoned.append)
    executor.revoke("victim")
    blocker_release.set()

    deadline = time.time() + 5
    while time.time() < deadline and executor.state("blocker") != SUCCESS:
        time.sleep(0.05)
    time.sleep(0.2)
    assert ran == []
    assert executor.state("victim") == REVOKED
    assert executor.is_alive("victim") is False
    # 不執行的任務照樣收尾：被撤銷的收尾只呼叫一次
    assert abandoned == [True]


@pytest.mark.parametrize("ends_with, abandoned_with", [
    (TransientError("503"), [True]),
    (None, []),
], ids=["transient-error", "stopped-by-itself"])
def test_revoking_a_started_task_lets_this_attempt_finish_without_retrying(
        executor, monkeypatch, ends_with, abandoned_with):
    """開始之後才撤銷：執行緒不可 kill，這一次照常跑完（任務自己看取消旗標停下、收尾）；
    這一次以暫時錯誤結束時不再重試，改呼叫收尾，和 Celery 丟掉被撤銷的重試一樣。"""
    monkeypatch.setattr("app.runtime.executor.time.sleep", lambda _: None)
    attempts, alive, abandoned = [], [], []

    def cancelled_while_running():
        attempts.append(1)
        executor.revoke("t-started")  # 使用者在執行途中取消
        alive.append(executor.is_alive("t-started"))
        if ends_with is not None:
            raise ends_with
        return "任務看到取消、自己收尾"

    executor.submit(cancelled_while_running, task_id="t-started", retry_on=(TransientError,),
                    on_abandoned=abandoned.append)

    deadline = time.time() + 5
    while time.time() < deadline and executor.is_alive("t-started"):
        time.sleep(0.05)
    assert len(attempts) == 1
    assert alive == [True]  # 這一次跑完之前都還算存活
    assert abandoned == abandoned_with
    assert executor.is_alive("t-started") is False


def test_shutdown_abandons_tasks_still_queued():
    executor = LocalExecutor(default_concurrency=1)
    release = threading.Event()
    abandoned = []
    executor.submit(lambda: release.wait(5), task_id="running", queue="local_asr",
                    on_abandoned=abandoned.append)
    executor.submit(lambda: None, task_id="queued", queue="local_asr",
                    on_abandoned=abandoned.append)
    deadline = time.time() + 5
    while time.time() < deadline and executor.state("running") != "STARTED":
        time.sleep(0.01)

    executor.shutdown()
    release.set()

    # 還在排隊的任務不再執行，以「不是被撤銷」收尾；執行中的照常跑完
    assert abandoned == [False]
    assert executor.is_alive("queued") is False


def test_unknown_task_id_is_not_alive(executor):
    assert executor.is_alive("nope") is False
    assert executor.state("nope") is None
