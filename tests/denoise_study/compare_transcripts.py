"""比較各版本的轉錄結果（無人工標準答案時的無參考指標 + 並排對照）。

指標：
  coverage_speech_windows   原檔 Silero 判定有 ≥5s 語音的 30s 視窗中，有轉錄行的比例（漏轉偵測）
  han_chars / latin_words   產出量
  suspicious_rate_lines     每秒字數 > 9（行起點到下一行起點）的行數，常見於幻覺或時間軸錯亂
  repeat_runs               同一 2~6 字片語連續重複 ≥4 次的次數（幻覺迴圈特徵）
  glossary                  log4j 領域詞：正確詞與典型誤聽詞出現次數
  diarization               各半段偵測到的說話者數、片段數
  mean_cer_vs_others        以 60s 視窗切齊後，與其他所有版本的平均字元錯誤率（越低越接近共識）

並排對照：report/side_by_side.md（具名）與 report/blind/ 下的匿名版（盲評用）。

用法（denoise venv，需要 rapidfuzz）：
  python tests\\denoise_study\\compare_transcripts.py ROOT
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

from rapidfuzz.distance import Levenshtein

LINE_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](?:\[(S\d+)\])?\s*(.*)")
HAN_RE = re.compile(r"[一-鿿]")
LATIN_RE = re.compile(r"[A-Za-z]+")
NORM_DROP_RE = re.compile(r"[\s\W_]+", re.UNICODE)

GLOSSARY_GOOD = {
    "logger": r"logger|log\s*ger|logger",
    "appender": r"append(?:er)?s?",
    "level": r"level",
    "marker": r"marker",
    "filter": r"filter",
    "layout": r"layout",
    "console": r"console",
    "rolling file": r"rolling\s*file",
    "log4j": r"log\s*4\s*j|log\s*for\s*j",
}
GLOSSARY_SUSPECT = {
    "logo(→logger)": r"logo",
    "label(→level)": r"label",
}


def parse_lrc(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(line)
        if m:
            rows.append({"t": int(m.group(1)) * 60 + float(m.group(2)),
                         "spk": m.group(3), "text": m.group(4).strip()})
    return rows


def normalize(text: str) -> str:
    return NORM_DROP_RE.sub("", text).lower()


def windows_text(rows: list[dict], size: float, total: float) -> list[str]:
    n = int(total // size) + 1
    buckets = [""] * n
    for r in rows:
        buckets[min(int(r["t"] // size), n - 1)] += r["text"]
    return buckets


def repeat_runs(text: str) -> int:
    count = 0
    for n in range(2, 7):
        count += len(re.findall(r"(.{%d})\1{3,}" % n, normalize(text)))
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--excerpt-count", type=int, default=12)
    parser.add_argument("--excerpt-seconds", type=float, default=45)
    args = parser.parse_args()
    root: Path = args.root

    speech = json.loads((root / "00_analysis" / "silero_segments_original.json").read_text(encoding="utf-8"))
    total = json.loads((root / "00_analysis" / "analysis.json").read_text(encoding="utf-8"))["duration_seconds"]

    variants = {}
    for folder in sorted((root / "transcripts").iterdir()):
        lrc = folder / "transcript.lrc"
        if lrc.exists():
            variants[folder.name] = {
                "rows": parse_lrc(lrc),
                "run": json.loads((folder / "run.json").read_text(encoding="utf-8")),
                "diar": json.loads((folder / "diarization.json").read_text(encoding="utf-8")),
            }
    if not variants:
        print("沒有完成的轉錄結果")
        return 1

    # 30s 視窗：原檔有 ≥5s 語音的視窗
    win = 30.0
    speech_windows = []
    for i in range(int(total // win) + 1):
        lo, hi = i * win, (i + 1) * win
        overlap = sum(max(0.0, min(e, hi) - max(s, lo)) for s, e in speech)
        if overlap >= 5.0:
            speech_windows.append(i)

    metrics = {}
    for vid, v in variants.items():
        rows = v["rows"]
        full = "".join(r["text"] for r in rows)
        lower = full.lower()
        covered = {int(r["t"] // win) for r in rows if r["text"]}
        fast = 0
        for a, b in zip(rows, rows[1:] + [{"t": total}]):
            dur = max(b["t"] - a["t"], 0.01)
            if len(normalize(a["text"])) / dur > 9 and len(normalize(a["text"])) > 8:
                fast += 1
        spk_lines = {}
        for r in rows:
            spk_lines[r["spk"]] = spk_lines.get(r["spk"], 0) + 1
        metrics[vid] = {
            "elapsed_minutes": round(v["run"]["elapsed_seconds"] / 60, 1),
            "silence_removal_used": bool(v["run"].get("vad")) and
                v["run"]["vad"].get("speech_ratio", 1) < v["run"].get("vad_skip_threshold", 0.9),
            "pipeline_vad_speech_ratio": v["run"].get("vad", {}).get("speech_ratio"),
            "diarization_calls": len(v["diar"]),
            "speakers_per_call": [len(c["speakers"]) for c in v["diar"]],
            "diar_segments": sum(len(c["segments"]) for c in v["diar"]),
            "lines": len(rows),
            "han_chars": len(HAN_RE.findall(full)),
            "latin_words": len(LATIN_RE.findall(full)),
            "coverage_speech_windows": round(len(covered & set(speech_windows)) / len(speech_windows), 4),
            "uncovered_speech_windows_at": [f"{int(i * win // 60):02d}:{int(i * win % 60):02d}"
                                            for i in speech_windows if i not in covered],
            "suspicious_rate_lines": fast,
            "repeat_runs": repeat_runs(full),
            "glossary_good": {k: len(re.findall(p, lower)) for k, p in GLOSSARY_GOOD.items()},
            "glossary_suspect": {k: len(re.findall(p, lower)) for k, p in GLOSSARY_SUSPECT.items()},
            "lines_per_speaker": spk_lines,
        }
        g = metrics[vid]
        g["glossary_good_total"] = sum(g["glossary_good"].values())
        g["glossary_suspect_total"] = sum(g["glossary_suspect"].values())

    # 60s 視窗 CER 矩陣
    ids = list(variants)
    wins = {vid: [normalize(t) for t in windows_text(variants[vid]["rows"], 60.0, total)] for vid in ids}
    matrix = {a: {} for a in ids}
    for a in ids:
        for b in ids:
            if a == b:
                continue
            edits = ref_len = 0
            for wa, wb in zip(wins[a], wins[b]):
                edits += Levenshtein.distance(wa, wb)
                ref_len += max(len(wb), 1)
            matrix[a][b] = round(edits / ref_len, 4)
    for vid in ids:
        others = [matrix[vid][o] for o in ids if o != vid]
        metrics[vid]["mean_cer_vs_others"] = round(sum(others) / len(others), 4) if others else None

    report_dir = root / "report"
    report_dir.mkdir(exist_ok=True)
    (report_dir / "transcript_metrics.json").write_text(
        json.dumps({"metrics": metrics, "cer_matrix": matrix}, ensure_ascii=False, indent=2), encoding="utf-8")

    # 並排對照：在語音視窗中均勻取樣
    rng = random.Random(17)
    step = max(1, len(speech_windows) // args.excerpt_count)
    starts = [speech_windows[i] * win for i in range(step // 2, len(speech_windows), step)][:args.excerpt_count]
    blind_dir = report_dir / "blind"
    blind_dir.mkdir(exist_ok=True)
    named, blind, keymap = [], [], {}
    for n, start in enumerate(starts, 1):
        end = start + args.excerpt_seconds
        head = f"## 片段 {n}：{int(start // 60):02d}:{int(start % 60):02d} – {int(end // 60):02d}:{int(end % 60):02d}"
        named.append(head)
        blind.append(head)
        order = ids[:]
        rng.shuffle(order)
        for label_idx, vid in enumerate(order):
            label = chr(ord("A") + label_idx)
            keymap.setdefault(str(n), {})[label] = vid
            lines = [f"[{r['spk']}] {r['text']}" for r in variants[vid]["rows"] if start <= r["t"] < end]
            body = "\n".join(lines) if lines else "（無轉錄）"
            named.append(f"\n### {vid}\n```\n{body}\n```")
            blind.append(f"\n### 版本 {label}\n```\n{body}\n```")
        named.append("")
        blind.append("")
    (report_dir / "side_by_side.md").write_text("\n".join(named), encoding="utf-8")
    (blind_dir / "blind_excerpts.md").write_text("\n".join(blind), encoding="utf-8")
    (blind_dir / "blind_key.json").write_text(json.dumps(keymap, ensure_ascii=False, indent=2), encoding="utf-8")

    for vid, m in metrics.items():
        print(f"{vid:24s} cov {m['coverage_speech_windows']:.3f}  han {m['han_chars']:6d}  lat {m['latin_words']:4d}  "
              f"fast {m['suspicious_rate_lines']:3d}  rep {m['repeat_runs']:3d}  good {m['glossary_good_total']:3d}  "
              f"sus {m['glossary_suspect_total']:3d}  spk {m['speakers_per_call']}  cer~ {m['mean_cer_vs_others']}  "
              f"vad {m['silence_removal_used']}  {m['elapsed_minutes']}min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
