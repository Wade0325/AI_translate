"""``python -m tools.eval transcribe``（#37）：跑正式的轉錄路徑，輸出轉錄結果（LRC）與 manifest。

供應商換成假供應商，其他都走真的：合成音檔經真實的 ffmpeg 轉檔、去靜音、分段轉錄與輸出格式。
不啟動 API、不碰資料庫；輸出的 LRC 直接交給 ``python -m tools.eval eval`` 計分。
"""
import builtins
import hashlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.fake_provider import FAKE_MODEL, Fail
from tests.support.synthetic_audio import synthetic_audio
from tools.eval import cli, lrc

ROOT = Path(__file__).resolve().parents[2]

# 時間軸是送進去的語音視圖：合成音檔去靜音後是 0–2.3、4.7–7.3、9.7–12 秒接成的 7.2 秒，
# 第二句的 3.0 秒落在第二個有聲段，還原回原音檔是 4.7 + 0.7 = 5.4 秒
LINES = [(0.0, 1.5, 0, "第一句測試"), (3.0, 4.0, 1, "第二句測試")]


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "meeting.wav"
    path.write_bytes(synthetic_audio())
    return path


@pytest.fixture(autouse=True)
def visible_gpus(monkeypatch):
    """指令會在沒設 CUDA_VISIBLE_DEVICES 時把它設成 0；每個測試從沒設開始，結束後換回原本的。"""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES")


@pytest.fixture
def no_prompt(monkeypatch):
    """加了 --yes：不該停下來等使用者確認。"""
    def refuse(*_):
        raise AssertionError("加了 --yes 還在等使用者確認")
    monkeypatch.setattr(builtins, "input", refuse)


def _run(audio, out, *extra):
    return cli.main(["transcribe", "--audio", str(audio), "--provider", "fake",
                     "--model", FAKE_MODEL, "--language", "zh-TW", "--out", str(out), *extra])


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, encoding="utf-8",
                          check=True).stdout.strip()


def test_writes_the_transcript_on_the_original_timeline(fake, uploads, audio, tmp_path, no_prompt):
    fake.script = [LINES]
    out = tmp_path / "out"

    assert _run(audio, out, "--yes") == 0

    transcript = lrc.read(out / "meeting.lrc")
    assert [(line.seconds, line.speaker, line.text) for line in transcript.lines] == [
        (0.0, "S0", "第一句測試"), (pytest.approx(5.4), "S1", "第二句測試")]
    # 和應用程式下載的 LRC 逐位元組相同：只用 LF，Windows 上也不換成 CRLF
    assert b"\r" not in (out / "meeting.lrc").read_bytes()
    # 送進模型的是去靜音之後的語音視圖，不是原音檔
    assert fake.durations == [pytest.approx(7.2, abs=0.05)]
    # 暫存檔都清掉了，模型的轉接器也釋放了
    assert list(uploads.iterdir()) == []
    assert fake.released == 1


def test_chinese_transcript_is_written_before_the_traditional_output(
        fake, uploads, audio, tmp_path, no_prompt):
    # 錯字率量轉換前的結果（#242）：本機的模型寫的簡體與講者說的詞照寫，不做應用程式完成任務時
    # 的繁體輸出（#14，下載的會是「我們開會」「台灣的軟體」）
    fake.script = [[(0.0, 1.5, 0, "我们开会"), (3.0, 4.0, 1, "台湾的软件")]]
    out = tmp_path / "out"

    assert _run(audio, out, "--yes") == 0

    assert [line.text for line in lrc.read(out / "meeting.lrc").lines] == ["我们开会", "台湾的软件"]


