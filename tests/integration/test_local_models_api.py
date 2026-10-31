"""本機模型權重 API：必要／選用權重的狀態與下載目標、以位元組計算的下載進度、模型卡上的授權。"""
import os
import time
from types import SimpleNamespace

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
    monkeypatch.setattr(local_models, "_plan", None)
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

    monkeypatch.setattr(huggingface_hub, "snapshot_download", no_permission)
    monkeypatch.setattr(local_models.threading, "Thread", RunNow)

    assert client.post(DOWNLOAD_URL, params={"model": "all"}).json()["started"] is True
    download = client.get(STATUS_URL).json()["download"]
    assert download["state"] == "failed"
    assert download["error"]
    assert "wang.xiaoming" not in download["error"]
    assert "Permission denied" not in download["error"]
    assert "Permission denied" in "\n".join(app_log)


class RunNow:
    """下載執行緒當場跑完。"""

    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def fake_hub(monkeypatch, tmp_path, fake_env):
    """假的 Hugging Face：每個 repo 有一份 1,000 位元組的權重與一份 100 位元組的 config.json。

    dry_run 回報每個檔案下載完成後在快照裡的位置與大小；真的下載時先寫一半到 blobs 的暫存檔、
    記下當時查到的下載狀態（``seen``），再把整個檔案放進快照。``ready`` 裡的 repo 算已下載。
    """
    files = {"config.json": 100, "weights/model.safetensors": 1000}
    seen = []

    def storage(repo_id):
        return tmp_path / "hub" / f"models--{repo_id.replace('/', '--')}"

    def fake_snapshot_download(repo_id, revision=None, dry_run=False, **kwargs):
        snapshot = storage(repo_id) / "snapshots" / revision
        if dry_run:
            return [SimpleNamespace(filename=name, file_size=size,
                                    local_path=str(snapshot.joinpath(*name.split("/"))))
                    for name, size in files.items()]
        blobs = storage(repo_id) / "blobs"
        blobs.mkdir(parents=True, exist_ok=True)
        for name, size in files.items():
            temp = blobs / f"{name.replace('/', '-')}.8e67e928.incomplete"
            temp.write_bytes(b"x" * (size // 2))
            seen.append(local_models._download_status())
            temp.unlink()
            target = snapshot.joinpath(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * size)
        return str(snapshot)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    return SimpleNamespace(storage=storage, seen=seen)


class TestDownloadProgress:
    """下載進度以位元組計算：這次要下載的權重合計，下載到一半的大檔也算進去（#24）。"""

    def test_counts_finished_files_and_the_part_of_the_file_being_downloaded(
            self, client, fake_hub, monkeypatch):
        monkeypatch.setattr(local_models.threading, "Thread", RunNow)

        # 選用的 Qwen3-ASR 與 VibeVoice 兩個 repo，各 1,100 位元組
        assert client.post(DOWNLOAD_URL, params={"model": "all"}).json()["started"] is True

        progress = [(s["current_repo"], s["downloaded_bytes"], s["total_bytes"]) for s in fake_hub.seen]
        assert progress == [
            (weights.ASR_MODEL_ID, 50, 2200),             # config.json 寫了一半
            (weights.ASR_MODEL_ID, 100 + 500, 2200),      # 權重寫了一半
            (weights.DIARIZATION_MODEL_ID, 1100 + 50, 2200),
            (weights.DIARIZATION_MODEL_ID, 1100 + 100 + 500, 2200),
        ]
        download = client.get(STATUS_URL).json()["download"]
        assert (download["state"], download["downloaded_bytes"], download["total_bytes"]) == (
            "completed", 2200, 2200)

    def test_partial_files_left_by_an_earlier_download_do_not_count(self, client, fake_hub):
        # 上一次下載被強制結束（關掉視窗）留下的暫存檔：huggingface_hub 不會接著用它
        blobs = fake_hub.storage(weights.ASR_MODEL_ID) / "blobs"
        blobs.mkdir(parents=True)
        stale = blobs / "model.c1886eed.incomplete"
        stale.write_bytes(b"x" * 700)
        an_hour_ago = time.time() - 3600
        os.utime(stale, (an_hour_ago, an_hour_ago))

        start_planned_download(client, [weights.ASR_MODEL_ID])
        assert client.get(STATUS_URL).json()["download"]["downloaded_bytes"] == 0

        (blobs / "model.f322dc1a.incomplete").write_bytes(b"x" * 300)
        assert client.get(STATUS_URL).json()["download"]["downloaded_bytes"] == 300

    def test_never_goes_backwards(self, client, fake_hub):
        # 檔案寫完、從暫存檔放進快照的那一瞬間，兩邊都看不到它
        start_planned_download(client, [weights.ASR_MODEL_ID])
        blobs = fake_hub.storage(weights.ASR_MODEL_ID) / "blobs"
        blobs.mkdir(parents=True)
        temp = blobs / "model.f322dc1a.incomplete"
        temp.write_bytes(b"x" * 900)
        assert client.get(STATUS_URL).json()["download"]["downloaded_bytes"] == 900

        temp.unlink()
        assert client.get(STATUS_URL).json()["download"]["downloaded_bytes"] == 900

    def test_a_new_download_does_not_show_the_previous_progress(self, client, fake_hub, monkeypatch):
        monkeypatch.setattr(local_models.threading, "Thread", RunNow)
        client.post(DOWNLOAD_URL, params={"model": "moss-qwen3-asr"})
        assert client.get(STATUS_URL).json()["download"]["downloaded_bytes"] == 1100

        # 第二次的下載執行緒還沒問完 Hub：不知道總共多大，也不拿上一次的檔案清單來算
        monkeypatch.setattr(local_models.threading, "Thread", FakeThreadThatNeverRuns)
        client.post(DOWNLOAD_URL, params={"model": "vibevoice-qwen3-asr"})
        download = client.get(STATUS_URL).json()["download"]
        assert (download["state"], download["downloaded_bytes"], download["total_bytes"]) == (
            "downloading", None, None)


class FakeThreadThatNeverRuns:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def start_planned_download(client, repos):
    """模擬下載執行緒問完 Hub、開始下載第一個 repo，之後就停在那裡。"""
    local_models._state.update(state="downloading", repo_index=1, repo_count=len(repos),
                               current_repo=repos[0])
    plan = local_models._plan_download(repos)
    local_models._plan = plan
    local_models._state.update(total_bytes=plan.total_bytes, downloaded_bytes=0)


class TestModelCardLicense:
    """設定頁照 Hugging Face 模型卡列出每份權重的授權，並連到模型卡（#24）。"""

    def test_status_lists_the_license_written_on_each_model_card(self, client, fake_env):
        by_repo = {m["repo_id"]: m for m in client.get(STATUS_URL).json()["models"]}
        assert {repo: m["license"] for repo, m in by_repo.items()} == {
            weights.MOSS_MODEL_ID: "apache-2.0",
            weights.ALIGNER_MODEL_ID: "apache-2.0",
            weights.ASR_MODEL_ID: "apache-2.0",
            weights.DIARIZATION_MODEL_ID: "mit",
        }
        # 連到下載的那個版本的模型卡，不是之後可能改過授權的最新版
        assert by_repo[weights.MOSS_MODEL_ID]["model_card_url"] == (
            "https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize/blob/"
            f"{weights.REPO_REVISIONS[weights.MOSS_MODEL_ID]}/README.md")

    @pytest.mark.parametrize("repo_id", weights.ALL_REPOS)
    def test_license_was_checked_at_the_pinned_revision(self, repo_id):
        checked_at, _ = local_models._MODEL_CARD_LICENSES[repo_id]
        assert checked_at == weights.REPO_REVISIONS[repo_id], (
            f"{repo_id} 換了 revision：照新版本的模型卡重新核對授權，再更新 _MODEL_CARD_LICENSES")


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
