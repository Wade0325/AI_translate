"""設定頁「複製診斷資訊」的各項怎麼讀出來（#24）：作業系統的版本名稱、驅動與 ffmpeg 的版本。

整段文字與去識別由 tests/integration/test_diagnostics_api.py 透過 API 檢查。
"""
import sys

import pytest

from app.services import diagnostics


@pytest.mark.parametrize(("system", "reported", "version", "expected"), [
    # 免安裝版的 Python 3.11 在 Windows 11 上回報 10：組建號 22000 以上是 Windows 11
    ("Windows", "10", "10.0.22000", "11"),
    ("Windows", "10", "10.0.26100", "11"),
    ("Windows", "10", "10.0.19045", "10"),
    ("Windows", "11", "10.0.26100", "11"),
    ("Windows", "10", "10.0", "10"),
    ("Linux", "6.8.0-45-generic", "#45-Ubuntu SMP", "6.8.0-45-generic"),
])
def test_release(system, reported, version, expected):
    assert diagnostics.release(system, reported, version) == expected


@pytest.mark.parametrize(("output", "expected"), [
    ("576.02\n", "576.02"),
    ("576.02\n576.02\n", "576.02"),  # 兩張卡時每張一行，驅動是同一個
    ("", None),
    (None, None),
])
def test_nvidia_driver_version(monkeypatch, output, expected):
    monkeypatch.setattr(diagnostics, "_run", lambda *command: output)

    assert diagnostics.nvidia_driver_version() == expected


@pytest.mark.parametrize(("output", "expected"), [
    ("ffmpeg version n7.1.1-20250101 Copyright (c) 2000-2025 the FFmpeg developers\n"
     "built with gcc 14.2.0\nconfiguration: --enable-shared\n", "n7.1.1-20250101"),
    ("ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers\n",
     "6.1.1-3ubuntu5"),
    ("something else\n", None),
    ("ffmpeg version", None),
    (None, None),
])
def test_ffmpeg_version(monkeypatch, output, expected):
    monkeypatch.setattr(diagnostics, "_run", lambda *command: output)

    assert diagnostics.ffmpeg_version() == expected


class TestRun:
    """問不到時（沒裝、失敗、卡住）一律是 None，診斷資訊照樣產生。"""

    def test_returns_the_output(self):
        assert diagnostics._run(sys.executable, "-c", "print('576.02')") == "576.02\n"

    def test_missing_command(self):
        assert diagnostics._run("no-such-command-for-diagnostics") is None

    def test_failed_command(self):
        assert diagnostics._run(sys.executable, "-c", "import sys; sys.exit(9)") is None

    def test_command_that_hangs(self, monkeypatch):
        monkeypatch.setattr(diagnostics, "COMMAND_TIMEOUT_SECONDS", 0.5)

        assert diagnostics._run(sys.executable, "-c", "import time; time.sleep(30)") is None


def test_free_space_of_a_missing_folder(tmp_path):
    assert diagnostics.free_space(tmp_path / "not-there") == "讀不到"
