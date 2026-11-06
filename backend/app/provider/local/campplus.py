"""說話者嵌入：CAM++（中文 20 萬位說話者訓練，192 維），給分段轉錄對齊各段的說話者編號（#93；Gemini 是 #335）。

模型的網路照 3D-Speaker 的 ``speakerlab/models/campplus``（DTDNN.py、layers.py，commit
065629c313eaf1a01c65c640c46d77e61e9607b4，Apache License 2.0，
Copyright 3D-Speaker，https://github.com/modelscope/3D-Speaker）改寫：只留推論用得到的部分
（拿掉訓練時的 gradient checkpointing 與權重初始化），模組的名稱與層次不變，權重檔的 key 才對得上。
特徵照它的 ``speakerlab/bin/infer_sv.py``：16 kHz 單聲道、80 維 Kaldi fbank（dither 0）、減去平均。

權重是 Hugging Face 的 ``funasr/campplus``（:data:`weights.CAMPPLUS_MODEL_ID`，釘住 revision），和
ModelScope 的 ``iic/speech_campplus_sv_zh-cn_16k-common`` 是同一個檔案（SHA-256 相同）。用
``torch.load(weights_only=True)`` 載入：只讀張量，不執行權重檔裡的程式。

在 CPU 上跑，不佔顯存：各段轉錄完、合併時才用到，模型只有約 700 萬個參數。torch 與 torchaudio 在第一次
建立 :class:`CamPlusPlus` 時才匯入：單次轉完的音檔用不到它。

本機 MOSS 模型的必要權重包含它（設定頁下載）；只用 Gemini 的人多半沒下載過，第一次要對齊時在任務裡下載，
狀態說明寫明（#335）。
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Sequence, Tuple

from app.provider.local import weights

if TYPE_CHECKING:
    import numpy as np

SAMPLE_RATE = 16000
FBANK_BINS = 80
EMBEDDING_SIZE = 192


class CamPlusPlus:
    """CAM++ 說話者嵌入（:class:`app.services.speaker_alignment.SpeakerEmbedder`）。

    建立時載入模型權重（本機沒有完整的權重時照 :func:`weights.resolve_repo` 下載，先用 ``report`` 告訴使用者）；
    下載或載入失敗時拋出原本的錯誤，由分段轉錄退回不對齊的做法。
    """

    def __init__(self, report: Callable[[str], None] = lambda text: None) -> None:
        import torch

        repo = weights.CAMPPLUS_MODEL_ID
        if not weights.repo_is_ready(repo):
            report(f"第一次對齊各段的說話者：從 Hugging Face 下載說話者嵌入（CAM++）的權重，"
                   f"約 {round(weights.REPO_SIZE_GB[repo] * 1000)} MB...")
        path = Path(weights.resolve_repo(repo)) / weights.WEIGHTS_FILES[repo]
        state = torch.load(path, map_location="cpu", weights_only=True)
        model = _network()
        model.load_state_dict(state)
        model.eval()
        self._model = model

    def embed(self, audio: Path, spans: Sequence[Tuple[float, float]]) -> List[Optional[np.ndarray]]:
        """``audio`` 裡每一段（起, 迄，秒）的嵌入（192 維、長度 1）；讀不到聲音的段是 None。"""
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio

        out: List[Optional[np.ndarray]] = []
        with sf.SoundFile(str(audio)) as file:
            rate = file.samplerate
            for start, end in spans:
                file.seek(max(0, int(start * rate)))
                samples = file.read(max(0, int((end - start) * rate)), dtype="float32",
                                    always_2d=True)
                if len(samples) < rate * 0.1:
                    out.append(None)
                    continue
                wave = torch.from_numpy(np.ascontiguousarray(samples[:, 0])).unsqueeze(0)
                if rate != SAMPLE_RATE:
                    wave = torchaudio.functional.resample(wave, rate, SAMPLE_RATE)
                with torch.inference_mode():
                    feature = torchaudio.compliance.kaldi.fbank(
                        wave, num_mel_bins=FBANK_BINS, sample_frequency=SAMPLE_RATE, dither=0.0)
                    feature = feature - feature.mean(0, keepdim=True)
                    vector = self._model(feature.unsqueeze(0))[0].numpy().astype(np.float64)
                norm = float(np.linalg.norm(vector))
                out.append(vector / norm if norm > 0 else None)
        return out


# ── 網路（照 3D-Speaker 的 DTDNN.py、layers.py 改寫） ───────────────────────────

def _network() -> Any:
    """CAM++ 的網路：CAMPPlus(feat_dim=80, embedding_size=192)，和 3D-Speaker 的 CAMPPLUS_COMMON 相同。"""
    import torch
    import torch.nn.functional as F
    from torch import nn

    def nonlinear(config: str, channels: int) -> nn.Sequential:
        layers = nn.Sequential()
        for name in config.split("-"):
            if name == "relu":
                layers.add_module("relu", nn.ReLU(inplace=True))
            elif name == "batchnorm":
                layers.add_module("batchnorm", nn.BatchNorm1d(channels))
            elif name == "batchnorm_":
                layers.add_module("batchnorm", nn.BatchNorm1d(channels, affine=False))
            else:
                raise ValueError(f"Unexpected module ({name}).")
        return layers

    class StatsPool(nn.Module):
        def forward(self, x):
            return torch.cat([x.mean(dim=-1), x.std(dim=-1, unbiased=True)], dim=-1)

    class TDNNLayer(nn.Module):
        def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0, dilation=1,
                     bias=False, config_str="batchnorm-relu"):
            super().__init__()
            if padding < 0:
                padding = (kernel_size - 1) // 2 * dilation
            self.linear = nn.Conv1d(in_channels, out_channels, kernel_size, stride=stride,
                                    padding=padding, dilation=dilation, bias=bias)
            self.nonlinear = nonlinear(config_str, out_channels)

        def forward(self, x):
            return self.nonlinear(self.linear(x))

    class CAMLayer(nn.Module):
        def __init__(self, bn_channels, out_channels, kernel_size, stride, padding, dilation, bias,
                     reduction=2):
            super().__init__()
            self.linear_local = nn.Conv1d(bn_channels, out_channels, kernel_size, stride=stride,
                                          padding=padding, dilation=dilation, bias=bias)
            self.linear1 = nn.Conv1d(bn_channels, bn_channels // reduction, 1)
            self.relu = nn.ReLU(inplace=True)
            self.linear2 = nn.Conv1d(bn_channels // reduction, out_channels, 1)
            self.sigmoid = nn.Sigmoid()

        def forward(self, x):
            y = self.linear_local(x)
            context = x.mean(-1, keepdim=True) + self.seg_pooling(x)
            context = self.relu(self.linear1(context))
            return y * self.sigmoid(self.linear2(context))

        @staticmethod
        def seg_pooling(x, seg_len=100):
            seg = F.avg_pool1d(x, kernel_size=seg_len, stride=seg_len, ceil_mode=True)
            shape = seg.shape
            seg = seg.unsqueeze(-1).expand(*shape, seg_len).reshape(*shape[:-1], -1)
            return seg[..., :x.shape[-1]]

    class CAMDenseTDNNLayer(nn.Module):
        def __init__(self, in_channels, out_channels, bn_channels, kernel_size, stride=1, dilation=1,
                     bias=False, config_str="batchnorm-relu"):
            super().__init__()
            padding = (kernel_size - 1) // 2 * dilation
            self.nonlinear1 = nonlinear(config_str, in_channels)
            self.linear1 = nn.Conv1d(in_channels, bn_channels, 1, bias=False)
            self.nonlinear2 = nonlinear(config_str, bn_channels)
            self.cam_layer = CAMLayer(bn_channels, out_channels, kernel_size, stride=stride,
                                      padding=padding, dilation=dilation, bias=bias)

        def forward(self, x):
            return self.cam_layer(self.nonlinear2(self.linear1(self.nonlinear1(x))))

    class CAMDenseTDNNBlock(nn.ModuleList):
        def __init__(self, num_layers, in_channels, out_channels, bn_channels, kernel_size,
                     dilation=1, config_str="batchnorm-relu"):
            super().__init__()
            for i in range(num_layers):
                self.add_module(f"tdnnd{i + 1}", CAMDenseTDNNLayer(
                    in_channels + i * out_channels, out_channels, bn_channels, kernel_size,
                    dilation=dilation, config_str=config_str))

        def forward(self, x):
            for layer in self:
                x = torch.cat([x, layer(x)], dim=1)
            return x

    class TransitLayer(nn.Module):
        def __init__(self, in_channels, out_channels, bias=True, config_str="batchnorm-relu"):
            super().__init__()
            self.nonlinear = nonlinear(config_str, in_channels)
            self.linear = nn.Conv1d(in_channels, out_channels, 1, bias=bias)

        def forward(self, x):
            return self.linear(self.nonlinear(x))

    class DenseLayer(nn.Module):
        def __init__(self, in_channels, out_channels, bias=False, config_str="batchnorm-relu"):
            super().__init__()
            self.linear = nn.Conv1d(in_channels, out_channels, 1, bias=bias)
            self.nonlinear = nonlinear(config_str, out_channels)

        def forward(self, x):
            if len(x.shape) == 2:
                x = self.linear(x.unsqueeze(dim=-1)).squeeze(dim=-1)
            else:
                x = self.linear(x)
            return self.nonlinear(x)

    class BasicResBlock(nn.Module):
        expansion = 1

        def __init__(self, in_planes, planes, stride=1):
            super().__init__()
            self.conv1 = nn.Conv2d(in_planes, planes, kernel_size=3, stride=(stride, 1), padding=1,
                                   bias=False)
            self.bn1 = nn.BatchNorm2d(planes)
            self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=1, padding=1, bias=False)
            self.bn2 = nn.BatchNorm2d(planes)
            self.shortcut = nn.Sequential()
            if stride != 1 or in_planes != planes:
                self.shortcut = nn.Sequential(
                    nn.Conv2d(in_planes, planes, kernel_size=1, stride=(stride, 1), bias=False),
                    nn.BatchNorm2d(planes))

        def forward(self, x):
            out = F.relu(self.bn1(self.conv1(x)))
            out = self.bn2(self.conv2(out))
            return F.relu(out + self.shortcut(x))

    class FCM(nn.Module):
        def __init__(self, num_blocks=(2, 2), m_channels=32, feat_dim=80):
            super().__init__()
            self.in_planes = m_channels
            self.conv1 = nn.Conv2d(1, m_channels, kernel_size=3, stride=1, padding=1, bias=False)
            self.bn1 = nn.BatchNorm2d(m_channels)
            self.layer1 = self._make_layer(m_channels, num_blocks[0], stride=2)
            self.layer2 = self._make_layer(m_channels, num_blocks[1], stride=2)
            self.conv2 = nn.Conv2d(m_channels, m_channels, kernel_size=3, stride=(2, 1), padding=1,
                                   bias=False)
            self.bn2 = nn.BatchNorm2d(m_channels)
            self.out_channels = m_channels * (feat_dim // 8)

        def _make_layer(self, planes, num_blocks, stride):
            layers = []
            for each in [stride] + [1] * (num_blocks - 1):
                layers.append(BasicResBlock(self.in_planes, planes, each))
                self.in_planes = planes
            return nn.Sequential(*layers)

        def forward(self, x):
            out = F.relu(self.bn1(self.conv1(x.unsqueeze(1))))
            out = self.layer2(self.layer1(out))
            out = F.relu(self.bn2(self.conv2(out)))
            shape = out.shape
            return out.reshape(shape[0], shape[1] * shape[2], shape[3])

    class CAMPPlus(nn.Module):
        def __init__(self, feat_dim=FBANK_BINS, embedding_size=EMBEDDING_SIZE, growth_rate=32,
                     bn_size=4, init_channels=128, config_str="batchnorm-relu"):
            super().__init__()
            self.head = FCM(feat_dim=feat_dim)
            channels = self.head.out_channels
            self.xvector = nn.Sequential(OrderedDict([
                ("tdnn", TDNNLayer(channels, init_channels, 5, stride=2, dilation=1, padding=-1,
                                   config_str=config_str)),
            ]))
            channels = init_channels
            for i, (num_layers, kernel_size, dilation) in enumerate(
                    zip((12, 24, 16), (3, 3, 3), (1, 2, 2), strict=True)):
                self.xvector.add_module(f"block{i + 1}", CAMDenseTDNNBlock(
                    num_layers, channels, growth_rate, bn_size * growth_rate, kernel_size,
                    dilation=dilation, config_str=config_str))
                channels = channels + num_layers * growth_rate
                self.xvector.add_module(f"transit{i + 1}", TransitLayer(
                    channels, channels // 2, bias=False, config_str=config_str))
                channels //= 2
            self.xvector.add_module("out_nonlinear", nonlinear(config_str, channels))
            self.xvector.add_module("stats", StatsPool())
            self.xvector.add_module("dense", DenseLayer(channels * 2, embedding_size,
                                                        config_str="batchnorm_"))

        def forward(self, x):
            return self.xvector(self.head(x.permute(0, 2, 1)))  # (B,T,F) => (B,F,T)

    return CAMPPlus()
