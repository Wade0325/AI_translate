"""接縫 1 的 Docker 模式組：透過 API 派送、撤銷、查存活，經 Celery＋Redis 執行模式（#128）。

Redis 換成 fakeredis；Celery 的 broker 與結果後端放記憶體，任務由測試行程裡的 Celery worker
（``celery.contrib.testing.worker``，solo pool）從佇列取出執行；供應商換成假供應商。其他和行程內
執行模式的接縫測試一樣走真的：TestClient、sqlite、WebSocket 狀態廣播與合成音檔。

不用 eager（``task_always_eager``）：eager 在派送的當下就把任務跑完，API 還沒登記任務、任務也從來
不在佇列裡，撤銷與存活查詢都測不到。這裡的任務和 Docker 模式一樣，派送之後才在 worker 執行。

worker 照 Docker 模式分開：單檔的本機任務只由消費 ``local_asr`` 的 worker（主機的 GPU worker，
``local_worker.bat``）執行，批次只由消費預設佇列的 worker（celery-worker 容器）執行；
佇列路由錯了，任務就沒有 worker 拿，測試等不到結果。
"""
import threading
from contextlib import contextmanager
from dataclasses import replace

import fakeredis
import fakeredis.aioredis
import pytest
from celery.result import AsyncResult

from app.core.task_status import TaskStatus
from app.provider.base import LOCAL_QUEUE
from app.runtime import run_mode
from app.runtime.celery_redis import CeleryRedisRunMode
from tests.support.api_client import api_client
from tests.support.fake_provider import FAKE_MODEL
from tests.support.task_api import listed, receive_until, upload
from tests.support.waiting import TIMEOUT, cancel_when_dispatched, wait_until

