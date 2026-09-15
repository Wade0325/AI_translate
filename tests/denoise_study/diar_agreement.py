"""實驗 B 的說話者分離比較：各版本的 VibeVoice 分離結果在同一時間軸上彼此一致到什麼程度。

沒有人工標註，無法算 DER；改量：
  speakers              偵測到的說話者數（本錄音為 2 人）
  speech_coverage       原檔 Silero 語音幀中被分離結果涵蓋的比例（漏分離偵測）
  agreement_vs_ref      與對照版本在雙方都有標籤的幀上、最佳說話者對應後的一致率
  speaker_share         各說話者時間佔比（主講者/聆聽者比例是否穩定）
  turns                 說話者切換次數

分離片段時間在「送進模型的音檔」時間軸上；若該版本啟用了靜音移除，依 vad_segments.json
換算回片段原始時間軸（與 flows.remap_lrc_timestamps 同邏輯）。

用法：
  python tests\\denoise_study\\diar_agreement.py EXCERPT_ROOT [--ref 00_original_16k]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

STEP = 0.1


def remapper(vad_segments: list[dict]):
    if not vad_segments:
        return lambda t: t
    durs = [s["end"] - s["start"] for s in vad_segments]
    cum = np.concatenate([[0.0], np.cumsum(durs)])

    def remap(t: float) -> float:
        i = int(np.searchsorted(cum, t, side="right") - 1)
        i = min(max(i, 0), len(vad_segments) - 1)
        return vad_segments[i]["start"] + (t - cum[i])
    return remap


def grid_labels(folder: Path, total: float) -> tuple[np.ndarray, dict]:
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    diar = json.loads((folder / "diarization.json").read_text(encoding="utf-8"))
    vad_segments = json.loads((folder / "vad_segments.json").read_text(encoding="utf-8"))
    used = bool(run.get("vad")) and run["vad"].get("speech_ratio", 1) < run.get("vad_skip_threshold", 0.9)
    remap = remapper(vad_segments if used else [])
    labels = np.full(int(total / STEP) + 1, -1, dtype=int)
    for call in diar:  # 片段實驗不會切半，只有一次呼叫
        for seg in call["segments"]:
            a, b = remap(float(seg.get("Start", 0))), remap(float(seg.get("End", 0)))
            labels[int(a / STEP):int(b / STEP)] = int(seg.get("Speaker", 0))
    return labels, {"silence_removal_used": used}


def agreement(a: np.ndarray, b: np.ndarray) -> float | None:
    both = (a >= 0) & (b >= 0)
    if not both.any():
        return None
    la, lb = np.unique(a[both]), np.unique(b[both])
    conf = np.array([[np.sum((a[both] == x) & (b[both] == y)) for y in lb] for x in la])
    r, c = linear_sum_assignment(-conf)
    return float(conf[r, c].sum() / both.sum())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--ref", default="00_original_16k")
    args = parser.parse_args()
    root: Path = args.root

    total = json.loads((root / "00_analysis" / "analysis.json").read_text(encoding="utf-8"))["duration_seconds"]
    speech = json.loads((root / "00_analysis" / "silero_segments_original.json").read_text(encoding="utf-8"))
    speech_mask = np.zeros(int(total / STEP) + 1, dtype=bool)
    for s, e in speech:
        speech_mask[int(s / STEP):int(e / STEP)] = True

    grids, info = {}, {}
    for folder in sorted((root / "transcripts").iterdir()):
        if (folder / "transcript.lrc").exists() and (folder / "diarization.json").exists():
            grids[folder.name], info[folder.name] = grid_labels(folder, total)

    results = {}
    ref = grids.get(args.ref)
    for vid, g in grids.items():
        labeled = g >= 0
        spk, counts = np.unique(g[labeled], return_counts=True)
        turns = int(np.sum((g[1:] != g[:-1]) & (g[1:] >= 0) & (g[:-1] >= 0)))
        results[vid] = {
            **info[vid],
            "speakers": int(len(spk)),
            "speech_coverage": round(float((labeled & speech_mask).sum() / speech_mask.sum()), 4),
            "labeled_nonspeech_seconds": round(float((labeled & ~speech_mask).sum() * STEP), 1),
            "speaker_share": {int(s): round(float(c / counts.sum()), 3) for s, c in zip(spk, counts)},
            "turns": turns,
            "agreement_vs_ref": round(agreement(g, ref), 4) if ref is not None and vid != args.ref else None,
        }
    matrix = {a: {b: (round(agreement(grids[a], grids[b]), 4) if a != b else 1.0) for b in grids} for a in grids}
    out = root / "report"
    out.mkdir(exist_ok=True)
    (out / "diarization_agreement.json").write_text(
        json.dumps({"ref": args.ref, "variants": results, "matrix": matrix}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    for vid, r in results.items():
        print(f"{vid:22s} spk {r['speakers']}  cov {r['speech_coverage']:.3f}  share {r['speaker_share']}  "
              f"turns {r['turns']}  agree {r['agreement_vs_ref']}  vad {r['silence_removal_used']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
