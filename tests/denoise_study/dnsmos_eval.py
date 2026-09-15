"""DNSMOS P.835（SIG 語音失真 / BAK 背景噪音 / OVRL 整體）+ P.808 無參考音質評分。

所有版本評同一組片段：從原檔 Silero VAD 語音最密集的 10s 視窗中均勻取 N 段。
SIG 下降 = 降噪傷到人聲（對 ASR 最危險）；BAK 上升 = 背景變乾淨。

用法（denoise venv，需要 speechmos）：
  python tests\\denoise_study\\dnsmos_eval.py ROOT SOURCE_AUDIO [--clips 40]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from speechmos import dnsmos

SR = 16000
CLIP = 10.0


def decode16(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--clips", type=int, default=40)
    args = parser.parse_args()
    root: Path = args.root

    speech = json.loads((root / "00_analysis" / "silero_segments_original.json").read_text(encoding="utf-8"))
    total = json.loads((root / "00_analysis" / "analysis.json").read_text(encoding="utf-8"))["duration_seconds"]
    starts = []
    for i in range(int(total // CLIP)):
        lo, hi = i * CLIP, (i + 1) * CLIP
        if sum(max(0.0, min(e, hi) - max(s, lo)) for s, e in speech) >= 7.0:
            starts.append(lo)
    picks = [starts[int(k)] for k in np.linspace(0, len(starts) - 1, min(args.clips, len(starts)))]

    variants = {"00_original_m4a": args.source}
    for folder in sorted((root / "denoised").iterdir()):
        wav = folder / f"{folder.name}.wav"
        if folder.name != "_work" and wav.exists():
            variants[folder.name] = wav

    out_path = root / "report" / "dnsmos.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for vid, path in variants.items():
        if vid in results and results[vid].get("clips") == len(picks):
            continue
        x = decode16(path)
        scores = []
        for s in picks:
            clip = np.clip(x[int(s * SR):int((s + CLIP) * SR)], -1.0, 1.0)
            scores.append(dnsmos.run(clip, SR))
        results[vid] = {k: round(float(np.mean([sc[k] for sc in scores])), 3)
                        for k in ("sig_mos", "bak_mos", "ovrl_mos", "p808_mos")} | {"clips": len(picks)}
        print(f"{vid:24s} {results[vid]}", flush=True)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
