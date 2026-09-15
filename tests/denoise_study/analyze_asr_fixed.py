"""實驗 A 分析：固定切段轉錄的成對比較 + 盲評題包。

每個版本：
  token_mean_logprob            Qwen3-ASR 自信度（越接近 0 越有把握）
  paired_vs_ref.delta_mean      與對照組同一塊的自信度差平均，含 bootstrap 95% 信賴區間
  paired_vs_ref.win_rate        同一塊自信度高於對照組的比例
  cer_vs_ref                    與對照組的字元差異率（改變了多少文字）
  cer_vs_consensus              與「逐塊共識文字」的差異率（共識 = 所有版本中與其他人總距離最小的那句）
  empty_chunks / han_chars / glossary / repeat_runs

盲評題包：挑各版本說法分歧最大的塊，去重後匿名（A/B/C…），附上前後文，
輸出 report/blind_A/packet_{n}.md 與對照表 key.json，交由評審選出最合理的文字。

用法（denoise venv）：
  python tests\\denoise_study\\analyze_asr_fixed.py ROOT [--ref 01_original_wav]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
from rapidfuzz.distance import Levenshtein

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_transcripts import GLOSSARY_GOOD, GLOSSARY_SUSPECT, HAN_RE, LATIN_RE, normalize, repeat_runs  # noqa: E402

import re  # noqa: E402

# 常用字的繁 / 簡對照（逐字一一對應），估計輸出偏繁體還是簡體
TRAD_CHARS = "這個們說設檔層級錄輸過濾實體還會對應時間問題為從來後裡點頭開關現發與進東車門長書見聽話讓學習給寫將麼樣種經"
SIMP_CHARS = "这个们说设档层级录输过滤实体还会对应时间问题为从来后里点头开关现发与进东车门长书见听话让学习给写将么样种经"
_PAIRS = [(t, s) for t, s in zip(TRAD_CHARS, SIMP_CHARS) if t != s]


def traditional_ratio(text: str) -> float | None:
    trad = sum(text.count(t) for t, _ in _PAIRS)
    simp = sum(text.count(s) for _, s in _PAIRS)
    return round(trad / (trad + simp), 4) if trad + simp else None


def bootstrap_ci(values: np.ndarray, n: int = 4000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(n, len(values)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--ref", default="01_original_wav")
    parser.add_argument("--blind-chunks", type=int, default=60)
    parser.add_argument("--packet-size", type=int, default=20)
    parser.add_argument("--src", default="asr_fixed", help="ROOT 下的結果資料夾（asr_context 等）")
    parser.add_argument("--no-blind", action="store_true")
    parser.add_argument("--min-distinct", type=int, default=3, help="盲評候選塊至少要有幾種不同說法")
    args = parser.parse_args()
    root: Path = args.root
    src = root / args.src
    if not (src / "chunks.json").exists():
        (src / "chunks.json").write_text((root / "asr_fixed" / "chunks.json").read_text(encoding="utf-8"),
                                         encoding="utf-8")

    data = {}
    for f in sorted(src.glob("*.json")):
        if f.name != "chunks.json":
            data[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    ids = list(data)
    n_chunks = len(data[ids[0]]["chunks"])
    texts = {vid: [c["text"] for c in data[vid]["chunks"]] for vid in ids}
    norms = {vid: [normalize(t) for t in texts[vid]] for vid in ids}

    def chunk_conf(vid):
        return np.array([c["logprob_sum"] / c["n_tokens"] if c["n_tokens"] else np.nan
                         for c in data[vid]["chunks"]])

    # 逐塊共識：與其他版本編輯距離總和最小的文字
    consensus = []
    for i in range(n_chunks):
        cands = [norms[v][i] for v in ids]
        costs = [sum(Levenshtein.distance(a, b) for b in cands) for a in cands]
        consensus.append(cands[int(np.argmin(costs))])
    consensus_raw = []
    for i in range(n_chunks):
        for v in ids:
            if norms[v][i] == consensus[i]:
                consensus_raw.append(texts[v][i])
                break

    ref_conf = chunk_conf(args.ref)
    metrics = {}
    for vid in ids:
        full = "".join(texts[vid])
        conf = chunk_conf(vid)
        both = ~np.isnan(conf) & ~np.isnan(ref_conf)
        delta = conf[both] - ref_conf[both]
        cer_ref = sum(Levenshtein.distance(a, b) for a, b in zip(norms[vid], norms[args.ref])) / \
            max(1, sum(len(b) for b in norms[args.ref]))
        cer_cons = sum(Levenshtein.distance(a, b) for a, b in zip(norms[vid], consensus)) / \
            max(1, sum(len(b) for b in consensus))
        lower = full.lower()
        m = {
            **data[vid]["summary"],
            "han_chars": len(HAN_RE.findall(full)),
            "latin_words": len(LATIN_RE.findall(full)),
            "cer_vs_ref": round(cer_ref, 4),
            "cer_vs_consensus": round(cer_cons, 4),
            "repeat_runs": repeat_runs(full),
            "traditional_ratio": traditional_ratio(full),
            "glossary_good": {k: len(re.findall(p, lower)) for k, p in GLOSSARY_GOOD.items()},
            "glossary_suspect": {k: len(re.findall(p, lower)) for k, p in GLOSSARY_SUSPECT.items()},
        }
        if vid != args.ref and len(delta):
            lo, hi = bootstrap_ci(delta)
            m["paired_vs_ref"] = {"chunks": int(len(delta)), "delta_mean": round(float(delta.mean()), 4),
                                  "ci95": [round(lo, 4), round(hi, 4)],
                                  "win_rate": round(float((delta > 0).mean()), 4),
                                  "loss_rate": round(float((delta < 0).mean()), 4)}
        m["glossary_good_total"] = sum(m["glossary_good"].values())
        m["glossary_suspect_total"] = sum(m["glossary_suspect"].values())
        metrics[vid] = m

    out_dir = root / "report"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{args.src}_metrics.json").write_text(
        json.dumps({"ref": args.ref, "chunks": n_chunks, "metrics": metrics}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out_dir / f"{args.src}_consensus.txt").write_text("\n".join(consensus_raw), encoding="utf-8")
    if args.no_blind:
        for vid, m in metrics.items():
            print(f"{vid:22s} conf {m['token_mean_logprob']:+.4f}  cerRef {m['cer_vs_ref']:.4f}  "
                  f"good {m['glossary_good_total']}  sus {m['glossary_suspect_total']}  "
                  f"trad {m['traditional_ratio']}  empty {m['empty_chunks']}")
        return 0

    # 盲評題包：分歧大（≥3 種不同說法）且共識長度 ≥ 8 字的塊，時間上均勻抽樣
    chunks_meta = json.loads((src / "chunks.json").read_text(encoding="utf-8"))
    candidates = [i for i in range(n_chunks)
                  if len({norms[v][i] for v in ids}) >= args.min_distinct and len(consensus[i]) >= 8]
    rng = random.Random(17)
    if len(candidates) > args.blind_chunks:
        step = len(candidates) / args.blind_chunks
        picked = [candidates[int(k * step + rng.random() * step)] for k in range(args.blind_chunks)]
    else:
        picked = candidates
    blind_dir = out_dir / ("blind_A" if args.src == "asr_fixed" else f"blind_{args.src}")
    blind_dir.mkdir(exist_ok=True)
    key = {}
    packets: list[list[str]] = [[]]
    for n, i in enumerate(picked, 1):
        uniq: dict[str, list[str]] = {}
        shown: dict[str, str] = {}
        for v in ids:
            uniq.setdefault(norms[v][i], []).append(v)
            shown.setdefault(norms[v][i], texts[v][i] or "（空白，未轉出文字）")
        order = list(uniq)
        rng.shuffle(order)
        labels = {chr(ord("A") + k): norm for k, norm in enumerate(order)}
        start = chunks_meta[i]["Start"]
        key[f"Q{n}"] = {"chunk": i, "time": f"{int(start // 60):02d}:{start % 60:05.2f}",
                        "labels": {lab: uniq[norm] for lab, norm in labels.items()}}
        prev_ctx = "".join(consensus_raw[max(0, i - 2):i]) or "（無）"
        next_ctx = "".join(consensus_raw[i + 1:i + 3]) or "（無）"
        block = [f"## Q{n}", f"前文：{prev_ctx}", f"後文：{next_ctx}", "候選："]
        block += [f"- {lab}: {shown[norm]}" for lab, norm in labels.items()]
        if len(packets[-1]) >= args.packet_size:
            packets.append([])
        packets[-1].append("\n".join(block))
    for k, p in enumerate(packets, 1):
        (blind_dir / f"packet_{k}.md").write_text("\n\n".join(p), encoding="utf-8")
    (blind_dir / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ref={args.ref}  chunks={n_chunks}  blind={len(picked)}（候選 {len(candidates)}）")
    for vid, m in metrics.items():
        p = m.get("paired_vs_ref", {})
        print(f"{vid:22s} conf {m['token_mean_logprob']:+.4f}  d {p.get('delta_mean', 0):+.4f} "
              f"ci {p.get('ci95', '')}  win {p.get('win_rate', '')}  cerRef {m['cer_vs_ref']:.4f}  "
              f"cerCons {m['cer_vs_consensus']:.4f}  empty {m['empty_chunks']}  han {m['han_chars']}  "
              f"good {m['glossary_good_total']}  sus {m['glossary_suspect_total']}  rep {m['repeat_runs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