LINES = [(0.2, 1.5, 0, "おはよう。"), (2.3, 3.6, 1, "こんにちは。")]
TERMINAL = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def docker_run_mode():
    """Docker 模式的執行模式：Celery＋Redis 轉接器，Redis 換成 fakeredis。"""
    server = fakeredis.FakeServer()
    mode = CeleryRedisRunMode(
        fakeredis.FakeRedis(server=server),
        lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    previous = run_mode.use(mode)
    yield mode
    run_mode.use(previous)
    mode.close()


@pytest.fixture
def celery_app(monkeypatch):
    """broker 與結果後端放記憶體的 Celery app。

    預設的 broker 是 Redis、結果後端是 Postgres：測試不能連它們，也不能寫進開發者本機的資料庫。
    記憶體 broker 的佇列整個行程共用，前後各清一次，上一個測試留下的任務不會被下一個 worker 拿到。
    """
    from app.celery.celery import celery_app as app
    from app.core.config import get_settings

    assert not get_settings().is_standalone, "這裡測的是 Docker 模式"
    monkeypatch.setitem(app.conf, "broker_url", "memory://")
    monkeypatch.setitem(app.conf, "result_backend", "cache+memory://")
    # 記憶體 broker 預設每秒才看一次佇列，測試等不起
    monkeypatch.setitem(app.conf, "broker_transport_options",
                        {**app.conf.broker_transport_options, "polling_interval": 0.01})
    # worker 啟動時不接管 root logger：其他測試靠它看 log
    monkeypatch.setitem(app.conf, "worker_hijack_root_logger", False)
    # 之前照舊設定建立過的結果後端與連線池，換掉
    monkeypatch.delattr(app._local, "backend", raising=False)
    monkeypatch.setattr(app, "_pool", None)
    monkeypatch.setattr(app.amqp, "_producer_pool", None)
    _purge(app)
    yield app
    _purge(app)


def _purge(app) -> None:
    with app.connection_for_write() as connection:
        for queue in (app.conf.task_default_queue, LOCAL_QUEUE):
            connection.default_channel.queue_purge(queue)


@contextmanager
def worker(app, fake, queue: str):
    """只消費 ``queue`` 的 Celery worker。結束時先放行假供應商還停著的轉錄與查詢，worker 才停得下來。

    停下 worker 要約 4 秒（Celery 的同步迴圈每 2 秒才看一次停止旗標），所以情境併在少數幾個測試裡。
    """
    from celery.contrib.testing.worker import start_worker

    with start_worker(app, pool="solo", concurrency=1, perform_ping_check=False,
                      queues=[queue], loglevel="WARNING"):
        try:
            yield
        finally:
            for hold in (fake.hold, *fake.poll_holds):
                if hold is not None:
                    hold.set()


@pytest.fixture
def gpu_worker(celery_app, fake, docker_run_mode, task_db):
    """主機的 GPU worker：只消費本機的佇列（假供應商的模型能力也排在這裡）。"""
    assert fake.model_capabilities.queue == LOCAL_QUEUE
    with worker(celery_app, fake, LOCAL_QUEUE):
        yield


@pytest.fixture
def container_worker(celery_app, fake, docker_run_mode, task_db):
    """celery-worker 容器的 worker：只消費預設佇列（批次跑在這裡）。"""
    with worker(celery_app, fake, celery_app.conf.task_default_queue):
        yield


@pytest.fixture
def api(test_engine, data_dir, task_db, docker_run_mode, fake):
    """API 選 Docker 模式的執行模式：派送交給 Celery，狀態廣播從 Redis 收。"""
    with api_client(test_engine) as client:
        yield client


# ─── helpers ─────────────────────────────────────────────────────────────────

def submit(ws, filename: str) -> None:
    ws.send_json({"filename": filename, "original_filename": filename, "provider": "fake",
                  "model": FAKE_MODEL, "source_lang": "ja"})


def record(api, task_uuid: str) -> dict:
    return api.get(f"/api/v1/history/{task_uuid}").json()


def registered_task_id(mode, file_uid: str) -> str:
    wait_until(lambda: mode.registered_task(file_uid) is not None)
    return mode.registered_task(file_uid).task_id


def watching_task_id(db_session, batch_id: str) -> str:
    """批次紀錄上看著這個批次的任務（最後派出去的那一個）。"""
    from app.database.models import BatchJob

    db_session.expire_all()
    return db_session.query(BatchJob).filter_by(batch_id=batch_id).one().celery_task_id


# ─── 單檔任務 ────────────────────────────────────────────────────────────────

def test_a_single_file_task_completes_and_cancelling_it_afterwards_changes_nothing(
        api, fake, gpu_worker, docker_run_mode):
    fake.script = [list(LINES)]
    filename = upload(api)

    with api.websocket_connect("/api/v1/ws/uid-docker") as ws:
        submit(ws, filename)
        end = receive_until(ws, *TERMINAL)[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert "こんにちは。" in end["result"]["transcripts"]["srt"]
    assert len(fake.calls) == 1

    # 任務可能在 API 登記之前就跑完，登記會留著：取消端點問 Celery，查到已經結束就不撤銷
    response = api.post("/api/v1/transcription/uid-docker/cancel").json()

    assert response["cancelled"] is False
    assert response["reason"] in ("not-started", "finished")
    assert docker_run_mode.registered_task("uid-docker") is None
    assert record(api, end["task_uuid"])["status"] == TaskStatus.COMPLETED


def test_cancelling_a_running_task_stops_it_at_the_next_check(api, fake, gpu_worker):
    fake.script = [list(LINES)]
    fake.hold = threading.Event()
    filename = upload(api)

    with api.websocket_connect("/api/v1/ws/uid-docker-running") as ws:
        submit(ws, filename)
        assert fake.started.wait(TIMEOUT)
        # Celery 回報執行中（STARTED）：設取消旗標；本機的任務不強制終止，任務看到旗標自己停下
        assert cancel_when_dispatched(api, "uid-docker-running")["cancelled"] is True
        cancelled = receive_until(ws, TaskStatus.CANCELLED)[-1]

    wait_until(lambda: fake.cancelled == 1)
    wait_until(lambda: record(api, cancelled["task_uuid"]).get("status") == TaskStatus.CANCELLED)


def test_cancelling_a_queued_task_revokes_it_and_the_worker_discards_it(
        api, fake, gpu_worker, docker_run_mode, celery_app):
    # GPU worker 只有一個：第一個任務停在供應商時，第二個排在佇列裡
    fake.script = [list(LINES)]
    fake.hold = threading.Event()
    first, second = upload(api, "first.wav"), upload(api, "second.wav")
    with api.websocket_connect("/api/v1/ws/uid-docker-first") as ws:
        submit(ws, first)
        assert fake.started.wait(TIMEOUT)
    with api.websocket_connect("/api/v1/ws/uid-docker-queued") as ws:
        submit(ws, second)
        queued = registered_task_id(docker_run_mode, "uid-docker-queued")
        # Celery 查不出排隊中的任務在不在（PENDING）：當成還在佇列裡，撤銷它
        assert cancel_when_dispatched(api, "uid-docker-queued")["cancelled"] is True
        assert receive_until(ws, TaskStatus.CANCELLED)[-1]["status_code"] == TaskStatus.CANCELLED

    fake.hold.set()

    # worker 輪到它時直接丟掉、照樣收尾：Celery 記成已撤銷（不是開始之後看到取消旗標才停下），
    # 任務紀錄記成已取消，供應商只轉了第一個
    wait_until(lambda: AsyncResult(queued, app=celery_app).state == "REVOKED")
    wait_until(lambda: record(api, queued).get("status") == TaskStatus.CANCELLED)
    assert len(fake.calls) == 1
    wait_until(lambda: docker_run_mode.registered_task("uid-docker-queued") is None)


# ─── 批次 ────────────────────────────────────────────────────────────────────

@pytest.mark.usefixtures("google_key")  # 恢復批次的金鑰從資料庫取，請求不帶明文（#16 Q8b）
def test_a_batch_runs_on_the_container_worker_and_a_queued_recovery_finds_it_completed(
        api, fake, container_worker, docker_run_mode, db_session):
    fake.model_capabilities = replace(fake.model_capabilities, supports_batch=True)
    fake.script = [list(LINES)]
    poll = threading.Event()
    fake.poll_holds = [poll]
    name = "docker-batch.wav"
    request = {"files": [{"filename": upload(api, name), "original_filename": name,
                          "file_uid": name}],
               "provider": "fake", "model": FAKE_MODEL, "source_lang": "ja"}

    with api.websocket_connect("/api/v1/batch/ws/batch-dispatched") as ws:
        ws.send_json(request)
        assert fake.polling.wait(TIMEOUT)
        # 查詢停住時：Celery 回報看著批次的任務執行中，任務頁不給「恢復」
        assert listed(api, "batch-dispatched")["is_alive"] is True
        assert listed(api, "batch-dispatched")["recoverable"] is False
        # 這時按恢復：復原入口派送出去，排在同一個 worker 的佇列裡
        response = api.post("/api/v1/batch/batch-dispatched/recover", json={})
        assert response.status_code == 200, response.text
        poll.set()
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)

    ends = [m for m in messages if m.get("file_uid") == name and m["status_code"] in TERMINAL]
    assert [m["status_code"] for m in ends] == [TaskStatus.COMPLETED]
    # 復原入口排在批次後面，輪到它時批次已經完成：Celery 回報它跑完了，它沒有再查詢一次，
    # 檔案也沒有被結束第二次
    recovery = watching_task_id(db_session, "batch-dispatched")
    wait_until(lambda: docker_run_mode.is_alive(recovery) is False)
    assert fake.polls == 1
    assert listed(api, "batch-dispatched")["status"] == "COMPLETED"
    assert record(api, ends[0]["task_uuid"])["status"] == TaskStatus.COMPLETED
