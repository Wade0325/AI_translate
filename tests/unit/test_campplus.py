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
