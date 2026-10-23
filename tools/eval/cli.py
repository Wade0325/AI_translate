"""``python -m tools.eval`` 的指令：eval（對標準答案計分）與 selftest（自我驗證）。

在 repo 根目錄執行，用法見同一個資料夾的 README.md。離線計分，不呼叫任何 API、不讀音檔。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from . import mer, reference_set, selftest
from .custom_vocabulary import load_custom_vocabulary

REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_ENV = "AIT_LAB_DIR"


class UsageError(Exception):
    """參數指到不存在或不能用的檔案；訊息直接給人看。"""


def _git(*args: str, cwd: Path) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              encoding="utf-8", check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip()


def default_lab_dir(repo_root: Path = REPO_ROOT) -> Path:
    """研究區：環境變數 AIT_LAB_DIR，否則是主 checkout 旁邊的 ``<主 checkout 名稱>-lab``。

    主 checkout 是 ``git rev-parse --path-format=absolute --git-common-dir`` 的上一層，所以
    從 worktree 執行也找到同一個研究區；不在 git 裡時以這份程式所在的 repo 為準。
    """
    env = os.environ.get(LAB_ENV)
    if env:
        return Path(env)
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=repo_root)
    main = Path(common).parent if common else repo_root
    return main.parent / f"{main.name}-lab"


def _tool_version() -> str | None:
    """這份工具的 commit；tools/eval 有沒 commit 的改動時加上 +dirty。"""
    commit = _git("rev-parse", "HEAD", cwd=REPO_ROOT)
    if commit is None:
        return None
    dirty = _git("status", "--porcelain", "--", "tools/eval", cwd=REPO_ROOT)
    return commit + ("+dirty" if dirty else "")


def _available(directory: Path, suffix: str) -> str:
    names = sorted(p.name.removesuffix(suffix) for p in directory.glob(f"*{suffix}"))
    if names:
        return f"\n{directory} 底下有：" + "、".join(names)
    return (f"\n{directory} 底下沒有任何 *{suffix}；用參數指定資料夾，"
            f"或用環境變數 {LAB_ENV} 指定研究區。")


def _resolve(names: Sequence[str], directory: Path, suffix: str, what: str) -> list[Path]:
    """存在的路徑照用；否則當成名稱，到資料夾裡找 ``<名稱><suffix>``。"""
    out = []
    for name in names:
        path = Path(name)
        if not path.is_file():
            path = directory / (name if name.endswith(suffix) else f"{name}{suffix}")
        if not path.is_file():
            raise UsageError(f"找不到{what} {name}：{path} 不存在。" + _available(directory, suffix))
        out.append(path)
    return out


def _refuse_writing_references(target: Path, reference_dir: Path,
                               references: Sequence[Path]) -> None:
    resolved = target.resolve()
    for protected in {reference_dir.resolve(), *(p.resolve().parent for p in references)}:
        if resolved == protected or protected in resolved.parents:
            raise UsageError(f"--json 不能寫進標準答案的資料夾 {protected}：工具只讀取標準答案，不寫入。")


def _evaluate(excerpts, hyp_path: Path, vocabulary: dict, bootstrap: int) -> list[mer.Result]:
    return [mer.evaluate(ex, reference_set.clip_hyp(hyp_path, ex.start, ex.end), vocabulary,
                         bootstrap=bootstrap)
            for ex in excerpts]


def _dump(results: Sequence[mer.Result], path: Path) -> dict:
    return {
        "hyp": str(path),
        "per_excerpt": [{
            "name": r.name, "window": r.window, "utts": r.n_utts,
            "ref_len": r.ref_len, "hyp_len": r.hyp_len, "unk": r.unk,
            "subs": r.subs, "dels": r.dels, "ins": r.ins,
            "mer": round(r.mer, 4), "ci": [round(c, 4) for c in r.ci],
            "mer_no_overlap": round(r.mer_no_overlap, 4),
            "cp_mer_local": round(r.cp_mer_local, 4),
            "cp_mer_global": round(r.cp_mer_global, 4),
            "mapping_local": r.mapping_local,
            "term_recall": round(r.term_recall, 4),
            "term_hit": r.term_hit, "term_total": r.term_total,
            "term_false_ins": r.term_false_ins,
            "budget": r.budget, "examples": r.examples,
        } for r in results],
        "total_mer": round(sum(r.errors for r in results)
                           / max(1, sum(r.ref_len for r in results)), 4),
    }


def cmd_eval(a) -> int:
    lab = default_lab_dir()
    reference_dir = Path(a.reference_dir) if a.reference_dir else lab / "data" / "eval"
    vocabulary_dir = Path(a.vocabulary_dir) if a.vocabulary_dir else lab / "glossaries"

    paths = _resolve(a.reference, reference_dir, ".txt", "標準答案")
    if a.json:
        _refuse_writing_references(Path(a.json), reference_dir, paths)
    hyps = [Path(h) for h in (a.hyp, a.vs) if h]
    for h in hyps:
        if not h.is_file():
            raise UsageError(f"找不到轉錄結果：{h}")

    excerpts = [reference_set.read_reference(p, allow_draft=a.allow_draft) for p in paths]
    drafts = sum(e.draft_marks for e in excerpts)
    if drafts:
        print(f"⚠ 使用草稿標準答案（{drafts} 處未確認標記），數字只能當工具驗證，"
              f"不能當結論。\n")
    for h in hyps:
        for warning in reference_set.hyp_warnings(h):
            print(f"⚠ {h.name}：{warning}")

    vpaths = _resolve(a.vocabulary or [], vocabulary_dir, ".json", "術語表")
    vocabulary = load_custom_vocabulary(*vpaths)

    hyp_a = hyps[0]
    res_a = _evaluate(excerpts, hyp_a, vocabulary, a.bootstrap)
    map_a, cp_a = mer.global_mapping(res_a)
    print(mer.format_report(res_a, hyp_a.name, map_a, cp_a))

    systems = [_dump(res_a, hyp_a)]
    if a.vs:
        hyp_b = hyps[1]
        res_b = _evaluate(excerpts, hyp_b, vocabulary, a.bootstrap)
        map_b, cp_b = mer.global_mapping(res_b)
        print("\n" + "=" * 70 + "\n")
        print(mer.format_report(res_b, hyp_b.name, map_b, cp_b))

        print("\n" + "=" * 70)
        print(f"成對比較（{hyp_b.name} − {hyp_a.name}）：負值代表後者較好")
        lens = [n for r in res_a for n in r.line_ref_len]
        ea = [e for r in res_a for e in r.line_errors]
        eb = [e for r in res_b for e in r.line_errors]
        mean, lo, hi = mer.paired_delta_ci(ea, eb, lens, n=a.bootstrap)
        sig = "顯著" if (lo < 0 and hi < 0) or (lo > 0 and hi > 0) else "不顯著（區間跨 0）"
        print(f"  ΔMER {mean*100:+.2f} pp   95% CI [{lo*100:+.2f}, {hi*100:+.2f}]   {sig}")
        systems.append(_dump(res_b, hyp_b))

    if a.json:
        out = Path(a.json)
        payload = {
            "command": "eval",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "tool_version": _tool_version(),
            "reference": [str(p) for p in paths],
            "reference_draft_marks": drafts,
            "vocabulary": [p.name for p in vpaths],
            "bootstrap": a.bootstrap,
            "systems": systems,
            "global_mapping": {"mapping": map_a, "cp_mer": round(cp_a, 4)},
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已寫入：{out}")
    return 0


def cmd_selftest(_) -> int:
    return 0 if selftest.run() else 1


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m tools.eval",
        description="評測工具：拿轉錄結果和標準答案比對（離線，不呼叫任何 API）。")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", help="正規化、錯誤分類與同音判斷的自我驗證"
                   ).set_defaults(fn=cmd_selftest)

    p = sub.add_parser("eval", help="對標準答案計分（錯字率／說話者／錯誤預算）")
    p.add_argument("--reference", nargs="+", required=True, metavar="名稱或路徑",
                   help="標準答案；只給名稱時到 --reference-dir 找 <名稱>.txt（例如 demo_A.draft）")
    p.add_argument("--hyp", required=True, help="轉錄結果的 LRC")
    p.add_argument("--vs", help="另一份轉錄結果，和 --hyp 做成對比較")
    p.add_argument("--vocabulary", nargs="*", metavar="名稱或路徑",
                   help="術語表；只給名稱時到 --vocabulary-dir 找 <名稱>.json")
    p.add_argument("--reference-dir",
                   help=f"標準答案的資料夾（預設：研究區的 data/eval；研究區可用 {LAB_ENV} 指定）")
    p.add_argument("--vocabulary-dir", help="術語表的資料夾（預設：研究區的 glossaries）")
    p.add_argument("--bootstrap", type=int, default=1000, help="信賴區間的重抽樣次數")
    p.add_argument("--allow-draft", action="store_true",
                   help="允許標準答案仍有草稿標記（只用來驗證工具本身）")
    p.add_argument("--json", metavar="路徑",
                   help="另外把數字寫成 JSON；不能寫進標準答案的資料夾")
    p.set_defaults(fn=cmd_eval)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.fn(args)
    except (UsageError, reference_set.ReferenceSetError) as e:
        print(e, file=sys.stderr)
        return 2
