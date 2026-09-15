"""實驗 B 的輸入：從每個版本裁出同一段落，建立與主研究相同結構的子目錄。

  EXCERPT_ROOT/denoised/{id}/{id}.wav   各版本同一時間段（保留原取樣率）
  EXCERPT_ROOT/00_analysis/             裁切後的 Silero 語音段與時長（供 compare_transcripts）

另加 00_original_16k：原檔轉 16kHz wav，等同正式流程處理 m4a 時 convert_to_wav 的產物
（.wav 輸入會被直接放行），用來重現「上傳 m4a」的路徑而不必重新壓縮成 m4a。
分流版本（有 vad_source.txt）一併裁切其 VAD 音檔並改寫指向。

用法：
  python tests\\denoise_study\\make_excerpts.py ROOT SOURCE_AUDIO --start 0 --duration 360
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def cut(src: Path, dst: Path, start: float, duration: float, sr: int | None = None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ss", str(start), "-t", str(duration), "-ac", "1"]
    if sr:
        cmd += ["-ar", str(sr)]
    subprocess.run(cmd + ["-c:a", "pcm_s16le", str(dst)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=360.0)
    args = parser.parse_args()
    root: Path = args.root
    s, d = args.start, args.duration
    ex_root = root / f"B_excerpt_{int(s // 60):02d}m{int(s % 60):02d}s-{int((s + d) // 60):02d}m{int((s + d) % 60):02d}s"

    cut(args.source, ex_root / "denoised" / "00_original_16k" / "00_original_16k.wav", s, d, sr=16000)
    for folder in sorted((root / "denoised").iterdir()):
        wav = folder / f"{folder.name}.wav"
        if folder.name == "_work" or not wav.exists():
            continue
        target = ex_root / "denoised" / folder.name / wav.name
        vad_source = folder / "vad_source.txt"
        if vad_source.exists():
            vad_src = Path(vad_source.read_text(encoding="utf-8").strip())
            vad_target = ex_root / "denoised" / vad_src.parent.name / vad_src.name
            if not vad_target.exists():
                cut(vad_src, vad_target, s, d)
            (target.parent).mkdir(parents=True, exist_ok=True)
            (target.parent / "vad_source.txt").write_text(str(vad_target), encoding="utf-8")
        if not target.exists():
            cut(wav, target, s, d)
        params = folder / "params.json"
        if params.exists():
            (target.parent / "params.json").write_text(params.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[裁切] {folder.name}", flush=True)

    speech = json.loads((root / "00_analysis" / "silero_segments_original.json").read_text(encoding="utf-8"))
    clipped = [[max(a, s) - s, min(b, s + d) - s] for a, b in speech if b > s and a < s + d]
    (ex_root / "00_analysis").mkdir(parents=True, exist_ok=True)
    (ex_root / "00_analysis" / "silero_segments_original.json").write_text(json.dumps(clipped), encoding="utf-8")
    (ex_root / "00_analysis" / "analysis.json").write_text(
        json.dumps({"duration_seconds": d, "excerpt_of": str(args.source), "start_seconds": s}), encoding="utf-8")
    print(ex_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
