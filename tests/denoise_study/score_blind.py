"""盲評計分：把評審選出的最佳/最差匿名候選還原成版本，統計各版本勝率。

  best_rate   該版本的文字被評為「最佳（含並列）」的題目比例
  worst_rate  被評為「最差」的比例
  net         best_rate − worst_rate，附 bootstrap 95% 信賴區間（以題目為單位重抽）
  best_rate_hi_conf  只計評審信心 high/medium 的題目

用法：
  python tests\\denoise_study\\score_blind.py KEY_JSON OUT_JSON JUDGE_JSON [JUDGE_JSON ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("key", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("judges", type=Path, nargs="+")
    args = parser.parse_args()

    key = json.loads(args.key.read_text(encoding="utf-8"))
    verdicts = {}
    for path in args.judges:
        verdicts.update(json.loads(path.read_text(encoding="utf-8")))
    questions = [q for q in key if q in verdicts]
    variants = sorted({v for q in key.values() for vs in q["labels"].values() for v in vs})

    best = {v: np.zeros(len(questions)) for v in variants}
    worst = {v: np.zeros(len(questions)) for v in variants}
    conf_ok = np.array([verdicts[q].get("confidence") in ("high", "medium") for q in questions])
    for n, q in enumerate(questions):
        labels = key[q]["labels"]
        for lab in verdicts[q].get("best", []):
            for v in labels.get(lab, []):
                best[v][n] = 1
        for lab in verdicts[q].get("worst", []):
            for v in labels.get(lab, []):
                worst[v][n] = 1

    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(questions), size=(4000, len(questions)))
    scores = {}
    for v in variants:
        net = best[v] - worst[v]
        boot = net[idx].mean(axis=1)
        scores[v] = {
            "best_rate": round(float(best[v].mean()), 4),
            "worst_rate": round(float(worst[v].mean()), 4),
            "net": round(float(net.mean()), 4),
            "net_ci95": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
            "best_rate_hi_conf": round(float(best[v][conf_ok].mean()), 4) if conf_ok.any() else None,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"questions": len(questions), "hi_conf_questions": int(conf_ok.sum()),
                                    "scores": scores, "verdicts": verdicts}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"題數 {len(questions)}（高/中信心 {int(conf_ok.sum())}）")
    for v, s in sorted(scores.items(), key=lambda kv: -kv[1]["net"]):
        print(f"{v:22s} best {s['best_rate']:.3f}  worst {s['worst_rate']:.3f}  net {s['net']:+.3f} "
              f"{s['net_ci95']}  best(hi/med) {s['best_rate_hi_conf']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
