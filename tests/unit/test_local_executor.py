"""LocalExecutor（免安裝模式的行程內任務執行器）單元測試。"""
import threading
import time

import pytest

from app.runtime.executor import (
    LocalExecutor,
    REVOKED,
    SUCCESS,
)


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


@pytest.mark.parametrize("ends_with", [RuntimeError("503"), None],
                         ids=["ended-with-an-error", "stopped-by-itself"])
def test_revoking_a_started_task_lets_it_finish(executor, ends_with):
    """開始之後才撤銷：執行緒不可 kill，照常跑完（任務自己看取消旗標停下、收尾），不另外收尾；
    結束得了錯也不重試。"""
    attempts, alive, abandoned = [], [], []

    def cancelled_while_running():
        attempts.append(1)
        executor.revoke("t-started")  # 使用者在執行途中取消
        alive.append(executor.is_alive("t-started"))
        if ends_with is not None:
            raise ends_with
        return "任務看到取消、自己收尾"

    executor.submit(cancelled_while_running, task_id="t-started", on_abandoned=abandoned.append)

    deadline = time.time() + 5
    while time.time() < deadline and executor.is_alive("t-started"):
        time.sleep(0.05)
    assert len(attempts) == 1
    assert alive == [True]  # 跑完之前都還算存活
    assert abandoned == []
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
