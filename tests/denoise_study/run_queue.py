"""依序對所有降噪版本跑完整 local 轉錄（GPU 一次只跑一件事，避免 OOM）。

每跑完一個版本就重新掃描：ROOT/queue_order.txt 決定優先順序（每行一個 id，可在
執行中編輯），之後才輪到清單外、已產生音檔但尚未轉錄的版本。已有 transcript.lrc
的版本略過，所以中斷後重跑會接續。

  --prepare ID ...   轉錄前先用 denoise venv 產生這些版本（GPU 降噪模型在此階段獨佔 GPU）

用法（backend venv）：
  backend\\.venv\\Scripts\\python.exe tests\\denoise_study\\run_queue.py ROOT SOURCE_AUDIO [--prepare 08_mossformer2_48k ...]
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DENOISE_PY = Path(r"D:\AI_translate\models\denoise_tools\venv\Scripts\python.exe")


def log(msg: str) -> None:
    print(f"{datetime.datetime.now():%H:%M:%S} {msg}", flush=True)


def pending(root: Path, order_file: Path) -> list[str]:
    ready = {f.name for f in (root / "denoised").iterdir()
             if f.is_dir() and (f / f"{f.name}.wav").exists()}
    done = {f.name for f in (root / "transcripts").iterdir() if (f / "transcript.lrc").exists()} \
        if (root / "transcripts").exists() else set()
    failed = {f.name for f in (root / "transcripts").iterdir() if (f / "error.txt").exists()} \
        if (root / "transcripts").exists() else set()
    order =[l.strip() for l in order_file.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")] if order_file.exists() else []
    todo = [v for v in order if v in ready and v not in done and v not in failed]
    todo += sorted(v for v in ready - done - failed if v not in todo)
    return todo


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--prepare", nargs="*", default=[])
    parser.add_argument("--order", type=Path, default=HERE / "queue_order.txt")
    args = parser.parse_args()
    env = os.environ | {"PYTHONIOENCODING": "utf-8"}

    if args.prepare:
        log(f"產生降噪版本: {args.prepare}")
        # ClearerVoice 把權重下載到 cwd 下的 checkpoints/，固定在工具目錄避免落進 repo
        rc = subprocess.run([str(DENOISE_PY), str(HERE / "make_variants.py"), str(args.source), str(args.root),
                             "--only", *args.prepare], env=env, cwd=DENOISE_PY.parents[2]).returncode
        log(f"降噪產生結束 rc={rc}")

    while True:
        todo = pending(args.root, args.order)
        if not todo:
            log("佇列清空")
            return 0
        vid = todo[0]
        out = args.root / "transcripts" / vid
        out.mkdir(parents=True, exist_ok=True)
        log(f"轉錄開始: {vid}（剩 {len(todo)} 個）")
        cmd = [sys.executable, str(HERE / "run_local_pipeline.py"),
               str(args.root / "denoised" / vid / f"{vid}.wav"), str(out)]
        vad_source = args.root / "denoised" / vid / "vad_source.txt"
        if vad_source.exists():
            cmd += ["--vad-audio", vad_source.read_text(encoding="utf-8").strip()]
        with open(out / "stdout.txt", "w", encoding="utf-8") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env).returncode
        if rc != 0 and not (out / "error.txt").exists():
            (out / "error.txt").write_text(f"run_local_pipeline 結束碼 {rc}，見 stdout.txt", encoding="utf-8")
        log(f"轉錄結束: {vid} rc={rc}")


if __name__ == "__main__":
    sys.exit(main())
