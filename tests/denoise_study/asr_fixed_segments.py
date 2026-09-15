"""實驗 A：固定切段的 Qwen3-ASR 比較（全長、所有版本、成對可比）。

完整 local 流程在本機一個 37 分鐘檔要約 5 小時（VibeVoice 權重約一半降載 CPU，
每個生成 token 都要搬權重過 PCIe），13 個版本全跑不切實際；而 Qwen3-ASR 1.7B 可整個
放進 GPU、很快。此實驗把「分離」固定住，只量測降噪對「轉錄」的影響：

  1. 以原檔 Silero VAD 語音段合併成 ≤20s 的語句塊（間隔 <0.6s 才合併），所有版本共用
  2. 每個版本照正式流程先轉 mono 24kHz（_to_mono_24k 同參數），依同一組時間切塊
  3. 用與正式流程逐行一致的 Qwen3-ASR 解碼（greedy，language=Chinese），另記 token log 機率

輸出 ROOT/asr_fixed/{id}.json；chunks.json 為共用切塊。

用法（backend venv）：
  backend\\.venv\\Scripts\\python.exe tests\\denoise_study\\asr_fixed_segments.py ROOT SOURCE_AUDIO [--only id ...]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_local_pipeline as rlp  # noqa: E402 — 同時把 backend 放進 sys.path

MAX_CHUNK = 20.0
MERGE_GAP = 0.6
PAD = 0.15
MIN_CHUNK = 0.4


def build_chunks(speech: list, total: float) -> list[dict]:
    chunks: list[list[float]] = []
    for s, e in speech:
        if chunks and s - chunks[-1][1] < MERGE_GAP and e - chunks[-1][0] <= MAX_CHUNK:
            chunks[-1][1] = e
        else:
            chunks.append([s, e])
    out = []
    for s, e in chunks:
        # 單一 Silero 段超過上限時等長切開（極少見）
        n = max(1, int((e - s) // MAX_CHUNK) + (1 if (e - s) % MAX_CHUNK else 0))
        step = (e - s) / n
        for k in range(n):
            a, b = s + k * step, s + (k + 1) * step
            if b - a >= MIN_CHUNK:
                out.append({"Start": round(max(0.0, a - PAD), 3), "End": round(min(total, b + PAD), 3), "Speaker": 0})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--lang", default="zh-TW")
    args = parser.parse_args()
    root: Path = args.root

    from app.provider.local import asr
    from app.utils.binaries import ffmpeg_bin

    analysis = json.loads((root / "00_analysis" / "analysis.json").read_text(encoding="utf-8"))
    speech = json.loads((root / "00_analysis" / "silero_segments_original.json").read_text(encoding="utf-8"))
    chunks = build_chunks(speech, analysis["duration_seconds"])
    out_dir = root / "asr_fixed"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    print(f"{len(chunks)} 塊，總長 {sum(c['End'] - c['Start'] for c in chunks):.0f}s", flush=True)

    variants = {"00_original_m4a": args.source}
    for folder in sorted((root / "denoised").iterdir()):
        wav = folder / f"{folder.name}.wav"
        # 13 分流版本的音訊與 02 相同（差別只在 VAD），固定切段實驗中不重複跑
        if folder.name != "_work" and wav.exists() and not (folder / "vad_source.txt").exists():
            variants[folder.name] = wav
    if args.only:
        variants = {k: v for k, v in variants.items() if k in args.only}

    language = asr._LANGUAGE_MAP.get(args.lang.strip().lower())
    for vid, path in variants.items():
        target = out_dir / f"{vid}.json"
        if target.exists():
            print(f"[略過] {vid}", flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix="ait_asrfix_") as tmp:
            src = Path(path)
            if src.suffix.lower() != ".wav":
                # 正式流程對非 wav 先轉 16kHz（convert_to_wav）再轉 24kHz，照做
                wav16 = Path(tmp) / "input_16k.wav"
                subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(src), "-ar", "16000", "-ac", "1",
                                str(wav16)], check=True)
                src = wav16
            wav24 = Path(tmp) / "input_24k.wav"
            subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(src), "-ac", "1",
                            "-ar", str(asr.DIARIZATION_SAMPLE_RATE), str(wav24)], check=True)
            started = time.time()
            entries = rlp.scored_transcribe_segments(asr, wav24, chunks, language)
        by_start = {(round(e["start"], 3), round(e["end"], 3)): e for e in entries}
        rows = []
        for i, c in enumerate(chunks):
            e = by_start.get((c["Start"], c["End"]), {})
            rows.append({"i": i, "start": c["Start"], "end": c["End"], "text": e.get("text", ""),
                         "logprob_sum": e.get("logprob_sum"), "n_tokens": e.get("n_tokens"),
                         "min_logprob": e.get("min_logprob")})
        scored = [r for r in rows if r["n_tokens"]]
        summary = {
            "elapsed_seconds": round(time.time() - started, 1),
            "empty_chunks": sum(1 for r in rows if not r["text"]),
            "token_mean_logprob": round(sum(r["logprob_sum"] for r in scored) / sum(r["n_tokens"] for r in scored), 4),
            "chunk_mean_logprob": round(sum(r["logprob_sum"] / r["n_tokens"] for r in scored) / len(scored), 4),
        }
        target.write_text(json.dumps({"variant": vid, "summary": summary, "chunks": rows},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[完成] {vid:22s} {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
