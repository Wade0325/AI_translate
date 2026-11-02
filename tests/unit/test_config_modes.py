"""執行模式設定推導測試（docker 預設不變是回歸守門重點）。"""
import re
from pathlib import Path

import pytest

from app.core import config
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """隔離宿主環境變數，測試只看 init kwargs。"""
    for var in ("APP_MODE", "DATABASE_URL", "AIT_DATA_DIR",
                "AIT_STATIC_DIR", "AIT_FFMPEG_DIR", "CORS_ALLOWED_ORIGINS", "HF_HOME"):
        monkeypatch.delenv(var, raising=False)


def test_default_mode_is_docker():
    """預設必須是 docker：compose 不設 APP_MODE，任何行為變化都是回歸。"""
    s = Settings(_env_file=None)
    assert s.app_mode == "docker"
    assert s.is_standalone is False
    assert s.sync_database_url.startswith("postgresql://")
    # Docker 模式維持 cwd 相對路徑（容器與 host worker 共享上傳檔的契約）
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


def test_cors_origins_default_to_vite_dev_server():
    """預設只放行開發用的 Vite dev server；免安裝模式同源不需要 CORS。"""
    s = Settings(_env_file=None)
    assert s.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_origins_from_env_comma_separated(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS",
                       " http://192.168.1.10:5173 , https://Example.test/ ,")
    s = Settings(_env_file=None)
    assert s.cors_origins == ["http://192.168.1.10:5173", "https://example.test"]


def test_cors_origins_ignore_wildcard(monkeypatch):
    """萬用字元會讓任何網站都能跨站呼叫，設定了也不採用。"""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*,http://localhost:5173")
    assert Settings(_env_file=None).cors_origins == ["http://localhost:5173"]


def test_cors_origins_can_be_emptied(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    assert Settings(_env_file=None).cors_origins == []


class TestHfHome:
    """模型權重的位置（#267）：沒設 HF_HOME 時，免安裝模式放在資料目錄，Docker 模式不變。"""

    def test_standalone_defaults_to_models_under_data_dir(self):
        s = Settings(_env_file=None, app_mode="standalone", data_dir="X:/pkg/data")
        assert s.hf_home == str(Path("X:/pkg/data") / "models" / "hf_cache")

    def test_standalone_without_data_dir_stays_inside_the_package(self):
        # 不經過啟動器、只帶 APP_MODE 手動啟動（舊版 README.txt 的寫法）：資料目錄是發布包的
        # data\，模型權重跟著放進去，不寫到開發機的 D:\AI_translate
        s = Settings(_env_file=None, app_mode="standalone")
        assert s.hf_home == str(ROOT / "data" / "models" / "hf_cache")

    def test_docker_mode_default_is_unchanged(self):
        assert Settings(_env_file=None).hf_home == r"D:\AI_translate\models\hf_cache"

    def test_docker_mode_default_matches_local_worker_bat(self):
        # Docker 模式的本機轉錄在主機的 local_worker.bat；在主機下載權重（download_weights）沒設
        # HF_HOME 時用設定的預設值，兩邊不一致就會下載到 worker 找不到的地方
        bat = (ROOT / "local_worker.bat").read_text(encoding="utf-8")
        match = re.search(r'^set "?HF_HOME=([^"\r\n]+)"?\s*$', bat, re.M | re.I)
        assert match, "local_worker.bat 裡找不到 set HF_HOME=..."
        assert match.group(1) == config.DOCKER_HF_HOME == Settings(_env_file=None).hf_home

    @pytest.mark.parametrize("app_mode", ["docker", "standalone"])
    def test_hf_home_env_wins_in_both_modes(self, monkeypatch, app_mode):
        monkeypatch.setenv("HF_HOME", "E:/hf")
        s = Settings(_env_file=None, app_mode=app_mode, data_dir="X:/pkg/data")
        assert s.hf_home == "E:/hf"

    def test_empty_hf_home_counts_as_unset(self, monkeypatch):
        # .env.example 裡的 HF_HOME= 取消註解但沒填值
        monkeypatch.setenv("HF_HOME", "")
        s = Settings(_env_file=None, app_mode="standalone", data_dir="X:/pkg/data")
        assert s.hf_home == str(Path("X:/pkg/data") / "models" / "hf_cache")
