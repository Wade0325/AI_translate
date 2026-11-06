"""CAM++ 的網路（#93）：照 3D-Speaker 改寫的網路和權重檔對得上。

conftest 把 torch 換成假的，另開乾淨的直譯器跑 tests/support/campplus_structure.py。要真的 torch：CI 不裝
ML 依賴，那裡略過；本機的 backend\\.venv（照 requirements-standalone.txt 安裝）會跑。權重檔不進 repo，只比
網路的結構（參數的名稱與數量、輸出的維度）；實際的權重在 GPU 驗證時載入。
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "support" / "campplus_structure.py"
NO_TORCH = 3


def test_network_matches_the_weights_file():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode == NO_TORCH:
        pytest.skip("沒裝 torch")
    assert result.returncode == 0, result.stdout + result.stderr


class TestFirstUse:
    """只用 Gemini 的人多半沒下載過本機模型（#335）：第一次要對齊時在任務裡下載權重，下載前先告訴使用者。

    torch 是 conftest 換上的假的，網路也換成假的；取得權重（resolve_repo：本機沒有時下載）也是假的，只記下
    什麼時候呼叫。"""

    @pytest.fixture
    def events(self, monkeypatch, tmp_path):
        from unittest.mock import MagicMock

        from app.provider.local import campplus, weights

        happened: list[str] = []
        monkeypatch.setattr(weights, "resolve_repo",
                            lambda repo: happened.append(f"取得權重 {repo}") or str(tmp_path))
        monkeypatch.setattr(campplus, "_network", MagicMock)
        return happened

    def test_says_it_downloads_the_weights_before_it_does(self, monkeypatch, events):
        from app.provider.local import campplus, weights

        monkeypatch.setattr(weights, "repo_is_ready", lambda repo: False)

        campplus.CamPlusPlus(events.append)

        assert events == [
            "第一次對齊各段的說話者：從 Hugging Face 下載說話者嵌入（CAM++）的權重，約 30 MB...",
            "取得權重 funasr/campplus"]

    def test_says_nothing_when_the_weights_are_already_there(self, monkeypatch, events):
        from app.provider.local import campplus, weights

        monkeypatch.setattr(weights, "repo_is_ready", lambda repo: True)

        campplus.CamPlusPlus(events.append)

        assert events == ["取得權重 funasr/campplus"]


def test_a_window_past_the_end_of_the_audio_has_no_embedding(tmp_path):
    # Gemini 寫的時間可能超過送進去的音檔（#335）：整個在結尾之後的窗沒有嵌入，不讓整個對齊失敗
    # （soundfile 跳到結尾之後會拋錯）。這一窗在讀聲音時就停下，用不到 torch
    import numpy as np
    import soundfile as sf

    from app.provider.local import campplus

    audio = tmp_path / "chunk.wav"
    sf.write(str(audio), np.zeros(16000, dtype="float32"), 16000)
    embedder = object.__new__(campplus.CamPlusPlus)

    assert embedder.embed(audio, [(2.0, 4.0)]) == [None]
