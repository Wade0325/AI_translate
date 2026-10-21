"""整合測試等背景任務的小工具：逾時就直接失敗，不讓 CI 卡住。"""

from __future__ import annotations

import time

TIMEOUT = 30


def wait_until(condition, timeout: float = TIMEOUT) -> None:
    """等到 ``condition()`` 成立。"""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "等太久"
        time.sleep(0.02)


def cancel_when_dispatched(api, file_uid: str, timeout: float = TIMEOUT) -> dict:
    """派送本身不廣播：輪詢取消端點，直到任務登記好、取消真的送出，回傳取消端點的回應。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = api.post(f"/api/v1/transcription/{file_uid}/cancel")
        assert response.status_code == 200
        if response.json()["cancelled"]:
            return response.json()
        time.sleep(0.02)
    raise AssertionError(f"{file_uid} 一直沒有派送")
