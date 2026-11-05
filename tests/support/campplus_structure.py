"""用真的 torch 建 CAM++ 的網路，確認和權重檔對得上（tests/unit/test_campplus.py 另開直譯器執行）。

conftest 把 torch 換成假的，同一個行程裡建不了網路。沒裝 torch 時（CI 不裝 ML 依賴）結束碼是
:data:`NO_TORCH`，測試略過；網路不對時印出哪裡不同，結束碼 1。
"""

import sys
from pathlib import Path

NO_TORCH = 3
STATE_KEYS = 937
"""``campplus_cn_common.bin``（funasr/campplus e4b6ede）裡的張量數：參數加上 BatchNorm 的統計量。"""
STATE_NUMEL = 6_930_842
"""同一個檔案所有張量的元素總數。"""

try:
    import torch
except ImportError:
    sys.exit(NO_TORCH)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.provider.local import campplus  # noqa: E402

problems = []
state = campplus._network().state_dict()
if len(state) != STATE_KEYS:
    problems.append(f"張量數 {len(state)}，權重檔是 {STATE_KEYS}")
numel = sum(t.numel() for t in state.values())
if numel != STATE_NUMEL:
    problems.append(f"元素總數 {numel}，權重檔是 {STATE_NUMEL}")
for key in ("head.conv1.weight", "xvector.tdnn.linear.weight", "xvector.block3.tdnnd16.cam_layer.linear2.bias",
            "xvector.dense.nonlinear.batchnorm.running_mean"):
    if key not in state:
        problems.append(f"沒有 {key}")
model = campplus._network().eval()
with torch.inference_mode():
    shape = tuple(model(torch.randn(2, 150, campplus.FBANK_BINS)).shape)
if shape != (2, campplus.EMBEDDING_SIZE):
    problems.append(f"輸出的形狀是 {shape}")
print("\n".join(problems))
sys.exit(1 if problems else 0)
