"""透過 API 跑任務的整合測試共用的小工具：上傳、收狀態廣播、查片段與下載、看暫存資料夾。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait

from fastapi.testclient import TestClient

from app.core.task_status import TaskStatus
from tests.support.synthetic_audio import VOICED, synthetic_audio
from tests.support.waiting import TIMEOUT

_reader = ThreadPoolExecutor(max_workers=4)


def receive_until(ws, *end: TaskStatus, timeout: float = TIMEOUT) -> list[dict]:
    """收廣播直到收到其中一種結束狀態。

    等一則廣播超過 timeout 秒就斷言失敗，附上已經收到的廣播，不讓 CI 卡住。
    """
    messages = []
    while not messages or messages[-1]["status_code"] not in end:
        done, _ = wait([_reader.submit(ws.receive_json)], timeout=timeout)
        assert done, f"{timeout} 秒內沒有新的廣播，還沒收到 {'、'.join(end)}；已經收到：{messages}"
        messages.append(done.pop().result())
    return messages


def receive(ws) -> dict:
    """收下一則廣播；逾時直接失敗，不讓 CI 卡住。"""
    return _reader.submit(ws.receive_json).result(timeout=TIMEOUT)


def upload(api: TestClient, name: str = "voice.wav", voiced=VOICED) -> str:
    """上傳合成音檔（有聲段見 synthetic_audio；副檔名是 .flac 時寫成 FLAC），回傳暫存的檔名。"""
    fmt, content_type = ("FLAC", "audio/flac") if name.endswith(".flac") else ("WAV", "audio/wav")
    response = api.post(
        "/api/v1/upload", files={"file": (name, synthetic_audio(fmt, voiced), content_type)})
    assert response.status_code == 200, response.text
    return response.json()["filename"]


def file_results(messages: list[dict]) -> dict[str, dict]:
    """每個檔案最後一則完成或失敗的廣播，以 file_uid 為 key。"""
    return {m["file_uid"]: m for m in messages
            if m.get("file_uid") and m["status_code"] in (TaskStatus.COMPLETED, TaskStatus.FAILED)}


def stored_segments(api: TestClient, task_uuid: str) -> list[dict]:
    return api.get(f"/api/v1/transcripts/{task_uuid}").json()["segments"]


def flat_times(spans: list[dict]) -> list[float]:
    """片段（或詞）的起訖時間依序攤平：[開始, 結束, 開始, 結束, …]。"""
    return [t for span in spans for t in (span["start"], span["end"])]


def download(api: TestClient, task_uuid: str, fmt: str) -> str:
    response = api.get(f"/api/v1/history/{task_uuid}/download/{fmt}")
    assert response.status_code == 200
    return response.text


def leftovers(data_dir) -> list[str]:
    """暫存上傳資料夾裡還留著的檔案：上傳檔，以及去靜音、分段產生的暫存檔。"""
    return sorted(p.name for p in (data_dir / "temp_uploads").iterdir())
