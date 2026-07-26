"""執行模式設定推導測試（docker 預設不變是回歸守門重點）。"""
from pathlib import Path

import pytest

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """隔離宿主環境變數，測試只看 init kwargs。"""
    for var in ("APP_MODE", "DATABASE_URL", "AIT_DATA_DIR",
                "AIT_STATIC_DIR", "AIT_FFMPEG_DIR"):
        monkeypatch.delenv(var, raising=False)


def test_default_mode_is_docker():
    """預設必須是 docker：compose 不設 APP_MODE，任何行為變化都是回歸。"""
    s = Settings(_env_file=None)
    assert s.app_mode == "docker"
    assert s.is_standalone is False
    assert s.sync_database_url.startswith("postgresql://")
    # docker 模式維持 cwd 相對路徑（容器與 host worker 共享上傳檔的契約）
    assert s.temp_uploads_path == Path("temp_uploads")
    assert s.vad_artifacts_path == Path("vad_artifacts")
    assert s.static_path is None


def test_database_url_env_still_short_circuits():
    s = Settings(_env_file=None, app_mode="standalone",
                 database_url="postgresql://u:p@h:5432/db")
    assert s.sync_database_url == "postgresql://u:p@h:5432/db"


def test_standalone_defaults_to_sqlite_under_data_dir():
    s = Settings(_env_file=None, app_mode="standalone", data_dir="X:/pkg/data")
    assert s.is_standalone is True
    assert s.sync_database_url == "sqlite:///X:/pkg/data/app.db"
    assert s.temp_uploads_path == Path("X:/pkg/data") / "temp_uploads"
    assert s.vad_artifacts_path == Path("X:/pkg/data") / "vad_artifacts"


def test_standalone_static_dir_override():
    s = Settings(_env_file=None, app_mode="standalone",
                 static_dir="X:/pkg/frontend/dist")
    assert s.static_path == Path("X:/pkg/frontend/dist")
