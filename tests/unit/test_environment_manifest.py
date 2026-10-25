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
    }
    # 本機的模型都去靜音；單次長度的上限照模型能力
    assert described["settings"]["remove_silence"] is True
    assert described["settings"]["single_pass_seconds"] > 0


def test_records_the_gpu_this_run_can_see(monkeypatch):
    gib = 1024 ** 3
    card = SimpleNamespace(name="NVIDIA GeForce RTX 4080 SUPER", total_memory=16 * gib)
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True,
                                                 get_device_properties=lambda index: card))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

    described = environment_manifest.describe("local", weights.MOSS_ALIGN)

    assert described["gpu"] == {"name": "NVIDIA GeForce RTX 4080 SUPER", "vram_gb": 16.0,
                                "cuda_visible_devices": "0"}


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
