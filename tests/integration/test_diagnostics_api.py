"""整合測試：設定頁「複製診斷資訊」（#24）

測試範圍：
  GET /api/v1/diagnostics  回報問題時貼進 GitHub Issue 的一段文字

顯卡、模型權重、nvidia-smi 與 ffmpeg 都換成假的：CI 沒有顯卡，也不一定有 ffmpeg。
"""
import platform
import socket
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.version import APP_VERSION
from app.database.models import TranscriptionLog
from app.provider.local import weights
from app.services import diagnostics

URL = "/api/v1/diagnostics"

FFMPEG_OUTPUT = ("ffmpeg version n7.1.1-20250101 Copyright (c) 2000-2025 the FFmpeg developers\n"
                 "built with gcc 14.2.0 (crosstool-NG 1.26.0.120_4d36f27)\n")


@pytest.fixture
def machine(monkeypatch):
    """一台 Windows 11、RTX 4080、驅動 576.02 的電腦，預設模型的權重已下載、選用的沒有。

    回傳可以改的狀態：``gpu``、``ready``（已下載的權重）與 ``commands``（指令 → 標準輸出，
    None 是找不到或失敗）。
    """
    state = {
        "gpu": weights.Gpu("NVIDIA GeForce RTX 4080", 15.99, True),
        "ready": {weights.MOSS_MODEL_ID, weights.ALIGNER_MODEL_ID},
        "commands": {"nvidia-smi": "576.02\n", "ffmpeg": FFMPEG_OUTPUT},
    }
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "release", lambda: "10")
    monkeypatch.setattr(platform, "version", lambda: "10.0.26100")
    monkeypatch.setattr(platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(platform, "python_version", lambda: "3.11.9")
    monkeypatch.setattr(diagnostics, "package", lambda name: {"version": {
        "torch": "2.8.0+cu128", "transformers": "5.13.0", "moss-transcribe-diarize": "0.1.0",
        "google-genai": "2.6.0"}[name], "source": None})
    monkeypatch.setattr(weights, "detect_gpu", lambda: state["gpu"])
    monkeypatch.setattr(weights, "repo_is_ready", lambda repo: repo in state["ready"])
    monkeypatch.setattr(diagnostics, "ffmpeg_bin", lambda: "ffmpeg")
    for module in (diagnostics, weights):  # weights 問 nvidia-smi，diagnostics 問 ffmpeg
        monkeypatch.setattr(module, "command_output",
                            lambda command, *args: state["commands"].get(Path(command).stem))
    return state


@pytest.fixture
def standalone(monkeypatch, tmp_path) -> Path:
    """免安裝模式，data 資料夾在暫存資料夾裡；回傳 data 資料夾。"""
    monkeypatch.setattr(get_settings(), "app_mode", "standalone")
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    return tmp_path


def report(client: TestClient) -> str:
    response = client.get(URL)
    assert response.status_code == 200
    return response.json()["text"]


def without_free_space(text: str) -> list[str]:
    """拿掉磁碟剩餘空間那一行（數字隨執行的電腦不同），其餘逐行比對。"""
    return [line for line in text.splitlines() if not line.startswith("- data 資料夾所在磁碟")]


class TestStandalone:
    def test_lists_what_a_bug_report_needs(self, client, machine, standalone):
        text = report(client)

        assert without_free_space(text) == [
            "診斷資訊",
            f"- 版本：{APP_VERSION}",
            "- 執行模式：免安裝模式",
            # Python 3.11 在 Windows 11 上回報 10，照組建號改正
            "- 作業系統：Windows 11（10.0.26100，AMD64）",
            "- Python：3.11.9",
            "- 套件：torch 2.8.0+cu128、transformers 5.13.0、moss-transcribe-diarize 0.1.0、"
            "google-genai 2.6.0",
            "- NVIDIA 驅動：576.02",
            "- 顯卡：NVIDIA GeForce RTX 4080（16 GB）",
            "- 模型權重 moss-align（預設）：已下載",
            f"- 模型權重 moss-qwen3-asr（選用）：缺少 {weights.ASR_MODEL_ID}",
            f"- 模型權重 vibevoice-qwen3-asr（選用）：缺少 {weights.DIARIZATION_MODEL_ID}、"
            f"{weights.ASR_MODEL_ID}",
            "- ffmpeg：n7.1.1-20250101",
        ]
        assert text.endswith("\n")
        free_space = [line for line in text.splitlines() if line not in without_free_space(text)]
        assert len(free_space) == 1
        assert free_space[0].startswith("- data 資料夾所在磁碟的剩餘空間：")
        assert free_space[0].endswith(" GB")

    def test_driver_without_a_usable_gpu(self, client, machine, standalone):
        # PyTorch 用不了顯卡時 nvidia-smi 可能照樣找得到卡：原因和轉錄頁同一句，附上原始錯誤
        machine["gpu"] = weights.GpuUnavailable(
            "driver_too_old", "NVIDIA 顯卡驅動太舊（目前 472.12，需要 572.61 以上）",
            "更新驅動後重新開啟 Mimiji，或改用 Gemini",
            "RuntimeError: The NVIDIA driver on your system is too old (found version 11040).")
        machine["ready"] = set()

        lines = report(client).splitlines()

        assert "- NVIDIA 驅動：576.02" in lines
        assert "- 顯卡：NVIDIA 顯卡驅動太舊（目前 472.12，需要 572.61 以上）" in lines
        assert ("- PyTorch 的錯誤：RuntimeError: The NVIDIA driver on your system is too old "
                "(found version 11040).") in lines
        assert not any(line.startswith("- 顯卡記憶體") for line in lines)
        assert (f"- 模型權重 moss-align（預設）：缺少 {weights.MOSS_MODEL_ID}、"
                f"{weights.ALIGNER_MODEL_ID}") in lines

    def test_no_nvidia_driver_and_no_ffmpeg(self, client, machine, standalone):
        machine["gpu"] = weights.NO_GPU
        machine["commands"] = {}

        lines = report(client).splitlines()

        assert "- NVIDIA 驅動：找不到 nvidia-smi" in lines
        assert "- 顯卡：這台電腦沒有可用的 NVIDIA 顯卡" in lines
        assert not any(line.startswith("- PyTorch 的錯誤") for line in lines)
        assert "- ffmpeg：找不到" in lines

    def test_unsupported_gpu(self, client, machine, standalone):
        machine["gpu"] = weights.Gpu("NVIDIA GeForce GTX 970", 4.0, False)

        lines = report(client).splitlines()

        assert "- 顯卡：NVIDIA GeForce GTX 970（4 GB，目前的 PyTorch 不支援這張顯卡）" in lines
        # 跑不了的卡沒有記憶體的提示（和轉錄頁相同）
        assert not any(line.startswith("- 顯卡記憶體") for line in lines)

    def test_vram_below_the_minimum(self, client, machine, standalone):
        machine["gpu"] = weights.Gpu("NVIDIA GeForce RTX 3060 Ti", 8.0, True)

        lines = report(client).splitlines()

        notice = [line for line in lines if line.startswith("- 顯卡記憶體：")]
        assert notice and "顯卡記憶體 8 GB 沒有測過" in notice[0]


def test_docker_mode_points_to_the_gpu_worker(client, machine):
    # Docker 模式的本機轉錄在主機的 GPU worker，API 容器看到的不是它的顯卡與模型權重
    assert not get_settings().is_standalone

    lines = report(client).splitlines()

    assert "- 執行模式：Docker 模式" in lines
    assert "- 本機轉錄：Docker 模式在主機的 GPU worker 轉錄，這裡看不到它的顯卡與模型權重" in lines
    assert not any(line.startswith(("- NVIDIA 驅動", "- 顯卡", "- 模型權重", "- data 資料夾"))
                   for line in lines)
    assert "- ffmpeg：n7.1.1-20250101" in lines


def test_leaves_out_names_keys_paths_and_transcripts(client, machine, monkeypatch, tmp_path,
                                                     db_session: Session, stored_keys,
                                                     saved_prompt_template):
    """貼進公開的 Issue：不帶原檔名、提示詞、轉錄結果、金鑰、路徑、電腦名稱與使用者名稱。"""
    private = "王小明"
    data = tmp_path / f"{private}的資料" / "data"
    data.mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "app_mode", "standalone")
    monkeypatch.setattr(get_settings(), "data_dir", str(data))
    monkeypatch.setattr(get_settings(), "hf_home", str(data / "models" / "hf_cache"))
    monkeypatch.setenv("HOME", str(tmp_path / private))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / private))
    monkeypatch.setenv("USERNAME", private)
    monkeypatch.setattr(platform, "node", lambda: f"{private}-PC")
    monkeypatch.setattr(socket, "gethostname", lambda: f"{private}-PC")
    stored_keys("Google", ["AIzaSy-secret-key-0000"])
    saved_prompt_template("Google", f"說話者是{private}")
    task = TranscriptionLog(
        task_uuid=uuid.uuid4(), status="COMPLETED", original_filename=f"{private}的會議錄音.wav",
        lrc_content="[00:00.000]今天的會議開始")
    db_session.add(task)
    db_session.commit()
    try:
        text = report(client)
    finally:
        # 測試資料庫整個 session 共用：別的測試會用同一個名字搜尋歷史紀錄
        db_session.delete(task)
        db_session.commit()

    assert "- 執行模式：免安裝模式" in text
    for secret in (private, "AIzaSy", "secret", "會議", str(tmp_path), str(data), "hf_cache"):
        assert secret not in text
