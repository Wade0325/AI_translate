"""整合測試：設定頁「資料與隱私」用的本機資料 API（#231 Q1、Q7）

測試範圍：
  GET    /api/v1/local-data                 資料放在哪、保留音檔留幾天、目前留了多少
  DELETE /api/v1/local-data/retained-audio  立即刪除全部保留音檔
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.models import TranscriptionLog
from app.services import audio_store

URL = "/api/v1/local-data"
DELETE_URL = f"{URL}/retained-audio"


@pytest.fixture
def store(uploads) -> Path:
    """保留區（測試的暫存資料夾裡，還沒建立）。"""
    return audio_store.store_path()


def retain(store: Path, name: str, size: int) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    path = store / name
    path.write_bytes(b"a" * size)
    return path


class TestSummary:
    def test_nothing_retained_yet(self, client: TestClient, store: Path):
        body = client.get(URL).json()

        assert body["retained_audio"] == {
            "enabled": True,
            "retention_days": 30,
            "folder": str(store.resolve()),
            "file_count": 0,
            "total_bytes": 0,
        }

    def test_counts_retained_files_and_their_size(self, client: TestClient, store: Path):
        retain(store, f"{uuid.uuid4()}.m4a", 1000)
        retain(store, f"{uuid.uuid4()}.wav", 2345)
        (store / "not-audio").mkdir()

        retained = client.get(URL).json()["retained_audio"]

        assert (retained["file_count"], retained["total_bytes"]) == (2, 3345)

    def test_reports_the_retention_settings(self, client: TestClient, store: Path, monkeypatch):
        # 天數與開關只能用環境變數改（RETAIN_AUDIO、AUDIO_RETENTION_DAYS），畫面照實說明
        monkeypatch.setattr(get_settings(), "retain_audio", False)
        monkeypatch.setattr(get_settings(), "audio_retention_days", 0)

        retained = client.get(URL).json()["retained_audio"]

        assert (retained["enabled"], retained["retention_days"]) == (False, 0)

    def test_data_folder_only_in_standalone_mode(self, client: TestClient, store: Path,
                                                 monkeypatch, tmp_path):
        # 資料目錄是免安裝版解壓資料夾裡的 data；Docker 模式的資料分散在容器與 Postgres，沒有一個資料夾可指
        assert client.get(URL).json()["data_folder"] is None

        monkeypatch.setattr(get_settings(), "app_mode", "standalone")
        monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))

        assert client.get(URL).json()["data_folder"] == str(tmp_path.resolve())


class TestDeleteRetainedAudio:
    def test_deletes_every_retained_file(self, client: TestClient, store: Path, uploads: Path):
        retain(store, f"{uuid.uuid4()}.m4a", 10)
        retain(store, f"{uuid.uuid4()}.wav", 20)
        upload = uploads / "還沒轉錄.m4a"
        upload.write_bytes(b"upload")

        response = client.delete(DELETE_URL)

        assert response.status_code == 200
        assert response.json() == {"deleted": 2, "failed": 0}
        assert list(store.iterdir()) == []
        # 只刪保留區：上傳暫存區的檔案不動
        assert upload.exists()
        assert client.get(URL).json()["retained_audio"]["file_count"] == 0

    def test_nothing_to_delete(self, client: TestClient, store: Path):
        assert client.delete(DELETE_URL).json() == {"deleted": 0, "failed": 0}

    def test_task_records_stay_and_their_audio_reads_as_gone(self, client: TestClient,
                                                            store: Path, db_session: Session):
        # 和過期清掃一樣不動資料庫：轉錄結果還在，只是音檔沒了，播放端點回 404
        task_uuid = uuid.uuid4()
        name = f"{task_uuid}.m4a"
        retain(store, name, 10)
        db_session.add(TranscriptionLog(task_uuid=task_uuid, status="COMPLETED",
                                        original_filename="meeting.m4a", audio_filename=name))
        db_session.commit()
        assert client.get(f"/api/v1/transcripts/{task_uuid}/audio").status_code == 200

        client.delete(DELETE_URL)

        assert client.get(f"/api/v1/history/{task_uuid}").status_code == 200
        assert client.get(f"/api/v1/transcripts/{task_uuid}/audio").status_code == 404

    def test_counts_files_it_could_not_delete(self, client: TestClient, store: Path,
                                              monkeypatch, app_log):
        # Windows 上正被開著的檔案刪不掉（例如批次從復原入口重新收尾時）：照實回報，其他照刪
        stuck = retain(store, f"{uuid.uuid4()}.m4a", 10)
        retain(store, f"{uuid.uuid4()}.wav", 10)
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == stuck:
                raise PermissionError("檔案正在使用中")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)

        assert client.delete(DELETE_URL).json() == {"deleted": 1, "failed": 1}
        assert list(store.iterdir()) == [stuck]
        assert any(stuck.name in entry for entry in app_log)