def test_removes_silence_from_other_formats_in_a_fresh_data_folder(fake, tmp_path, monkeypatch,
                                                                   no_prompt):
    # 應用程式的暫存上傳區在 API 模組 import 時建立；這個指令不經 API，全新的資料夾裡還沒有它。
    # WAV 不必轉檔，其他格式要先由 ffmpeg 轉成 WAV 寫進暫存上傳區，資料夾不存在就轉不了，
    # 去靜音會悄悄退回送原音檔
    from app.core.config import get_settings

    settings = get_settings()
    data = tmp_path / "fresh-data"
    monkeypatch.setattr(settings, "temp_uploads_dir", str(data / "temp_uploads"))
    monkeypatch.setattr(settings, "audio_store_dir", str(data / "audio_store"))
    monkeypatch.setattr(settings, "vad_artifacts_dir", str(data / "vad_artifacts"))
    audio = tmp_path / "meeting.flac"
    audio.write_bytes(synthetic_audio("FLAC"))
    fake.script = [LINES]

    assert _run(audio, tmp_path / "out", "--yes") == 0

    # 送進模型的是去靜音之後的語音視圖，和應用程式相同
    assert fake.durations == [pytest.approx(7.2, abs=0.05)]
    assert list((data / "temp_uploads").iterdir()) == []


def test_manifest_records_the_run_without_any_transcript_text(fake, uploads, audio, tmp_path,
                                                             no_prompt):
    fake.script = [LINES]
    out = tmp_path / "out"

    assert _run(audio, out, "--yes") == 0

    text = (out / "meeting.manifest.json").read_text(encoding="utf-8")
    assert "第一句測試" not in text and "第二句測試" not in text
    manifest = json.loads(text)
    assert manifest["request"] == {"provider": "fake", "model": FAKE_MODEL, "language": "zh-TW"}
    assert manifest["audio"] == {
        "file": "meeting.wav",
        "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "duration_seconds": pytest.approx(12.0, abs=0.05),
    }
    assert manifest["code"] == {"commit": _git("rev-parse", "HEAD"),
                                "dirty": bool(_git("status", "--porcelain"))}
    assert manifest["outputs"] == {"transcript": "meeting.lrc"}

    environment = manifest["environment"]
    assert set(environment["packages"]) == {"torch", "transformers", "moss-transcribe-diarize"}
    # 測試環境沒有 CUDA；假供應商沒有釘住的模型權重
    assert environment["gpu"] is None
    assert environment["model_revisions"] == {}
    assert environment["settings"] == {
        "remove_silence": True,
        "speech_ratio_skip_threshold": 0.9,
        "single_pass_seconds": 600,
        "long_audio_split_threshold_seconds": 900.0,
        "local_moss_single_pass_max_seconds": 4200.0,
        "split_retry_min_seconds": 180,
    }

    run = manifest["run"]
    assert run["success"] is True and run["error"] is None
    assert run["segments"] == 2
    assert run["peak_vram_gb"] is None
    # rtf 取到小數 4 位、seconds 取到 3 位：假供應商只跑幾十毫秒，兩邊各自捨入的差距用相對誤差框不住
    assert run["rtf"] == pytest.approx(run["seconds"] / manifest["audio"]["duration_seconds"],
                                       abs=1e-4)
    # 各階段照進度訊息切開，從建立轉接器到轉錄結束，加起來就是整段耗時
    stages = run["stages"]
    assert stages[0]["stage"] == "建立供應商轉接器"
    assert all(stage["seconds"] >= 0 for stage in stages)
    assert sum(stage["seconds"] for stage in stages) == pytest.approx(run["seconds"], abs=0.01)


def test_progress_counters_fold_into_one_stage():
    from tools.eval.transcribe import FIRST_STAGE, _stages

    reports = [(0.0, FIRST_STAGE), (1.0, "準備音訊..."), (2.0, "MOSS 轉錄中 1/3 分鐘..."),
               (3.0, "MOSS 轉錄中 2/3 分鐘..."), (5.0, "MOSS 轉錄中 3/3 分鐘..."),
               (6.0, "Qwen3-ForcedAligner 強制對齊中..."), (6.5, "強制對齊中 1/2..."),
               (7.0, "強制對齊中 2/2..."), (8.0, "時間還原回原音檔...")]
    assert _stages(reports, end=8.5) == [
        {"stage": "建立供應商轉接器", "seconds": 1.0},
        {"stage": "準備音訊...", "seconds": 1.0},
        {"stage": "MOSS 轉錄中 #/# 分鐘...", "seconds": 4.0},
        # 模型名稱裡的數字不是計數
        {"stage": "Qwen3-ForcedAligner 強制對齊中...", "seconds": 0.5},
        {"stage": "強制對齊中 #/#...", "seconds": 1.5},
        {"stage": "時間還原回原音檔...", "seconds": 0.5},
    ]


