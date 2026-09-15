"""各降噪版本的客觀音訊指標（與原檔同一組 speech / noise 幀比較）。

語音遮罩固定取自「原檔」的 Silero VAD，各版本都在同一批幀上量測，避免降噪
改變 VAD 判斷而讓數字不可比。全部以 16kHz 解碼（Qwen3-ASR 的特徵取樣率）。

每個版本輸出：
  speech_level / noise_level / snr       dBFS / dB
  delta_speech_db / delta_noise_db       相對原檔的增減（語音被削多少、噪音被砍多少）
  band_delta_speech_db                   語音幀在各頻帶的增減（>3dB 的損失代表過度抑制）
  pipeline_vad                           正式流程 RMS VAD 的判定（是否會啟用靜音移除）

用法（backend venv）：
  backend\\.venv\\Scripts\\python.exe tests\\denoise_study\\audio_metrics.py ROOT SOURCE_AUDIO
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_audio import db, decode, interval_mask, vad_segments  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(os.environ.get("AIT_BACKEND_DIR", REPO_ROOT / "backend"))
sys.path.insert(0, str(BACKEND_DIR))

SR = 16000
FRAME = 320          # 20ms
NPERSEG = 512
BANDS = [(0, 300), (300, 1000), (1000, 4000), (4000, 8000)]


def frame_power(x: np.ndarray) -> np.ndarray:
    n = len(x) // FRAME
    f = x[:n * FRAME].reshape(n, FRAME).astype(np.float64)
    return np.mean(f ** 2, axis=1)


def band_levels(x: np.ndarray, intervals) -> list[float]:
    hop = NPERSEG // 2
    win = np.hanning(NPERSEG)
    freqs = np.fft.rfftfreq(NPERSEG, 1 / SR)
    acc = np.zeros(len(freqs))
    count = 0
    for c0 in range(0, len(x) - NPERSEG, SR * 60):
        seg = x[c0:c0 + SR * 60 + NPERSEG].astype(np.float64)
        nfr = (len(seg) - NPERSEG) // hop + 1
        idx = np.arange(NPERSEG)[None, :] + hop * np.arange(nfr)[:, None]
        centers = (c0 + hop * np.arange(nfr) + NPERSEG / 2) / SR
        keep = interval_mask(centers, intervals) & (centers < (c0 + SR * 60) / SR)
        if keep.any():
            spec = np.abs(np.fft.rfft(seg[idx[keep]] * win, axis=1)) ** 2
            acc += spec.sum(axis=0)
            count += int(keep.sum())
    psd = acc / max(count, 1)
    return [float(db(psd[(freqs >= lo) & (freqs < hi)].sum())) for lo, hi in BANDS]


def pipeline_vad(path: Path) -> dict:
    """呼叫正式流程的 RMS VAD（extract_speech_segments）看語音佔比與是否跳過。"""
    from app.core.config import get_settings
    from app.services.vad.flows import extract_speech_segments
    from app.services.vad.models import VADProcessRequest
    from app.utils.audio import convert_to_wav

    with tempfile.TemporaryDirectory() as tmp:
        wav = convert_to_wav(path, Path(tmp))
        result = extract_speech_segments(VADProcessRequest(audio_path=str(wav), output_dir=tmp))
    threshold = get_settings().vad_speech_ratio_skip_threshold
    ratio = float(result.speech_ratio) if result.success else 1.0
    return {"speech_ratio": round(ratio, 4),
            "speech_seconds": round(float(result.total_speech_duration or 0), 1) if result.success else None,
            "silence_removal_used": bool(result.success and ratio < threshold)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    root: Path = args.root

    seg_cache = root / "00_analysis" / "silero_segments_original.json"
    if seg_cache.exists():
        speech = [tuple(s) for s in json.loads(seg_cache.read_text(encoding="utf-8"))]
    else:
        speech = vad_segments(args.source)
        seg_cache.write_text(json.dumps(speech), encoding="utf-8")

    variants = {"00_original_m4a": args.source}
    for folder in sorted((root / "denoised").iterdir()):
        wav = folder / f"{folder.name}.wav"
        if folder.name != "_work" and wav.exists():
            variants[folder.name] = wav

    out_path = root / "report" / "audio_metrics.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}

    ref = None
    for vid, path in variants.items():
        x = decode(path, SR)
        fp = frame_power(x)
        times = (np.arange(len(fp)) + 0.5) * FRAME / SR
        sm = interval_mask(times, speech)
        nm = ~interval_mask(times, speech, pad=0.3)
        ps, pn = fp[sm].mean(), fp[nm].mean()
        row = {
            "speech_level_dbfs": round(float(db(ps)), 2),
            "noise_level_dbfs": round(float(db(pn)), 2),
            "noise_median_frame_dbfs": round(float(np.median(db(fp[nm]))), 2),
            "snr_db": round(float(db(max(ps - pn, 1e-20) / pn)), 2),
            "band_speech_db": [round(v, 2) for v in band_levels(x, speech)],
        }
        if ref is None:
            ref = row
        row["delta_speech_db"] = round(row["speech_level_dbfs"] - ref["speech_level_dbfs"], 2)
        row["delta_noise_db"] = round(row["noise_level_dbfs"] - ref["noise_level_dbfs"], 2)
        row["band_delta_speech_db"] = dict(zip(
            [f"{lo}-{hi}" for lo, hi in BANDS],
            [round(a - b, 2) for a, b in zip(row["band_speech_db"], ref["band_speech_db"])]))
        row["pipeline_vad"] = pipeline_vad(path)
        results[vid] = row
        print(f"{vid:24s} speech {row['speech_level_dbfs']:7.2f}  noise {row['noise_level_dbfs']:7.2f}  "
              f"snr {row['snr_db']:6.2f}  dS {row['delta_speech_db']:+6.2f}  dN {row['delta_noise_db']:+7.2f}  "
              f"bands {row['band_delta_speech_db']}  vad {row['pipeline_vad']}", flush=True)

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
