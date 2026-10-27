"""整合測試：免安裝模式的日誌檔不寫原檔名、提示詞與轉錄內容（#231 Q5、ADR-0005）。

透過 API 跑完單檔任務，只把供應商換成假供應商；上傳、ffmpeg、去靜音、任務紀錄與 WebSocket 狀態廣播
都走真的。再讀日誌檔：要有這個任務的紀錄，但不能有使用者的原檔名、提示詞與轉錄出來的文字。
"""
import os
import re
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.task_status import TaskStatus
from app.exceptions import TransientError
from app.tasks import batch_core
from tests.support.fake_provider import FAKE_MODEL
from tests.support.task_api import receive_until, upload
from tests.support.waiting import wait_until

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

NAME = "王小明的會議錄音"
PROMPT = "人名照寫：林美華"
SPOKEN = "這是機密的轉錄內容。"


def test_standalone_app_writes_its_log_into_the_data_folder(tmp_path):
    """另開一個行程，以免安裝模式啟動 app（真的 lifespan）：log 寫進資料目錄 logs 裡當天的檔案。"""
    probe = textwrap.dedent("""
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            assert client.get("/api/v1/health").status_code == 200
    """)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "APP_MODE": "standalone",
           "AIT_DATA_DIR": str(tmp_path / "data")}
    env.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=BACKEND_DIR, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120, env=env)

    assert result.returncode == 0, result.stderr
    [log] = (tmp_path / "data" / "logs").iterdir()
    assert re.fullmatch(r"app-\d{4}-\d{2}-\d{2}\.log", log.name)
    text = log.read_text(encoding="utf-8")
    assert "正在啟動 AI Voice Transcription API" in text
    assert "應用程式正在關閉" in text
    # 主控台照寫完整路徑；日誌檔裡使用者家目錄寫成 ~（Windows 的暫存資料夾就在家目錄底下）
    assert f"日誌檔寫在 {(tmp_path / 'data' / 'logs').resolve()}" in result.stdout
    assert "日誌檔寫在 " in text
    assert str(Path.home()) not in text


@pytest.fixture
def api(api, fake):
    return api


def transcribe(api, run_mode, filename: str, original_filename: str) -> dict:
    """送出單檔任務，等它整個跑完（結束的廣播之後還有收尾），回傳結束的那則廣播。"""
    with api.websocket_connect("/api/v1/ws/uid-log-file") as ws:
        ws.send_json({"filename": filename, "original_filename": original_filename,
                      "provider": "fake", "model": FAKE_MODEL, "source_lang": "ja",
                      "prompt": PROMPT})
        end = receive_until(ws, TaskStatus.COMPLETED, TaskStatus.FAILED)[-1]
    wait_until(lambda: not run_mode.is_alive(end["task_uuid"]))
    return end


def test_completed_task_is_logged_without_the_name_prompt_or_transcript(
        api, fake, in_process_run_mode, log_file):
    fake.script = [[(0.2, 1.5, 0, SPOKEN)]]
    filename = upload(api, f"{NAME}.wav")

    end = transcribe(api, in_process_run_mode, filename, f"{NAME}.wav")

    assert end["status_code"] == TaskStatus.COMPLETED
    assert SPOKEN in end["result"]["transcripts"]["srt"]  # 轉錄內容確實經過了 app
    log = log_file()
    assert end["task_uuid"] in log
    assert filename in log  # 磁碟上的隨機名稱照寫，排查時對得起來
    for private in (NAME, PROMPT, SPOKEN):
        assert private not in log


def test_failed_task_is_logged_without_the_name(api, in_process_run_mode, log_file):
    # 讀不了的音檔：失敗的原因與 traceback 都寫進日誌檔，一樣不帶原檔名
    response = api.post("/api/v1/upload",
                        files={"file": (f"{NAME}.m4a", b"not audio" * 64, "audio/x-m4a")})
    filename = response.json()["filename"]

    end = transcribe(api, in_process_run_mode, filename, f"{NAME}.m4a")

    assert end["status_code"] == TaskStatus.FAILED
    log = log_file()
    assert f"Transcription task failed for log ID: {end['task_uuid']}" in log
    assert NAME not in log


def test_batch_is_logged_without_the_name_prompt_or_transcript(
        api, fake, in_process_run_mode, log_file, google_key, quick_transient_retries, monkeypatch):
    # 批次的進度訊息帶著檔名（畫面要顯示），只是不寫進 log；上傳遇到暫時錯誤的重試也一樣
    fake.model_capabilities = replace(fake.model_capabilities, supports_batch=True)
    monkeypatch.setattr(batch_core, "FIRST_POLL_SECONDS", 0.01)
    fake.script = [[(0.2, 1.5, 0, SPOKEN)]]
    fake.upload_errors.append(TransientError("503 服務暫時無法使用", reason="503 UNAVAILABLE"))
    files = [{"filename": upload(api, f"{NAME}.wav"), "original_filename": f"{NAME}.wav",
              "file_uid": "f1"}]

    with api.websocket_connect("/api/v1/batch/ws/batch-log-file") as ws:
        ws.send_json({"files": files, "provider": "fake", "model": FAKE_MODEL,
                      "source_lang": "ja", "prompt": PROMPT})
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
    wait_until(lambda: not in_process_run_mode.is_alive(messages[-1]["task_uuid"]))

    assert any(NAME in m["status_text"] for m in messages)  # 畫面上照樣看得到檔名
    log = log_file()
    assert "遇到暫時錯誤" in log
    assert "batch-log-file" in log
    for private in (NAME, PROMPT, SPOKEN):
        assert private not in log
