"""Local 模型權重 API：必要／選用權重的狀態與下載目標。"""
import huggingface_hub
import pytest

from app.api import local_models
from app.provider.local import weights

STATUS_URL = "/api/v1/setting/local-models/status"
DOWNLOAD_URL = "/api/v1/setting/local-models/download"


@pytest.fixture
def fake_env(monkeypatch):
    """預設模型權重已下載、選用的沒有；下載執行緒只記錄不真的跑。"""
    ready = {weights.MOSS_MODEL_ID, weights.ALIGNER_MODEL_ID}
    started = []

    class FakeThread:
        def __init__(self, target, args=(), **kwargs):
            self.args = args

        def start(self):
            started.append(list(self.args[0]))

    monkeypatch.setattr(weights, "repo_is_ready", lambda repo: repo in ready)
    monkeypatch.setattr(weights, "cuda_status", lambda: (True, "Test GPU"))
    monkeypatch.setattr(local_models.threading, "Thread", FakeThread)
    monkeypatch.setattr(local_models.shutil, "disk_usage",
                        lambda path: type("U", (), {"free": 500 * 1024 ** 3})())
    # 整份模組級狀態換成測試專用副本，結束後還原，避免欄位在測試間殘留
    monkeypatch.setattr(local_models, "_state", dict(local_models._state, state="idle",
                                                     target=None, error=None))
    return ready, started


def test_status_marks_required_and_optional(client, fake_env):
    body = client.get(STATUS_URL).json()
    assert body["default_model"] == "moss-align"
    by_repo = {m["repo_id"]: m for m in body["models"]}
    assert by_repo[weights.MOSS_MODEL_ID]["required"] is True
    assert by_repo[weights.DIARIZATION_MODEL_ID]["required"] is False
    assert by_repo[weights.DIARIZATION_MODEL_ID]["used_by"] == ["vibevoice-qwen3-asr"]
    assert body["all_downloaded"] is True          # 只看預設模型所需
    assert body["optional_downloaded"] is False
    # 按鈕上的大小由後端提供（MOSS 1.8 + 對齊器 1.9；Qwen3-ASR 4.1 + VibeVoice 16.7）
    assert body["required_size_gb"] == 3.7
    assert body["optional_size_gb"] == 20.8


def test_default_download_is_noop_when_required_ready(client, fake_env):
    _, started = fake_env
    assert client.post(DOWNLOAD_URL).json() == {
        "started": False, "reason": "already-downloaded"}
    assert started == []


def test_already_downloaded_clears_stale_failure(client, fake_env):
    local_models._state.update(state="failed", error="network down")
    client.post(DOWNLOAD_URL)
    download = client.get(STATUS_URL).json()["download"]
    assert download["state"] == "completed" and download["error"] is None


def test_download_all_fetches_only_missing_optional(client, fake_env):
    _, started = fake_env
    body = client.post(DOWNLOAD_URL, params={"model": "all"}).json()
    assert body["started"] is True
    assert started == [[weights.ASR_MODEL_ID, weights.DIARIZATION_MODEL_ID]]


def test_download_specific_model(client, fake_env):
    _, started = fake_env
    client.post(DOWNLOAD_URL, params={"model": "moss-qwen3-asr"})
    assert started == [[weights.ASR_MODEL_ID]]


def test_unknown_model_is_rejected(client, fake_env):
    assert client.post(DOWNLOAD_URL, params={"model": "nope"}).status_code == 400


def test_failed_download_shows_a_fixed_message(client, fake_env, monkeypatch, app_log):
    """下載失敗時畫面上是固定訊息：例外的文字可能帶著使用者電腦上的路徑，原因只記在 log。"""
    def no_permission(repo_id, **kwargs):
        raise PermissionError(13, "Permission denied",
                              r"C:\Users\wang.xiaoming\hf_cache\models--OpenMOSS")

    class RunNow:
        """下載執行緒當場跑完。"""

        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", no_permission)
    monkeypatch.setattr(local_models.threading, "Thread", RunNow)

    assert client.post(DOWNLOAD_URL, params={"model": "all"}).json()["started"] is True
    download = client.get(STATUS_URL).json()["download"]
    assert download["state"] == "failed"
    assert download["error"]
    assert "wang.xiaoming" not in download["error"]
    assert "Permission denied" not in download["error"]
    assert "Permission denied" in "\n".join(app_log)
