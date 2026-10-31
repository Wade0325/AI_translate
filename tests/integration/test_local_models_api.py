"""本機模型權重 API：必要／選用權重的狀態與下載目標。"""
import huggingface_hub
import pytest

from app.api import local_models
from app.core.config import get_settings
from app.provider.local import weights

STATUS_URL = "/api/v1/setting/local-models/status"
DOWNLOAD_URL = "/api/v1/setting/local-models/download"
READINESS_URL = "/api/v1/setting/local-models/readiness"


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
    monkeypatch.setattr(weights, "detect_gpu", lambda: weights.Gpu("Test GPU", 16.0, True))
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


def use_gpu(monkeypatch, gpu):
    monkeypatch.setattr(weights, "detect_gpu", lambda: gpu)


def test_status_reports_the_gpu_and_its_memory(client, fake_env):
    body = client.get(STATUS_URL).json()
    assert (body["gpu_available"], body["gpu_name"], body["gpu_vram_gb"]) == (True, "Test GPU", 16.0)
    assert body["gpu_problem"] is None
    assert body["vram_notice"] is None


def test_status_says_why_an_unsupported_card_cannot_be_used(client, fake_env, monkeypatch):
    # torch 不支援這張顯卡（#11 Q4）：不算可用，設定頁照 gpu_problem 說明原因
    use_gpu(monkeypatch, weights.Gpu("NVIDIA GeForce GTX 980", 4.0, False))
    body = client.get(STATUS_URL).json()
    assert body["gpu_available"] is False
    assert "PyTorch 不支援這張顯卡（NVIDIA GeForce GTX 980）" in body["gpu_problem"]
    assert body["vram_notice"] is None


def test_status_warns_about_memory_below_the_minimum(client, fake_env, monkeypatch):
    use_gpu(monkeypatch, weights.Gpu("NVIDIA GeForce RTX 3060 Ti", 8.0, True))
    body = client.get(STATUS_URL).json()
    assert body["gpu_available"] is True
    assert "8 GB 沒有測過" in body["vram_notice"]


class TestReadiness:
    """轉錄頁選本機時先問的事（#11）：能不能轉錄、不能的原因與下一步、顯卡記憶體的提示。"""

    @pytest.fixture(autouse=True)
    def standalone(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "app_mode", "standalone")

    def test_ready_with_a_gpu_that_has_enough_memory(self, client, fake_env):
        assert client.get(READINESS_URL, params={"model": "moss-align"}).json() == {
            "checked": True, "ready": True, "reason": None, "message": None,
            "vram_notice": None}

    def test_without_a_gpu_suggests_another_provider(self, client, fake_env, monkeypatch):
        use_gpu(monkeypatch, weights.NO_GPU)
        body = client.get(READINESS_URL, params={"model": "moss-align"}).json()
        assert (body["checked"], body["ready"], body["reason"]) == (True, False, "no_gpu")
        assert "沒有可用的 NVIDIA 顯卡" in body["message"]

    def test_unsupported_card_is_not_ready(self, client, fake_env, monkeypatch):
        use_gpu(monkeypatch, weights.Gpu("NVIDIA GeForce GTX 980", 4.0, False))
        body = client.get(READINESS_URL).json()
        assert (body["ready"], body["reason"]) == (False, "unsupported_gpu")
        assert "GTX 980" in body["message"]

    def test_missing_weights_of_the_chosen_model(self, client, fake_env):
        # 預設模型的權重都在，「MOSS + Qwen3-ASR」另外要 Qwen3-ASR
        body = client.get(READINESS_URL, params={"model": "moss-qwen3-asr"}).json()
        assert (body["ready"], body["reason"]) == (False, "missing_weights")
        assert weights.ASR_MODEL_ID in body["message"]

    def test_small_memory_is_a_notice_not_a_block(self, client, fake_env, monkeypatch):
        # 8 GB 以下警告後放行（#11 Q2b）：照樣 ready，只多一段提示
        use_gpu(monkeypatch, weights.Gpu("NVIDIA GeForce RTX 3050", 6.0, True))
        body = client.get(READINESS_URL, params={"model": "moss-align"}).json()
        assert body["ready"] is True
        assert "低於 8 GB" in body["vram_notice"]
        assert "約 12 分鐘一段" in body["vram_notice"]

    def test_docker_mode_does_not_check_the_api_container(self, client, fake_env, monkeypatch):
        # Docker 模式的本機轉錄在主機的 GPU worker，API 容器看到的不是它的顯卡
        monkeypatch.setattr(get_settings(), "app_mode", "docker")
        use_gpu(monkeypatch, weights.NO_GPU)
        assert client.get(READINESS_URL).json() == {
            "checked": False, "ready": None, "reason": None, "message": None,
            "vram_notice": None}
