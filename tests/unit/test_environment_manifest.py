"""轉錄環境的描述（#37）：評測的 manifest 記下它，之後的版本也要拿它當轉錄環境的紀錄。"""
import sys
from types import SimpleNamespace

import pytest

from app.provider.local import weights
from app.services import environment_manifest


def test_local_models_record_their_pinned_weight_revisions():
    described = environment_manifest.describe("local", weights.MOSS_ALIGN)

    assert described["model_revisions"] == {
        weights.MOSS_MODEL_ID: weights.REPO_REVISIONS[weights.MOSS_MODEL_ID],
        weights.ALIGNER_MODEL_ID: weights.REPO_REVISIONS[weights.ALIGNER_MODEL_ID],
        # 分段轉錄時對齊說話者編號的 CAM++（#93）：換了它，分段轉錄的說話者編號可能不同
        weights.CAMPPLUS_MODEL_ID: weights.REPO_REVISIONS[weights.CAMPPLUS_MODEL_ID],
    }
    # 本機的模型都不去靜音（#95）；單次長度的上限照模型能力
    assert described["settings"]["remove_silence"] is False
    assert described["settings"]["single_pass_seconds"] > 0


def _one_gpu(monkeypatch, nvidia_smi):
    """一張 16 GB 的顯卡；``nvidia_smi`` 是 nvidia-smi 回報的驅動版本（None 是問不到）。"""
    gib = 1024 ** 3
    card = SimpleNamespace(name="NVIDIA GeForce RTX 4080 SUPER", total_memory=16 * gib)
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True,
                                                 get_device_properties=lambda index: card))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    monkeypatch.setattr(weights, "command_output", lambda *command: (
        nvidia_smi if command[0] == "nvidia-smi" else None))


def test_records_the_gpu_this_run_can_see(monkeypatch):
    _one_gpu(monkeypatch, "576.02\n")

    described = environment_manifest.describe("local", weights.MOSS_ALIGN)

    # 換了驅動，同一段音檔可能轉出不同的結果：基準與 PR 的驅動要相同才比（#276）
    assert described["gpu"] == {"name": "NVIDIA GeForce RTX 4080 SUPER", "vram_gb": 16.0,
                                "driver": "576.02", "cuda_visible_devices": "0"}


def test_a_driver_nvidia_smi_cannot_tell_is_recorded_as_none(monkeypatch):
    # summary 把讀不到的驅動當成確認不了相同，不下判定
    _one_gpu(monkeypatch, None)

    assert environment_manifest.describe("local", weights.MOSS_ALIGN)["gpu"]["driver"] is None


@pytest.mark.parametrize("torch", [None, SimpleNamespace(
    cuda=SimpleNamespace(is_available=lambda: False))], ids=["no torch", "no CUDA"])
def test_no_gpu_is_recorded_as_none(monkeypatch, torch):
    monkeypatch.setitem(sys.modules, "torch", torch)

    assert environment_manifest.describe("local", weights.MOSS_ALIGN)["gpu"] is None


def test_package_versions_come_from_the_installed_distributions():
    packages = environment_manifest.describe("local", weights.MOSS_ALIGN)["packages"]

    assert set(packages) == {"torch", "transformers", "moss-transcribe-diarize"}
    for package in packages.values():
        assert set(package) == {"version", "source"}


def test_a_package_from_pypi_has_only_a_version():
    assert environment_manifest.package("pytest") == {"version": pytest.__version__, "source": None}
    assert environment_manifest.package("no-such-distribution") == {"version": None, "source": None}


def test_a_package_installed_from_an_archive_records_where_it_came_from(tmp_path, monkeypatch):
    # moss-transcribe-diarize 是從固定 commit 的壓縮檔安裝的（requirements-standalone.txt），版本號
    # 看不出是哪個 commit；pip 把來源記在 direct_url.json（PEP 610）
    url = "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize/archive/e3bdd93.zip"
    info = tmp_path / "fake_archive_package-0.1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fake-archive-package\nVersion: 0.1.0\n", encoding="utf-8")
    (info / "direct_url.json").write_text(f'{{"url": "{url}", "archive_info": {{}}}}',
                                          encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    assert environment_manifest.package("fake-archive-package") == {"version": "0.1.0",
                                                                     "source": url}