def test_starts_without_the_scoring_dependencies(tmp_path):
    # 計分用的 opencc、rapidfuzz、pypinyin 在 requirements-dev.txt；只裝了應用程式依賴的
    # backend\.venv 也要能轉錄
    code = textwrap.dedent(f"""
        import sys
        for name in ("opencc", "rapidfuzz", "pypinyin"):
            sys.modules[name] = None  # import 時拋 ImportError
        from tools.eval import cli
        sys.exit(cli.main(["transcribe", "--audio", {str(tmp_path / "missing.wav")!r},
                           "--language", "zh-TW", "--out", {str(tmp_path / "out")!r}]))
    """)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                          encoding="utf-8", env=env)

    # 走到 transcribe 自己的檢查：找不到音檔
    assert done.returncode == 2, done.stderr
    assert "找不到音檔" in done.stderr


def test_peak_vram_comes_from_the_gpu_this_run_used(monkeypatch):
    from tools.eval.transcribe import _peak_vram_gb

    gib = 1024 ** 3
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True,
                                                 max_memory_reserved=lambda: int(5.5 * gib)))
    monkeypatch.setitem(sys.modules, "torch", torch)

    assert _peak_vram_gb() == 5.5


def test_asks_to_stop_other_gpu_work_before_starting(fake, uploads, audio, tmp_path, monkeypatch,
                                                     capsys):
    asked = []

    def cancel(prompt=""):
        asked.append(prompt)
        raise EOFError

    monkeypatch.setattr(builtins, "input", cancel)
    out = tmp_path / "out"

    assert _run(audio, out) == 1

    assert asked
    assert "local_worker" in capsys.readouterr().out
    # 使用者沒有確認：不建立轉接器、不轉錄、不寫任何檔案
    assert fake.opened == 0
    assert not out.exists()


def test_uses_only_the_first_gpu_unless_told_otherwise(fake, uploads, audio, tmp_path, no_prompt):
    fake.script = [LINES]

    assert _run(audio, tmp_path / "out", "--yes") == 0

    # 本機的 ASR 模型用 device_map="auto"，看得到幾張顯卡就攤到幾張
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0"


def test_refuses_more_than_one_gpu(fake, uploads, audio, tmp_path, monkeypatch, capsys, no_prompt):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    out = tmp_path / "out"

    assert _run(audio, out, "--yes") == 2

    assert "一張" in capsys.readouterr().err
    assert fake.opened == 0
    assert not out.exists()


def test_failed_transcription_writes_only_the_manifest(fake, uploads, audio, tmp_path, no_prompt):
    fake.script = [Fail("假供應商：顯存不足")]
    out = tmp_path / "out"

    assert _run(audio, out, "--yes") == 1

    assert not (out / "meeting.lrc").exists()
    run = json.loads((out / "meeting.manifest.json").read_text(encoding="utf-8"))["run"]
    assert run["success"] is False
    assert "顯存不足" in run["error"]


def test_refuses_providers_that_need_an_api_key(audio, tmp_path, capsys, no_prompt):
    out = tmp_path / "out"

    assert cli.main(["transcribe", "--audio", str(audio), "--provider", "google",
                     "--language", "zh-TW", "--out", str(out), "--yes"]) == 2

    assert "API 金鑰" in capsys.readouterr().err
    assert not out.exists()


def test_keeps_earlier_outputs(fake, uploads, audio, tmp_path, capsys, no_prompt):
    out = tmp_path / "out"
    out.mkdir()
    (out / "meeting.lrc").write_text("上一次的結果", encoding="utf-8")

    assert _run(audio, out, "--yes") == 2

    assert (out / "meeting.lrc").read_text(encoding="utf-8") == "上一次的結果"
    assert "meeting.lrc" in capsys.readouterr().err
    assert fake.opened == 0


def test_never_writes_into_the_reference_folder(fake, uploads, audio, tmp_path, monkeypatch,
                                                capsys, no_prompt):
    lab = tmp_path / "lab"
    references = lab / "data" / "eval"
    references.mkdir(parents=True)
    monkeypatch.setenv("AIT_LAB_DIR", str(lab))

    assert _run(audio, references, "--yes") == 2

    assert list(references.iterdir()) == []
    assert "標準答案" in capsys.readouterr().err
