"""移除轉錄結果中「複誦 system prompt」的行（上下文提示的副作用）。

Qwen3-ASR 給了上下文 system prompt 後，遇到很短、幾乎沒內容的片段（實測 0.9–2.1 秒，
正常片段中位數 7.5 秒）會把提示詞原封不動吐出來當成轉錄結果。實驗 C 有 76/359 個片段中獎。
判定方式：與提示文字的最長共同子串 ≥ MIN_SUBSTR 字，或正規化後相似度 ≥ MIN_RATIO。

輸出 transcript_cleaned.lrc / .srt / .txt 與 echo_removed.json（被移除的行，供核對）。

用法（backend venv，需要 app.services.converter）：
  backend\\.venv\\Scripts\\python.exe tests\\denoise_study\\clean_prompt_echo.py TRANSCRIPT_LRC --preset zh_tw_log4j
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(os.environ.get("AIT_BACKEND_DIR", REPO_ROOT / "backend"))))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_local_pipeline import ASR_CONTEXT_PRESETS  # noqa: E402

MIN_SUBSTR = 20
MIN_RATIO = 0.6
LINE_RE = re.compile(r"(\[\d+:\d+(?:\.\d+)?\])(\[S\d+\])?\s*(.*)")


def normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE).lower()


def is_echo(text: str, context_norm: str) -> tuple[bool, float, int]:
    norm = normalize(text)
    if not norm:
        return False, 0.0, 0
    match = SequenceMatcher(None, norm, context_norm, autojunk=False).find_longest_match(
        0, len(norm), 0, len(context_norm))
    ratio = match.size / len(norm)
    echo = match.size >= MIN_SUBSTR or (len(norm) >= 20 and ratio >= MIN_RATIO)
    return echo, round(ratio, 3), match.size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lrc", type=Path)
    parser.add_argument("--preset", default="zh_tw_log4j", choices=sorted(ASR_CONTEXT_PRESETS))
    args = parser.parse_args()

    from app.services.converter.service import convert_from_lrc

    context_norm = normalize(ASR_CONTEXT_PRESETS[args.preset]["system"])
    kept, removed = [], []
    for line in args.lrc.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(line)
        if not m:
            kept.append(line)
            continue
        echo, ratio, size = is_echo(m.group(3), context_norm)
        (removed if echo else kept).append(line if not echo else
                                          {"line": line, "overlap_ratio": ratio, "common_chars": size})

    out_dir = args.lrc.parent
    cleaned = "\n".join(kept)
    (out_dir / "transcript_cleaned.lrc").write_text(cleaned, encoding="utf-8")
    formats = convert_from_lrc(cleaned)
    (out_dir / "transcript_cleaned.srt").write_text(formats.srt, encoding="utf-8")
    (out_dir / "transcript_cleaned.txt").write_text(formats.txt, encoding="utf-8")
    (out_dir / "echo_removed.json").write_text(
        json.dumps({"preset": args.preset, "removed_lines": len(removed), "kept_lines": len(kept),
                    "removed": removed}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"保留 {len(kept)} 行、移除 {len(removed)} 行提示詞回音 → {out_dir / 'transcript_cleaned.lrc'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
